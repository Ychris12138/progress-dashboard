import argparse
import json
from pathlib import Path
import sys

from .core import Context, Error, canonical, load_public, read_json
from .engine import approve, confirm_draft, import_draft, preview, project_change, verify_batch
from .render import build
from .sources import capture
from .publish import publish
from .initialize import local_init, prepare, bootstrap


def main(command):
    parser = argparse.ArgumentParser(description="Local progress dashboard")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--local-root", type=Path, default=None)
    if command == "import":
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--input", type=Path)
        group.add_argument("--confirm", metavar="DRAFT_ID")
        parser.add_argument("--digest")
    elif command == "project":
        parser.add_argument("action", choices=["create", "rename", "set-category"])
        parser.add_argument("--project-id")
        parser.add_argument("--name")
        parser.add_argument("--category", choices=["research", "part_time", "internship", "other"])
    elif command == "preview":
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--draft", nargs="+", action="extend")
        group.add_argument("--approve", metavar="BATCH_ID")
        group.add_argument("--verify", metavar="BATCH_ID")
        parser.add_argument("--digest")
    elif command == "build":
        parser.add_argument("--output", type=Path)
        parser.add_argument("--batch")
        parser.add_argument("--synthetic", action="store_true", help="build synthetic fixtures outside the repository")
    elif command == "capture":
        parser.add_argument("--input", type=Path, required=True)
    elif command == "publish":
        parser.add_argument("--batch", required=True)
        parser.add_argument("--recover-only", action="store_true")
    elif command == "initialize":
        parser.add_argument("action", choices=["local-init", "prepare", "bootstrap"])
        parser.add_argument("--remote", type=Path)
        parser.add_argument("--email")
        parser.add_argument("--digest")
    args = parser.parse_args()
    try:
        ctx = Context(args.repo, args.local_root or args.repo.parent / (args.repo.name + "-local"))
        if command == "import":
            if args.input:
                result = import_draft(ctx, read_json(args.input))
            else:
                if not args.digest:
                    raise Error("--confirm requires reviewed --digest")
                result = confirm_draft(ctx, args.confirm, args.digest)
        elif command == "project":
            result = project_change(ctx, args.action, args.project_id, args.name, args.category)
        elif command == "preview":
            if args.approve:
                if not args.digest:
                    raise Error("--approve requires reviewed --digest")
                result = approve(ctx, args.approve, args.digest)
            elif args.verify:
                _, manifest, digest = verify_batch(ctx, args.verify, args.digest)
                result = {"batch_id": manifest["batch_id"], "digest": digest, "valid": True}
            else:
                result = preview(ctx, args.draft)
        elif command == "build":
            result = build(ctx, args.output, args.batch, args.synthetic)
        elif command == "capture":
            result = capture(ctx, read_json(args.input))
        elif command == "publish":
            result = publish(ctx, args.batch, args.recover_only)
        elif command == "initialize":
            if args.action == "local-init":
                result = local_init(ctx, args.email)
            elif args.action == "prepare":
                if not args.remote:
                    raise Error("prepare requires --remote")
                result = prepare(ctx, args.remote, args.email)
            else:
                if not args.digest:
                    raise Error("bootstrap requires reviewed --digest")
                result = bootstrap(ctx, args.digest)
        else:
            projects, records = load_public(ctx.repo)
            result = {"valid": True, "projects": len(projects), "records": len(records)}
        print(canonical(result).decode(), end="")
        return 0
    except (Error, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
