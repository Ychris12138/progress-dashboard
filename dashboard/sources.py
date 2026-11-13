"""Read-only adapter boundary. Desktop tools are invoked by the owning Agent."""
from __future__ import annotations

from .core import (HASH, atomic_json, canonical, draft, fingerprint, identifier, now,
                   obj, read_json, require, sha, temporal, text, version)
from .engine import catalog, import_draft


def validate_source(value):
    obj(value, ["schema_version", "source_id", "host_id", "scan_id", "window", "cursor",
                "next_cursor", "has_more", "anchor_reached", "turns"], "source-result-v1")
    version(value["schema_version"])
    for key in ("source_id", "host_id"):
        text(value[key], key)
    identifier(value["scan_id"], "scan_id")
    obj(value["window"], ["since", "until"], "window")
    start = temporal(value["window"]["since"], exact=True)[0]
    end = temporal(value["window"]["until"], exact=True)[0]
    require(start <= end, "invalid scan window")
    for key in ("cursor", "next_cursor"):
        text(value[key], key, True)
    require(type(value["has_more"]) is bool and type(value["anchor_reached"]) is bool, "invalid coverage flags")
    require(value["has_more"] == (value["next_cursor"] is not None), "next_cursor/has_more mismatch")
    require(type(value["turns"]) is list and len(value["turns"]) <= 50, "at most 50 turns per page")
    seen = set()
    for turn in value["turns"]:
        obj(turn, ["turn_id", "started_at", "status", "items", "outcome", "reason", "drafts"], "source turn")
        text(turn["turn_id"], "turn_id")
        require(turn["turn_id"] not in seen, "duplicate turn")
        seen.add(turn["turn_id"])
        temporal(turn["started_at"], exact=True)
        require(turn["status"] in ("completed", "in_progress", "failed"), "invalid turn status")
        require(turn["outcome"] in ("generated", "no_record", "needs_review"), "invalid outcome")
        text(turn["reason"], "reason")
        require(type(turn["items"]) is list, "invalid items")
        messages = {}
        for item in turn["items"]:
            obj(item, ["item_id", "text", "sha256"], "source item")
            text(item["item_id"], "item_id")
            text(item["text"], "source text")
            require(item["item_id"] not in messages, "duplicate source item")
            require(item["sha256"] == sha(item["text"].encode("utf-8")), "source content hash mismatch")
            messages[item["item_id"]] = item
        require(type(turn["drafts"]) is list, "invalid source drafts")
        require((turn["outcome"] == "generated") == bool(turn["drafts"]), "generated outcome/drafts mismatch")
        if turn["status"] != "completed":
            require(not turn["drafts"] and turn["outcome"] == "needs_review", "unfinished turns cannot generate records")
        for d in turn["drafts"]:
            draft(d)
            ref = d["source"]
            require(ref is not None and ref["source_id"] == value["source_id"] and ref["turn_id"] == turn["turn_id"], "draft source mismatch")
            require(set(ref["item_ids"]) <= set(messages), "draft references missing evidence")
            evidence = [{"item_id": k, "sha256": messages[k]["sha256"]} for k in sorted(ref["item_ids"])]
            require(ref["content_sha256"] == fingerprint(evidence), "draft evidence hash mismatch")


def capture(ctx, result, fail_at=None):
    """Persist evidence first, then drafts, then an atomic receipt, finally coverage.

    Failpoint injection is for local recovery tests, never a CLI argument.
    Opaque cursors are traversal state; completed_through is a separate watermark.
    """
    validate_source(result)
    source_key = sha(result["source_id"].encode())
    page_key = fingerprint(result)
    root = ctx.local / "source-cache" / source_key / result["scan_id"]
    checkpoint_path = ctx.local / "checkpoints" / (source_key + ".json")
    scan_path = root / "scan.json"
    receipt_path = root / (page_key + ".committed.json")
    with ctx.lock():
        checkpoint = read_json(checkpoint_path) if checkpoint_path.exists() else {
            "source_id": result["source_id"], "completed_through": None, "turn_hashes": {},
            "recent_completed": [], "pending_scan": None}
        scan = read_json(scan_path) if scan_path.exists() else None
        if not scan:
            require(result["cursor"] is None, "new scan must start at newest page")
            require(checkpoint["pending_scan"] in (None, result["scan_id"]), "unfinished scan must resume before starting another")
            scan = {"window": result["window"], "next_cursor": None, "receipts": [], "finished": False, "turns": {}}
        else:
            require(scan["window"] == result["window"], "scan window changed")
        already_linked = page_key in scan["receipts"]
        if page_key in checkpoint.get("applied_pages", []):
            receipt = read_json(receipt_path)
            complete = scan["finished"] and all(t["status"] == "completed" for t in scan["turns"].values())
            return {"scan_id": result["scan_id"], "status": "complete" if complete else "incomplete",
                    "next_cursor": scan["next_cursor"], "processed": receipt["processed"],
                    "imports": [], "checkpoint": checkpoint, "replayed": True}
        if not already_linked:
            require(not scan["finished"] and scan["next_cursor"] == result["cursor"], "non-contiguous or stale cursor")
        if fail_at == "before_save":
            raise RuntimeError("injected before save")
        atomic_json(root / (page_key + ".source.json"), result)
        require(read_json(root / (page_key + ".source.json")) == result, "source readback failed")
    # Imports are idempotent. If interrupted, the durable source page contains every
    # draft needed to replay. The complete receipt freezes the resulting ID mappings.
    imports = []
    processed = []
    for turn in result["turns"]:
        digest = fingerprint({"status": turn["status"], "items": sorted(
            [{"item_id": i["item_id"], "sha256": i["sha256"]} for i in turn["items"]], key=lambda x: x["item_id"])})
        old_digest = checkpoint["turn_hashes"].get(turn["turn_id"])
        changed = old_digest is not None and old_digest != digest
        outcome = "needs_review" if changed or turn["status"] != "completed" else turn["outcome"]
        for d in turn["drafts"]:
            result_import = import_draft(ctx, d)
            if changed:
                # A changed turn may add evidence around an otherwise identical candidate.
                with ctx.lock():
                    from .engine import save_catalog
                    state = catalog(ctx)
                    state["drafts"][result_import["draft_id"]]["needs_review"] = True
                    save_catalog(ctx, state)
                result_import["needs_review"] = True
            imports.append(result_import)
        processed.append({"turn_id": turn["turn_id"], "started_at": turn["started_at"], "status": turn["status"],
                          "sha256": digest, "outcome": outcome, "content_changed": changed})
    with ctx.lock():
        # Serialize completion; reject concurrent scans rather than losing their state.
        latest_scan = read_json(scan_path) if scan_path.exists() else None
        require(latest_scan is None or latest_scan == scan, "scan changed concurrently; retry")
        latest_checkpoint = read_json(checkpoint_path) if checkpoint_path.exists() else checkpoint
        require(latest_checkpoint == checkpoint, "checkpoint changed concurrently; retry")
        state = catalog(ctx)
        frozen_drafts = {i["draft_id"]: state["drafts"][i["draft_id"]] for i in imports}
        receipt = {"source_id": result["source_id"], "scan_id": result["scan_id"], "page_sha256": page_key,
                   "processed": processed, "drafts": frozen_drafts}
        if not receipt_path.exists():
            atomic_json(receipt_path, receipt)
        require(read_json(receipt_path)["page_sha256"] == page_key, "receipt readback failed")
        if fail_at in ("after_save", "before_checkpoint"):
            raise RuntimeError("injected after durable receipt")
        if not already_linked:
            scan["receipts"].append(page_key)
            scan["next_cursor"] = result["next_cursor"]
            for turn in processed:
                scan["turns"][turn["turn_id"]] = turn
            scan["finished"] = result["anchor_reached"] or not result["has_more"]
        completed = [t for t in scan["turns"].values() if t["status"] == "completed"]
        incomplete_turns = [t for t in scan["turns"].values() if t["status"] != "completed"]
        checkpoint["turn_hashes"].update({t["turn_id"]: t["sha256"] for t in completed})
        ordered = sorted(completed, key=lambda t: (temporal(t["started_at"])[0], t["turn_id"]), reverse=True)
        checkpoint["recent_completed"] = [t["turn_id"] for t in ordered[:5]]
        # Never claim the new head is covered while a history gap or running turn remains.
        complete = scan["finished"] and not incomplete_turns
        if complete and ordered and (checkpoint.get("completed_through_at") is None or
                                     temporal(ordered[0]["started_at"])[0] >= temporal(checkpoint["completed_through_at"])[0]):
            checkpoint["completed_through"] = ordered[0]["turn_id"]
            checkpoint["completed_through_at"] = ordered[0]["started_at"]
        checkpoint["pending_scan"] = None if scan["finished"] else result["scan_id"]
        checkpoint["last_receipt"] = str(receipt_path.relative_to(ctx.local))
        checkpoint.setdefault("applied_pages", [])
        if page_key not in checkpoint["applied_pages"]:
            checkpoint["applied_pages"].append(page_key)
        atomic_json(scan_path, scan)
        # A crash between these two writes is recovered by replaying the same page.
        atomic_json(checkpoint_path, checkpoint)
    return {"scan_id": result["scan_id"], "status": "complete" if complete else "incomplete",
            "next_cursor": scan["next_cursor"], "processed": processed,
            "imports": imports, "checkpoint": checkpoint}
