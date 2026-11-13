"""Normalize an explicitly supplied, minimal Desktop response for local capture."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.core import Context, atomic_json, no_links, read_json, require
from dashboard.desktop import normalize

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--scan-id", required=True)
    p.add_argument("--since", required=True)
    p.add_argument("--until", required=True)
    p.add_argument("--request-cursor")
    p.add_argument("--poc-no-record", action="store_true")
    p.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--local-root", type=Path)
    a = p.parse_args()
    ctx = Context(a.repo, a.local_root or a.repo.parent / (a.repo.name + "-local"))
    require(no_links(a.output).resolve().is_relative_to(ctx.local), "source output must be in local_root")
    require(not no_links(a.input).resolve().is_relative_to(ctx.repo), "real Desktop input must be outside repository")
    atomic_json(a.output, normalize(read_json(a.input), a.scan_id, a.since, a.until, a.request_cursor, a.poc_no_record))
    print("Normalized local source page; no publication.")
