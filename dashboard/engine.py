from __future__ import annotations

import copy
import difflib
import json
from pathlib import Path
import uuid

from .core import (CONTENT_KEYS, Error, HASH, atomic_json, atomic_bytes, canonical,
                   dataset, draft, fingerprint, identifier, load_public, no_links,
                   now, obj, project, public_files, public_path, read_json, record,
                   reject_tree_links, require, sha, version)


def catalog(ctx):
    path = ctx.local / "drafts/catalog.json"
    return read_json(path) if path.exists() else {"drafts": {}, "identities": {}, "draft_keys": {}}


def save_catalog(ctx, value):
    atomic_json(ctx.local / "drafts/catalog.json", value)


def identity(value):
    source = value["source"]
    if source is None:
        return "manual:" + value["draft_id"]
    return "source:" + fingerprint({k: source[k] for k in ("source_id", "turn_id", "unit_id")})


def source_family(value):
    source = value["source"]
    return fingerprint({k: source[k] for k in ("source_id", "turn_id")}) if source else None


def candidate_digest(value):
    # Agent-generated draft IDs are not the identity of a source event.
    return fingerprint({k: v for k, v in value.items() if k not in ("draft_id", "verification")})


def import_draft(ctx, value):
    draft(value)
    with ctx.lock():
        state = catalog(ctx)
        key = identity(value)
        previous_key = state["draft_keys"].get(value["draft_id"])
        require(previous_key is None or previous_key == key, "draft_id cannot change source identity")
        previous = state["identities"].get(key)
        if previous:
            old = state["drafts"][previous]
            if old["input_digest"] == candidate_digest(value):
                return {"draft_id": previous, "record_id": old["candidate"]["record_id"], "duplicate": True,
                        "needs_review": old["needs_review"]}
        projects, records = load_public(ctx.repo)
        published = {r["record_id"]: r for r in records}
        revision = value["revision"]
        base = None
        if revision:
            target = revision["target_record_id"]
            base = published.get(target)
            if base is None:
                base = next((x.get("candidate") for x in state["drafts"].values()
                             if x.get("candidate", {}).get("record_id") == target), None)
            require(base is not None, "revision target not found")
            if previous:
                require(state["drafts"][previous]["candidate"]["record_id"] == target, "revision changes record identity")
        elif previous:
            base = state["drafts"][previous]["candidate"]
            require(base["record_id"] not in published, "published changes require explicit revision")
        candidate = {"schema_version": 1, "record_id": base["record_id"] if base else "rec_" + uuid.uuid4().hex,
                     "recorded_at": base["recorded_at"] if base else now()}
        candidate.update({k: copy.deepcopy(value[k]) for k in CONTENT_KEYS})
        record(candidate)
        if base:
            require(base["project_id"] == candidate["project_id"], "project_id is immutable")
            if base["occurred_at"] != candidate["occurred_at"]:
                require(revision and revision["correct_occurred_at"], "time correction flag required")
            if base["state_as_of"] != candidate["state_as_of"]:
                require(revision and revision["correct_state_as_of"], "state evidence correction flag required")
        family = source_family(value)
        known_family = family and any(d.get("source_family") == family for d in state["drafts"].values())
        needs_review = value["verification"] != "confirmed" or bool(value["source"] and (previous or known_family))
        draft_id = previous or value["draft_id"]
        require(draft_id not in state["drafts"] or previous, "draft_id already belongs to another operation")
        envelope = {"kind": "record", "draft_id": draft_id, "candidate": candidate,
                    "input": copy.deepcopy(value), "input_digest": candidate_digest(value),
                    "needs_review": needs_review, "source_family": family,
                    "base_record": published.get(candidate["record_id"])}
        envelope["review_digest"] = fingerprint({k: v for k, v in envelope.items() if k != "needs_review"})
        state["drafts"][draft_id] = envelope
        state["identities"][key] = draft_id
        state["draft_keys"][value["draft_id"]] = key
        save_catalog(ctx, state)
        return {"draft_id": draft_id, "record_id": candidate["record_id"], "duplicate": False,
                "needs_review": needs_review, "review_digest": envelope["review_digest"]}


def confirm_draft(ctx, draft_id, digest):
    with ctx.lock():
        state = catalog(ctx)
        require(draft_id in state["drafts"], "unknown draft")
        item = state["drafts"][draft_id]
        actual = fingerprint({k: v for k, v in item.items() if k not in ("needs_review", "review_digest")})
        require(actual == digest == item["review_digest"], "draft review digest changed")
        item["needs_review"] = False
        save_catalog(ctx, state)
    return {"draft_id": draft_id, "confirmed": True}


def project_change(ctx, action, project_id=None, name=None, category=None):
    projects, _ = load_public(ctx.repo)
    old = next((p for p in projects if p["project_id"] == project_id), None)
    if action == "create":
        project_id = project_id or "proj_" + uuid.uuid4().hex
        require(old is None, "project already exists")
        new = {"schema_version": 1, "project_id": project_id, "public_name": name, "category": category, "aliases": []}
    else:
        require(old is not None, "project not in public registry")
        new = copy.deepcopy(old)
        if action == "rename":
            new["public_name"] = name
            new["aliases"] = sorted(set([*old["aliases"], old["public_name"]]) - {name})
        elif action == "set-category":
            new["category"] = category
        else:
            raise Error("unknown project action")
    project(new)
    draft_id = "draft_" + uuid.uuid4().hex
    with ctx.lock():
        state = catalog(ctx)
        state["drafts"][draft_id] = {"kind": "project", "draft_id": draft_id, "candidate": new,
                                     "base_project": old, "needs_review": False}
        save_catalog(ctx, state)
    return {"draft_id": draft_id, "project_id": project_id}


def source_files(repo):
    load_public(repo)
    return {p.relative_to(repo).as_posix(): p.read_bytes() for p in (repo / "public").rglob("*.json")}


def manifest_validate(value):
    obj(value, ["schema_version", "batch_id", "created_at", "target", "base_commit", "base_public",
                "draft_ids", "operations", "files", "preview_sha256", "record_ids"], "approval-manifest-v1")
    version(value["schema_version"])
    identifier(value["batch_id"], "batch_id")
    from .core import temporal
    temporal(value["created_at"], exact=True)
    obj(value["target"], ["repository", "branch"], "target")
    require(value["target"]["branch"] == "main", "only main supported")
    require(value["target"]["repository"] is None or type(value["target"]["repository"]) is str, "invalid repository")
    require(value["base_commit"] is None or (type(value["base_commit"]) is str and
            len(value["base_commit"]) in (40, 64) and all(c in "0123456789abcdef" for c in value["base_commit"])), "invalid commit")
    for name in ("base_public", "files"):
        require(type(value[name]) is dict, "invalid file hashes")
        for path, digest in value[name].items():
            public_path(Path("/nonexistent-schema-check"), path)
            require(type(digest) is str and HASH.fullmatch(digest), "invalid file digest")
    for name in ("draft_ids", "record_ids"):
        require(type(value[name]) is list and len(value[name]) == len(set(value[name])), "invalid IDs")
        for item in value[name]:
            identifier(item, name)
    require(type(value["preview_sha256"]) is str and HASH.fullmatch(value["preview_sha256"]), "invalid preview digest")
    require(type(value["operations"]) is list, "invalid operations")
    paths = []
    for operation in value["operations"]:
        obj(operation, ["path", "action", "old_sha256", "new_sha256"], "operation")
        path = operation["path"]
        public_path(Path("/nonexistent-schema-check"), path)
        paths.append(path)
        old, new = value["base_public"].get(path), value["files"].get(path)
        require(old != new and operation["old_sha256"] == old and operation["new_sha256"] == new, "operation hash mismatch")
        require(operation["action"] == ("delete" if new is None else "add" if old is None else "modify"), "operation action mismatch")
    expected = sorted(p for p in set(value["base_public"]) | set(value["files"])
                      if value["base_public"].get(p) != value["files"].get(p))
    require(paths == expected, "operation coverage mismatch")


def preview(ctx, draft_ids):
    require(draft_ids and len(draft_ids) == len(set(draft_ids)), "select unique drafts")
    with ctx.lock():
        state = catalog(ctx)
        projects, records = load_public(ctx.repo)
        pmap = {p["project_id"]: p for p in projects}
        rmap = {r["record_id"]: r for r in records}
        touched = set()
        for draft_id in draft_ids:
            require(draft_id in state["drafts"], "unknown draft")
            item = state["drafts"][draft_id]
            require(not item["needs_review"], "draft requires evidence review")
            if item["kind"] == "record":
                require(fingerprint({k: v for k, v in item.items() if k not in ("needs_review", "review_digest")})
                        == item["review_digest"], "draft changed after import/review")
            candidate = item["candidate"]
            if item["kind"] == "project":
                key = candidate["project_id"]
                require(("project", key) not in touched, "multiple changes to same project")
                require(pmap.get(key) == item["base_project"], "stale project draft")
                pmap[key] = candidate
                touched.add(("project", key))
            else:
                key = candidate["record_id"]
                require(("record", key) not in touched, "multiple revisions to same record")
                require(rmap.get(key) == item["base_record"], "stale record draft")
                # Revalidate protected fields against immutable published base.
                if item["base_record"]:
                    old = item["base_record"]
                    require(all(old[k] == candidate[k] for k in ("record_id", "project_id", "recorded_at")), "immutable record field changed")
                    flags = item["input"]["revision"]
                    require(old["occurred_at"] == candidate["occurred_at"] or flags["correct_occurred_at"], "missing time correction")
                    require(old["state_as_of"] == candidate["state_as_of"] or flags["correct_state_as_of"], "missing state correction")
                rmap[key] = candidate
                touched.add(("record", key))
        dataset(list(pmap.values()), list(rmap.values()))
        candidates = public_files(list(pmap.values()), list(rmap.values()))
        base = source_files(ctx.repo)
        operations = []
        diff = []
        for path in sorted(set(base) | set(candidates)):
            old, new = base.get(path), candidates.get(path)
            if old == new:
                continue
            operations.append({"path": path, "action": "delete" if new is None else "add" if old is None else "modify",
                               "old_sha256": sha(old) if old is not None else None,
                               "new_sha256": sha(new) if new is not None else None})
            old_text = json.dumps(json.loads(old), ensure_ascii=False, sort_keys=True, indent=2) + "\n" if old else ""
            new_text = json.dumps(json.loads(new), ensure_ascii=False, sort_keys=True, indent=2) + "\n" if new else ""
            diff.extend(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True), fromfile="old/" + path, tofile="new/" + path))
        require(operations, "batch has no changes")
        batch_id = "batch_" + uuid.uuid4().hex
        batch = no_links(ctx.local / "approvals" / batch_id)
        batch.mkdir()
        for path, data in candidates.items():
            atomic_bytes(public_path(batch / "candidate", path), data)
        review = ("# 本地审批预览\n\n尚未发布。仓库、网站及 Git 历史公开；删除当前记录不会撤回旧版本。\n"
                  "\n请核对：项目和企业名称是否脱敏、科研结论是否有来源、状态和下一步是否真实。\n"
                  "来源证据在本地 drafts/catalog.json；下方仅为待公开内容。\n\n## 文件变更及完整前后差异\n\n```diff\n"
                  + "".join(diff) + "```\n\n## 完整候选数据\n\n```json\n"
                  + json.dumps({"projects": sorted(pmap.values(), key=lambda p: p["project_id"]),
                                "records": sorted(rmap.values(), key=lambda r: r["record_id"])}, ensure_ascii=False, sort_keys=True, indent=2)
                  + "\n```\n").encode("utf-8")
        atomic_bytes(batch / "preview.md", review)
        manifest = {"schema_version": 1, "batch_id": batch_id, "created_at": now(), "target": ctx.target(),
                    "base_commit": ctx.head(), "base_public": {p: sha(b) for p, b in sorted(base.items())},
                    "draft_ids": sorted(draft_ids), "record_ids": sorted(rmap), "operations": operations,
                    "files": {p: sha(b) for p, b in sorted(candidates.items())}, "preview_sha256": sha(review)}
        manifest_validate(manifest)
        atomic_json(batch / "manifest.json", manifest)
        digest = fingerprint(manifest)
        atomic_json(batch / "seal.json", {"manifest_sha256": digest})
        return {"batch_id": batch_id, "digest": digest, "preview": str(batch / "preview.md"), "operations": operations}


def verify_frozen(ctx, batch_id, expected_digest=None):
    identifier(batch_id, "batch_id")
    batch = no_links(ctx.local / "approvals" / batch_id)
    reject_tree_links(batch)
    manifest = read_json(batch / "manifest.json")
    manifest_validate(manifest)
    require(manifest["batch_id"] == batch_id, "batch identity mismatch")
    raw = (batch / "manifest.json").read_bytes()
    require(raw == canonical(manifest), "manifest serialization changed")
    digest = sha(raw)
    seal = read_json(batch / "seal.json")
    obj(seal, ["manifest_sha256"], "seal")
    require(digest == seal["manifest_sha256"] and (expected_digest is None or digest == expected_digest), "manifest digest changed")
    require(sha((batch / "preview.md").read_bytes()) == manifest["preview_sha256"], "preview changed")
    actual = source_files(batch / "candidate")
    require({p: sha(b) for p, b in actual.items()} == manifest["files"], "frozen candidate changed")
    return batch, manifest, digest


def verify_batch(ctx, batch_id, expected_digest=None):
    batch, manifest, digest = verify_frozen(ctx, batch_id, expected_digest)
    require(ctx.head() == manifest["base_commit"] and ctx.target() == manifest["target"], "Git baseline/target changed")
    require({p: sha(b) for p, b in source_files(ctx.repo).items()} == manifest["base_public"], "public baseline changed")
    return batch, manifest, digest


def approve(ctx, batch_id, digest):
    with ctx.lock():
        batch, manifest, actual = verify_batch(ctx, batch_id, digest)
        receipt = {"schema_version": 1, "batch_id": batch_id, "manifest_sha256": actual, "approved_at": now()}
        atomic_json(batch / "approval.json", receipt)
    return {"batch_id": batch_id, "approved": True, "published": False}
