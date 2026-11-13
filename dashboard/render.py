from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .core import (atomic_bytes, atomic_json, before, canonical, dataset, load_public,
                   no_links, now, read_json, obj, reject_tree_links, require, temporal)
from .engine import verify_batch


def latest(values, field):
    return sorted([r for r in values if not any(before(r[field], other[field]) for other in values)],
                  key=lambda r: (temporal(r["recorded_at"])[0], r["record_id"]))


def presentation(projects, records):
    dataset(projects, records)
    cards = []
    for p in sorted(projects, key=lambda p: p["project_id"]):
        items = [r for r in records if r["project_id"] == p["project_id"]]
        states = latest([r for r in items if r["state_snapshot"] is not None], "state_as_of")
        progress = latest([r for r in items if r["record_type"] == "progress"], "occurred_at")
        cards.append({"project": p, "state_snapshot": states[0]["state_snapshot"] if states else None,
                      "state_evidence_times": sorted(set(r["state_as_of"] for r in states)),
                      "latest_progress": progress,
                      "last_recorded_at": max((r["recorded_at"] for r in items), key=lambda x: temporal(x)[0], default=None)})
    days = {}
    for r in records:
        start, _, precision = temporal(r["occurred_at"])
        day = days.setdefault(start.date().isoformat(), {"date": start.date().isoformat(), "timed": [], "untimed": []})
        day["timed" if precision == "instant" else "untimed"].append(r)
    for day in days.values():
        day["timed"].sort(key=lambda r: (temporal(r["occurred_at"])[0], temporal(r["recorded_at"])[0], r["record_id"]))
        day["untimed"].sort(key=lambda r: (temporal(r["recorded_at"])[0], r["record_id"]))
    return {"schema_version": 1, "projects": cards, "timeline": [days[k] for k in sorted(days, reverse=True)],
            "data_updated_at": max((r["recorded_at"] for r in records), key=lambda x: temporal(x)[0], default=None)}


def build(ctx, output=None, batch_id=None, synthetic=False):
    require(not (batch_id and synthetic), "choose batch or synthetic preview, not both")
    manifest = None
    if synthetic:
        fixture = read_json(ctx.repo / "tests/fixtures/dashboard-demo.json")
        obj(fixture, ["schema_version", "synthetic", "projects", "records"], "synthetic fixture")
        require(fixture["schema_version"] == 1 and fixture["synthetic"] is True, "synthetic fixture marker required")
        projects, records = fixture["projects"], fixture["records"]
        dataset(projects, records)
        require(output is not None, "synthetic preview requires explicit output")
    elif batch_id:
        batch, manifest, _ = verify_batch(ctx, batch_id)
        projects, records = load_public(batch / "candidate")
        require(output is not None, "candidate preview requires explicit output")
    else:
        projects, records = load_public(ctx.repo)
    output = no_links(output or ctx.repo / "dist").resolve()
    require(output != ctx.repo and not ctx.repo.is_relative_to(output), "output overlaps repository root")
    require(not output.is_relative_to(ctx.local) and not ctx.local.is_relative_to(output), "output overlaps private state")
    if output.is_relative_to(ctx.repo):
        require(output == ctx.repo / "dist", "inside repo only dist is a valid output")
    if batch_id or synthetic:
        require(not output.is_relative_to(ctx.repo), "candidate previews must be outside repository")
    reject_tree_links(output)
    allowed = {"index.html", "styles.css", "app.js", "data.json", "build.json"}
    if output.exists():
        require(all(p.is_file() and p.name in allowed for p in output.iterdir()), "output contains unexpected files")
    assets = {}
    for name in ("index.html", "styles.css", "app.js"):
        source = no_links(ctx.repo / "src" / name)
        assets[name] = source.read_bytes()
    data = presentation(projects, records)
    head = ctx.head()
    remote = ctx.target()['repository'] or ''
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?', remote)
    actions_url = f'https://github.com/{match[1]}/actions' if match else None
    metadata = {"built_at": now(), "commit": head, "local_preview": batch_id is not None or synthetic,
                "synthetic": synthetic, "actions_url": actions_url,
                "data_changed_at": manifest["created_at"] if manifest else
                (ctx.git("log", "-1", "--format=%cI", "--", "public") or None) if head and not synthetic else None}
    output.mkdir(parents=True, exist_ok=True)
    for name, data_bytes in assets.items():
        atomic_bytes(output / name, data_bytes)
    atomic_json(output / "data.json", data)
    atomic_json(output / "build.json", metadata)
    return {"output": str(output), "projects": len(projects), "records": len(records), "local_preview": batch_id is not None or synthetic}
