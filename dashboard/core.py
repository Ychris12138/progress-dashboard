from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
STATUSES = {"planned", "active", "blocked", "paused", "done"}
CATEGORIES = {"research", "part_time", "internship", "other"}
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")
HASH = re.compile(r"^[0-9a-f]{64}$")


class Error(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Error(message)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def fingerprint(value):
    return sha(canonical(value))


def now():
    return dt.datetime.now(SHANGHAI).isoformat(timespec="microseconds")


def no_links(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), f"symbolic link refused: {part}")
    return path


def reject_tree_links(root):
    root = no_links(root)
    if root.exists():
        for base, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files:
                no_links(Path(base) / name)


def read_json(path):
    no_links(path)
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise Error("non-finite JSON number")
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),
                          object_pairs_hook=pairs, parse_constant=invalid)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Error(f"cannot read JSON: {path}: {type(exc).__name__}") from exc


def atomic_bytes(path, content):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        dirfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path, value):
    atomic_bytes(path, canonical(value))


def obj(value, keys, label):
    require(type(value) is dict, f"{label}: expected object")
    require(set(value) == set(keys), f"{label}: missing or unknown fields")


def text(value, label, nullable=False):
    if nullable and value is None:
        return
    require(type(value) is str and bool(value.strip()), f"{label}: expected nonempty text")
    require(len(value) <= 20000, f"{label}: text too long")


def identifier(value, label):
    require(type(value) is str and ID.fullmatch(value) is not None, f"{label}: invalid identifier")


def version(value):
    require(type(value) is int and value == 1, "unsupported schema_version")


def temporal(value, exact=False):
    require(type(value) is str, "time must be a string")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) and not exact:
            date = dt.date.fromisoformat(value)
            start = dt.datetime.combine(date, dt.time(), SHANGHAI)
            return start, start + dt.timedelta(days=1), "date"
        require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value),
                "expected date or RFC3339 timestamp with timezone")
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(SHANGHAI)
        return parsed, parsed, "instant"
    except ValueError as exc:
        raise Error("invalid date/time") from exc


def overlaps(a, b):
    lo, hi, precision = temporal(a)
    other_lo, other_hi, other_precision = temporal(b)
    if precision == other_precision == "instant":
        return lo == other_lo
    if precision == "instant":
        return other_lo <= lo < other_hi
    if other_precision == "instant":
        return lo <= other_lo < hi
    return lo < other_hi and other_lo < hi


def before(a, b):
    lo, hi, precision = temporal(a)
    other_lo, _, _ = temporal(b)
    return hi <= other_lo if precision == "date" else lo < other_lo


def snapshot(value):
    if value is None:
        return
    obj(value, ["status", "next_step", "blocker"], "state_snapshot")
    require(type(value["status"]) is str and value["status"] in STATUSES, "invalid status")
    text(value["next_step"], "next_step", True)
    text(value["blocker"], "blocker", True)


CONTENT_KEYS = ["project_id", "record_type", "occurred_at", "summary", "state_as_of", "state_snapshot"]
RECORD_KEYS = ["schema_version", "record_id", "recorded_at", *CONTENT_KEYS]
PROJECT_KEYS = ["schema_version", "project_id", "public_name", "category", "aliases"]


def content(value):
    identifier(value["project_id"], "project_id")
    require(value["record_type"] in ("progress", "state_update"), "invalid record_type")
    temporal(value["occurred_at"])
    text(value["summary"], "summary")
    require((value["state_as_of"] is None) == (value["state_snapshot"] is None), "snapshot/time null pairing")
    if value["state_as_of"] is not None:
        temporal(value["state_as_of"])
    snapshot(value["state_snapshot"])
    require(value["record_type"] != "state_update" or value["state_snapshot"] is not None,
            "state_update requires snapshot")


def record(value):
    obj(value, RECORD_KEYS, "public-record-v1")
    version(value["schema_version"])
    identifier(value["record_id"], "record_id")
    temporal(value["recorded_at"], exact=True)
    content(value)


def project(value):
    obj(value, PROJECT_KEYS, "public-project-v1")
    version(value["schema_version"])
    identifier(value["project_id"], "project_id")
    text(value["public_name"], "public_name")
    require(type(value["category"]) is str and value["category"] in CATEGORIES, "invalid category")
    require(type(value["aliases"]) is list, "aliases must be a list")
    for alias in value["aliases"]:
        text(alias, "alias")
    require(len(set(value["aliases"])) == len(value["aliases"]), "duplicate aliases")


def source_ref(value):
    if value is None:
        return
    obj(value, ["source_id", "turn_id", "item_ids", "unit_id", "content_sha256"], "source_ref")
    for key in ("source_id", "turn_id", "unit_id"):
        text(value[key], key)
    require(type(value["item_ids"]) is list and value["item_ids"], "item_ids required")
    for item in value["item_ids"]:
        text(item, "item_id")
    require(len(value["item_ids"]) == len(set(value["item_ids"])), "duplicate item_ids")
    require(type(value["content_sha256"]) is str and HASH.fullmatch(value["content_sha256"]), "invalid source hash")


def draft(value):
    obj(value, ["schema_version", "draft_id", *CONTENT_KEYS, "source", "evidence", "verification", "revision"], "draft-v1")
    version(value["schema_version"])
    identifier(value["draft_id"], "draft_id")
    content(value)
    source_ref(value["source"])
    text(value["evidence"], "evidence")
    require(value["verification"] in ("confirmed", "needs_review"), "invalid verification")
    revision = value["revision"]
    if revision is not None:
        obj(revision, ["target_record_id", "correct_occurred_at", "correct_state_as_of"], "revision")
        identifier(revision["target_record_id"], "target_record_id")
        require(all(type(revision[k]) is bool for k in ("correct_occurred_at", "correct_state_as_of")), "revision flags must be boolean")


PRIVATE_PATTERNS = [
    ("email", re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")),
    ("url", re.compile(r"(?i)(?:https?://|ssh://|git@|www\.|(?:github|gitlab)\.com/|plugin://|codex://)")),
    ("path", re.compile(r"(?:^|[\s\"'(：:])(?:/[^\s]|~/|[A-Za-z]:[\\/]|\\\\)|/(?:Users|home|private|tmp|var|Volumes|etc)/")),
    ("credential", re.compile(r"(?i)(?:gh[pousr]_[A-Za-z0-9]{8,}|github_pat_|sk-[A-Za-z0-9_-]{8,}|AKIA[A-Z0-9]{12,}|-----BEGIN .*PRIVATE KEY|(?:token|password|api[_-]?key)\s*[:=]\s*\S+)")),
    ("chat-id", re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")),
    ("phone", re.compile(r"(?<!\w)(?:\+?86[- .]?)?1[3-9]\d{9}(?!\w)|(?<!\w)(?:\+\d{1,3}[- .]?)?(?:\(?\d{3}\)?[- .])\d{3}[- .]\d{4}(?!\w)")),
]


def privacy(projects, records):
    findings = []
    def check(value, location):
        if isinstance(value, str):
            for rule, regex in PRIVATE_PATTERNS:
                if regex.search(value):
                    findings.append({"field": location, "rule": rule})
        elif isinstance(value, list):
            for i, item in enumerate(value):
                check(item, f"{location}[{i}]")
        elif isinstance(value, dict):
            for key, item in value.items():
                check(item, f"{location}.{key}")
    for i, p in enumerate(projects):
        check(p, f"projects[{i}]")
    for i, r in enumerate(records):
        check(r, f"records[{i}]")
    return findings


def dataset(projects, records, private_check=True):
    ids = set()
    for p in projects:
        project(p)
        require(p["project_id"] not in ids, "duplicate project_id")
        ids.add(p["project_id"])
    seen = set()
    snapshots = {}
    for r in records:
        record(r)
        require(r["project_id"] in ids, "unknown project_id")
        require(r["record_id"] not in seen, "duplicate global record_id")
        seen.add(r["record_id"])
        if r["state_snapshot"] is not None:
            for previous in snapshots.setdefault(r["project_id"], []):
                require(not overlaps(previous["state_as_of"], r["state_as_of"]) or
                        previous["state_snapshot"] == r["state_snapshot"], "overlapping conflicting snapshots")
            snapshots[r["project_id"]].append(r)
    if private_check:
        found = privacy(projects, records)
        require(not found, f"public-data-check rejected: {found}")


def bucket(record_value):
    date = temporal(record_value["occurred_at"])[0].date()
    return f"public/records/{date:%Y/%m/%d}.json"


def public_path(repo, relative):
    require(type(relative) is str and "\\" not in relative, "invalid operation path")
    path = PurePosixPath(relative)
    require(not path.is_absolute() and ".." not in path.parts and str(path) == relative, "unsafe operation path")
    require(relative == "public/projects.json" or
            re.fullmatch(r"public/records/\d{4}/\d{2}/\d{2}\.json", relative), "path outside public allowlist")
    if relative != "public/projects.json":
        temporal(relative.removeprefix("public/records/").removesuffix(".json").replace("/", "-"))
    result = no_links(Path(repo) / relative)
    require(result.resolve().is_relative_to(Path(repo).resolve()), "path escapes repo")
    return result


def public_files(projects, records):
    files = {"public/projects.json": canonical({"schema_version": 1, "projects": sorted(projects, key=lambda p: p["project_id"])})}
    groups = {}
    for r in records:
        groups.setdefault(bucket(r), []).append(r)
    for path, values in sorted(groups.items()):
        files[path] = canonical({"schema_version": 1, "records": sorted(values, key=lambda r: r["record_id"])})
    return files


def load_public(repo):
    root = Path(repo) / "public"
    reject_tree_links(root)
    p = read_json(public_path(repo, "public/projects.json"))
    obj(p, ["schema_version", "projects"], "project registry")
    version(p["schema_version"])
    require(type(p["projects"]) is list, "projects must be a list")
    records = []
    for file in sorted(root.rglob("*")):
        if not file.is_file():
            continue
        if file.name == ".gitkeep":
            require(file.stat().st_size == 0, "placeholder must be empty")
            continue
        relative = file.relative_to(repo).as_posix()
        public_path(repo, relative)
        if relative == "public/projects.json":
            continue
        value = read_json(file)
        obj(value, ["schema_version", "records"], "daily records")
        version(value["schema_version"])
        require(type(value["records"]) is list and value["records"], "empty daily file must be removed")
        for r in value["records"]:
            record(r)
            require(bucket(r) == relative, "record stored in wrong date bucket")
        records.extend(value["records"])
    dataset(p["projects"], records)
    return p["projects"], records


class Context:
    def __init__(self, repo, local):
        self.repo = no_links(repo).resolve()
        self.local = no_links(local).resolve()
        require(not self.repo.is_relative_to(self.local) and not self.local.is_relative_to(self.repo), "repo/local roots overlap")
        for parent in (self.local, *self.local.parents):
            require(not (parent / ".git").exists(), "local_root is inside a Git worktree")
        self.local.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("drafts", "approvals", "source-mappings", "checkpoints", "source-cache", "reports"):
            no_links(self.local / name).mkdir(exist_ok=True, mode=0o700)

    @contextlib.contextmanager
    def lock(self):
        lock_path = no_links(self.local / ".lock")
        with lock_path.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def git(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env['GIT_TERMINAL_PROMPT'] = '0'
        result = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, env=env)
        return result.stdout.strip() if result.returncode == 0 else None

    def head(self):
        # Do not accidentally use a parent repository's HEAD.
        top = self.git("rev-parse", "--show-toplevel")
        return self.git("rev-parse", "HEAD") if top == str(self.repo) else None

    def target(self):
        return {"repository": self.git("remote", "get-url", "origin"), "branch": "main"}
