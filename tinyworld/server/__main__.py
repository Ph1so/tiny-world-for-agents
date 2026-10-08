"""python -m tinyworld.server --runs runs --runs samples --port 8000

New runs started from the viewer go into the first --runs directory."""
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from tinyworld.server.app import DEFAULT_VIEWER_DIST, create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve run folders to the viewer.")
    ap.add_argument("--runs", action="append", default=None,
                    help="a directory of run folders. Repeat to serve several (default: runs)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--viewer-dist", default=str(DEFAULT_VIEWER_DIST),
                    help="built viewer to serve at / (default: viewer/dist)")
    ap.add_argument("--read-only", action="store_true",
                    help="turn off starting, pausing and stopping runs from the viewer")
    args = ap.parse_args()
    dirs = [Path(d) for d in (args.runs or ["runs"])]
    app = create_app(dirs, Path(args.viewer_dist), controls=not args.read_only)
    print(f"serving runs from {', '.join(str(d) for d in dirs)} on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
