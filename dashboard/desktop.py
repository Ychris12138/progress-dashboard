"""Normalize explicitly supplied Desktop read_thread results, never scan files.

This module does not invoke Desktop MCP itself. The Agent reads the selected
chat and supplies only necessary visible messages; reasoning/tool outputs are
excluded. A source item hash covers exactly the retained message text.
"""
from .core import require, sha
from .sources import validate_source
import datetime as dt


def normalize(response, scan_id, since, until, request_cursor=None, poc_no_record=False):
    thread = response["thread"]
    require(thread["kind"] == "codex", "only Codex Desktop response supported")
    turns = []
    for turn in response["turns"]:
        complete = turn["status"] == "completed"
        items = []
        if complete:
            for item in turn["items"]:
                if item["type"] in ("agentMessage", "plan"):
                    value = item.get("text", "")
                elif item["type"] == "userMessage":
                    value = "\n".join(c.get("text", "") for c in item.get("content", []) if c.get("type") == "text")
                else:
                    continue
                if value.strip():
                    items.append({"item_id": item["id"], "text": value, "sha256": sha(value.encode("utf-8"))})
        turns.append({"turn_id": turn["id"], "started_at": dt.datetime.fromtimestamp(turn["startedAt"], dt.timezone.utc).isoformat(),
                      "status": "completed" if complete else "in_progress" if turn["status"] == "inProgress" else "failed",
                      "items": items, "outcome": "no_record" if complete and poc_no_record else "needs_review",
                      "reason": "仅验证读取接口，本次不提取业务进度" if poc_no_record and complete else "待完成轮次或人工提取核实",
                      "drafts": []})
    value = {"schema_version": 1, "source_id": thread["id"], "host_id": thread.get("hostId", "local"),
             "scan_id": scan_id, "window": {"since": since, "until": until}, "cursor": request_cursor,
             "next_cursor": response["page"]["nextCursor"], "has_more": response["page"]["hasMore"],
             "anchor_reached": False, "turns": turns}
    validate_source(value)
    return value
