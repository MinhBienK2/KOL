#!/usr/bin/env python3
"""Convenience CLI wrapper for Chief AI Commercial Director.

Agent contract
--------------
* ``--json`` prints exactly one JSON object on stdout (pipeline chatter goes to stderr).
* Exit codes: 0 success, 1 a stage failed, 2 invalid input / unmet prerequisites,
  3 the Stage 8 Verification Gates rejected the master (media exists, regenerate and re-verify).
* ``--inject NAME=PATH`` installs a validated canonical artifact (brief, script, scene_plan,
  asset_manifest) and resumes after the stage that would have produced it.
* ``--check`` validates a plan (stages to run, prerequisites) without executing or writing anything.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.archetypes import ProductArchetype
from pipeline.director import run_pipeline
from pipeline.workspace import ProjectWorkspace, first_stage_after

EXIT_OK = 0
EXIT_PIPELINE_FAILED = 1
EXIT_INVALID_INPUT = 2
EXIT_VERIFICATION_FAILED = 3

VERIFICATION_STAGE = 8
LAST_STAGE = 8


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chief AI Commercial Director Autonomous Pipeline CLI",
        epilog=(
            "exit codes: 0 ok | 1 stage failed | 2 invalid input or unmet prerequisites | "
            "3 verification gates failed. Example: --inject script=my_script.json resumes at stage 3."
        ),
    )
    parser.add_argument(
        "--campaign",
        default="campaign_lumina_mug_01",
        help="Campaign ID (defaults to campaign_lumina_mug_01)",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Project ID (alias for campaign ID)",
    )
    parser.add_argument(
        "--product",
        default="Ly Giữ Nhiệt Thông Minh Lumina Pro",
        help="Product name",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Affiliate link or raw product description",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Domain topic or product archetype (e.g. fashion_apparel, tech_gadgets, general_commercial)",
    )
    parser.add_argument(
        "--archetype",
        default=None,
        choices=[a.value for a in ProductArchetype],
        help="Directorial archetype (alias for topic)",
    )
    parser.add_argument(
        "--video-mode",
        default="api",
        choices=["ffmpeg", "api", "auto"],
        help="Video generator mode",
    )
    parser.add_argument(
        "--from-stage",
        type=int,
        default=None,
        choices=range(1, 9),
        help="Resume from stage (1-8); defaults to the stage after the latest --inject, else 1",
    )
    parser.add_argument(
        "--inject",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Supply your own canonical artifact (brief|script|scene_plan|asset_manifest) from PATH; repeatable",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the plan (stages to run, prerequisites) and exit without running or writing anything",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a single machine-readable JSON result on stdout (pipeline output goes to stderr)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Run version (e.g. v1, v2; defaults to active version or v1)",
    )
    parser.add_argument(
        "--new-version",
        action="store_true",
        help="Branch a new incremental run version (e.g. v2) inheriting assets via hardlinks",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory root",
    )
    return parser


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _run_outcome(workspace: ProjectWorkspace) -> dict[str, Any]:
    """Failure details for a finished run, read from its Run State Snapshot and render report."""
    state = _read_json(workspace.telemetry_dir / "state.json")
    failed_stage = (state.get("run_meta") or {}).get("failed_stage")
    error = None
    for entry in state.get("stages") or []:
        if failed_stage is not None and entry.get("stage") == failed_stage:
            error = entry.get("error")

    failed_gates: list[dict[str, Any]] = []
    if failed_stage == VERIFICATION_STAGE:
        report = _read_json(workspace.artifacts_dir / "render_report.json")
        failed_gates = [
            {"gate": gate.get("gate_name"), "error": gate.get("error_message")}
            for gate in report.get("verification_gates") or []
            if not gate.get("passed")
        ]
    return {"failed_stage": failed_stage, "error": error, "failed_gates": failed_gates}


def _result(workspace: ProjectWorkspace, from_stage: int, ok: bool, exit_code: int, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok,
        "exit_code": exit_code,
        "project_id": workspace.project_id,
        "topic": workspace.topic,
        "version": workspace.version,
        "from_stage": from_stage,
        "workspace_root": str(workspace.root),
        "artifacts_dir": str(workspace.artifacts_dir),
    }
    result.update(extra)
    return result


def _emit(result: dict[str, Any], as_json: bool) -> int:
    code = int(result["exit_code"])
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    elif code != EXIT_OK and result.get("error"):
        print(f"[ERROR] {result['error']}", file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.check and (args.inject or args.new_version):
        parser.error("--check is read-only and cannot be combined with --inject or --new-version")

    project_id = args.project_id or args.campaign
    topic = args.topic or args.archetype
    base_dir = Path(args.out_dir) if args.out_dir else None
    workspace = ProjectWorkspace.from_campaign_id(
        campaign_id=project_id,
        topic=topic,
        version=args.version,
        base_dir=base_dir,
    )
    if args.new_version:
        workspace = workspace.create_next_version()

    injected: list[str] = []
    for spec in args.inject:
        name, sep, source = spec.partition("=")
        if not sep or not name.strip() or not source.strip():
            result = _result(
                workspace,
                args.from_stage or 1,
                False,
                EXIT_INVALID_INPUT,
                error=f"--inject expects NAME=PATH, got '{spec}'",
            )
            return _emit(result, args.json)
        try:
            workspace.inject_artifact(name.strip(), source.strip())
        except (ValueError, FileNotFoundError) as exc:
            return _emit(_result(workspace, args.from_stage or 1, False, EXIT_INVALID_INPUT, error=str(exc)), args.json)
        injected.append(name.strip())

    from_stage = args.from_stage or first_stage_after(injected)
    problems = workspace.check_prerequisites(from_stage)
    stages_to_run = list(range(from_stage, LAST_STAGE + 1))

    if args.check:
        ok = not problems
        result = _result(
            workspace,
            from_stage,
            ok,
            EXIT_OK if ok else EXIT_INVALID_INPUT,
            check=True,
            stages_to_run=stages_to_run,
            problems=problems,
            error=None if ok else "; ".join(problems),
        )
        return _emit(result, args.json)

    if problems:
        result = _result(
            workspace,
            from_stage,
            False,
            EXIT_INVALID_INPUT,
            problems=problems,
            error=f"Cannot start at stage {from_stage}: " + "; ".join(problems),
        )
        return _emit(result, args.json)

    workspace.ensure_dirs()
    chatter = sys.stderr if args.json else sys.stdout
    if not args.json:
        # Print clean project path output: projects/{topic}/{project_id}/
        print(f"projects/{workspace.topic}/{workspace.project_id}/runs/{workspace.version}/")
        print(f"projects/{workspace.topic}/{workspace.project_id}/")
    with contextlib.redirect_stdout(chatter):
        ok = run_pipeline(
            campaign_id=project_id,
            project_id=project_id,
            product_name=args.product,
            product_url_or_query=args.url,
            archetype=topic,
            topic=topic,
            video_mode=args.video_mode,
            resume_from_stage=from_stage,
            output_dir=base_dir,
            workspace=workspace,
        )

    if ok:
        master: Optional[Path] = workspace.master_video_path if workspace.master_video_path.exists() else None
        result = _result(
            workspace,
            from_stage,
            True,
            EXIT_OK,
            master_video_path=str(master) if master else None,
            thumbnail_path=str(workspace.thumbnail_path) if workspace.thumbnail_path.exists() else None,
        )
        return _emit(result, args.json)

    outcome = _run_outcome(workspace)
    code = EXIT_VERIFICATION_FAILED if outcome["failed_stage"] == VERIFICATION_STAGE else EXIT_PIPELINE_FAILED
    error = outcome["error"] or "Pipeline failed; see telemetry/state.json"
    return _emit(_result(workspace, from_stage, False, code, **{**outcome, "error": error}), args.json)


if __name__ == "__main__":
    sys.exit(main())
