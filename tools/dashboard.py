#!/usr/bin/env python3
"""CLI for the supervisor dashboard: serve the live UI, list runs, or dump one view model.

Examples::

    python3 tools/dashboard.py                    # serve http://127.0.0.1:8787
    python3 tools/dashboard.py --port 8791 --no-browser
    python3 tools/dashboard.py --list             # terminal table of runs
    python3 tools/dashboard.py --run-id fashion_apparel/campaign_cherry_dress_01 --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import runs as runs_module  # noqa: E402
from dashboard.server import create_app  # noqa: E402
from pipeline.config import OUTPUT_DIR  # noqa: E402

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="KOL pipeline supervisor dashboard (live telemetry + artifacts).",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"bind host (default {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"bind port (default {DEFAULT_PORT})")
    parser.add_argument(
        "--out-dir",
        default=None,
        help=f"pipeline output root to inspect (default {OUTPUT_DIR})",
    )
    parser.add_argument("--list", action="store_true", help="print a table of discovered runs and exit")
    parser.add_argument("--run-id", default=None, help="run id (topic/project_id, or bare legacy project_id)")
    parser.add_argument("--json", action="store_true", help="print JSON to stdout instead of serving")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    return parser


def _format_elapsed(value: Optional[float]) -> str:
    if value is None:
        return "-"
    seconds = int(max(0.0, float(value)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _truncate(text: Optional[str], width: int) -> str:
    value = (text or "-").replace("\n", " ").strip() or "-"
    if len(value) <= width:
        return value
    return value[: max(0, width - 1)] + "…"


def print_run_table(runs: List[Dict[str, Any]]) -> None:
    """Print a fixed-width table of runs (run_id, status, stages done, current stage, product, elapsed)."""
    headers = ("RUN ID", "STATUS", "STAGES", "CURRENT", "PRODUCT", "ELAPSED", "LAYOUT")
    widths = (42, 10, 7, 8, 34, 9, 9)
    line = "  ".join(header.ljust(width) for header, width in zip(headers, widths))
    print(line)
    print("-" * len(line))
    for run in runs:
        stages = f"{run.get('completed_stages') or 0}/{run.get('total_stages') or 0}"
        current = run.get("current_stage")
        row = (
            _truncate(run.get("run_id"), widths[0]),
            _truncate(run.get("status"), widths[1]),
            stages.ljust(widths[2]),
            (str(current) if current is not None else "-").ljust(widths[3]),
            _truncate(run.get("product_name"), widths[4]),
            _format_elapsed(run.get("elapsed_seconds")).ljust(widths[5]),
            _truncate(run.get("layout"), widths[6]),
        )
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)))
    if not runs:
        print("(no runs found)")


def _silence_stdout() -> None:
    """Detach stdout after a broken pipe so interpreter shutdown stays quiet."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except Exception:
        pass


def _dump_json(payload: Any) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    base_dir = Path(args.out_dir).resolve() if args.out_dir else runs_module.resolve_base_dir(None)

    try:
        if args.list:
            print_run_table(runs_module.discover_runs(base_dir))
            return 0

        if args.json:
            if args.run_id:
                run_ref = runs_module.resolve_run(args.run_id, base_dir)
                _dump_json(runs_module.build_view(run_ref))
            else:
                _dump_json({"base_dir": str(base_dir), "runs": runs_module.discover_runs(base_dir)})
            return 0
    except (BrokenPipeError, KeyboardInterrupt):
        _silence_stdout()
        return 0

    app = create_app(base_dir)
    url = f"http://{args.host}:{args.port}/"
    if args.run_id:
        url = f"{url}?run={args.run_id}"
    print(f"KOL supervisor dashboard serving {base_dir}")
    print(f"Open: {url}")
    print("Endpoints: /api/health  /api/runs  /api/runs/{run_id}  /api/runs/{run_id}/stream")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
