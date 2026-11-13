"""Build an isolated local preview and serve it under the future Pages subpath."""
import argparse
import functools
import http.server
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard.core import Context, reject_tree_links
from dashboard.render import build

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local-only preview, no GitHub connection")
    parser.add_argument("--synthetic", action="store_true", help="use synthetic fixtures, keep public data empty")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--local-root", type=Path)
    parser.add_argument("--port", type=int, default=0, help="0 chooses an available loopback port")
    args = parser.parse_args()
    ctx = Context(args.repo, args.local_root or args.repo.parent / (args.repo.name + "-local"))
    # A dedicated directory ensures the HTTP server cannot list private state or
    # other applications' temporary files. Keep preview output for later review.
    site = Path(tempfile.mkdtemp(prefix="progress-dashboard-ui-")).resolve()
    output = site / "progress-dashboard"
    build(ctx, output, synthetic=args.synthetic)
    reject_tree_links(site)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Preview: http://127.0.0.1:{server.server_port}/progress-dashboard/", flush=True)
        print(f"Output: {output}\nCtrl-C stops this local preview. No data is uploaded.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Local preview stopped; output retained.")
