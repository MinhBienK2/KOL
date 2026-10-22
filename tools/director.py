#!/usr/bin/env python3
"""Convenience CLI wrapper for Chief AI Commercial Director.

Agent contract
--------------
* ``--json`` prints exactly one JSON object on stdout (pipeline chatter goes to stderr).
* Exit codes: 0 success, 1 a stage failed, 2 invalid input / unmet prerequisites,
  3 the Stage 8 Verification Gates rejected the master (media exists, regenerate and re-verify),
  4 paused by ``--pause-after-stage N`` (human checkpoint; resume with ``--from-stage N+1``).
* Paid-call estimate: before stage 5/6 the plan (new video jobs, TTS calls, generated seconds, optional
  cost from ``KOL_UNIT_COSTS``) is printed and returned as ``estimate`` (also in ``--check`` and run_result.json).
  ``--max-video-jobs N`` aborts with exit 2 / status ``budget_exceeded`` before any submit if exceeded.
  A missing ``MINIMAX_API_KEY`` for a paid plan is exit 2 with ``error_code: missing_api_key`` (offline needs none).
* Every executed run also saves the same result object as ``run_result.json`` in the run workspace;
  its ``status`` is completed | failed | verification_failed | paused | invalid | budget_exceeded | checked.
* Agent direction flags (all optional): ``--beats``, ``--shot-overrides``, ``--references``,
  ``--character``, ``--strict-resolution``, ``--strict-tts``, ``--transitions``, ``--offline``.
* ``--inject NAME=PATH`` installs a validated canonical artifact (brief, script, scene_plan,
  asset_manifest) and resumes after the stage that would have produced it.
* ``--check`` validates a plan (stages to run, prerequisites) without executing or writing anything.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.archetypes import ProductArchetype, detect_product_archetype
from pipeline.cost import estimate_for_workspace
from pipeline.director import load_json_arg, resolve_character_path, run_pipeline
from pipeline.workspace import ProjectWorkspace, first_stage_after

EXIT_OK = 0
EXIT_PIPELINE_FAILED = 1
EXIT_INVALID_INPUT = 2
EXIT_VERIFICATION_FAILED = 3
EXIT_PAUSED = 4

RUN_RESULT_FILENAME = "run_result.json"

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
    direct = parser.add_argument_group("agent direction (all optional)")
    direct.add_argument("--beats", metavar="PATH.json", default=None,
                        help="Stage 2: directed script beats (JSON list); validated strictly")
    direct.add_argument("--shot-overrides", metavar="PATH.json", default=None,
                        help="Stage 3: per-shot overrides for the scene plan (JSON object keyed by shot id)")
    direct.add_argument("--references", metavar="PATH.json", default=None,
                        help="Stage 4: reference_overrides for keyframe generation (JSON object)")
    direct.add_argument("--character", metavar="PATH_OR_ID", default=None,
                        help="Stage 3/4: character.json path, character directory, or persona id under "
                             "assets/characters/ (e.g. kol_main)")
    direct.add_argument("--strict-resolution", action="store_true",
                        help="Stage 4: fail instead of accepting low-resolution character references")
    direct.add_argument("--keyframe-source", choices=("auto", "synth", "reference"), default="auto",
                        help="Stage 4: 'synth' renders each shot's first frame from its scene prompt with the "
                             "face anchor / product hero as references; 'reference' pads the reference itself "
                             "(not the planned scene); 'auto' = synth unless --video-mode ffmpeg or --offline")
    direct.add_argument("--strict-tts", action="store_true",
                        help="Stage 6: fail instead of falling back to a degraded TTS voice")
    direct.add_argument("--transitions", metavar="PATH.json", default=None,
                        help="Stage 7: one {type,duration} (or type name) per join; default: per-beat "
                             "'transition' fields in script.json")
    direct.add_argument("--pause-after-stage", type=int, default=None, choices=range(1, 8), metavar="N",
                        help="Human checkpoint: stop cleanly after stage N (1-7), status 'paused', exit code 4; "
                             "resume with --from-stage N+1")
    direct.add_argument("--offline", action="store_true",
                        help="No network: sets KOL_OFFLINE=1 and forces --video-mode ffmpeg")
    direct.add_argument("--max-video-jobs", type=int, default=None, metavar="N",
                        help="Budget cap: abort (exit 2, status 'budget_exceeded') BEFORE any paid submit if stage 5 "
                             "would need more than N new video jobs (cached shots are free). Default: no cap; the "
                             "estimate is always printed and recorded")
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


_STATUS_BY_EXIT = {
    EXIT_OK: "completed",
    EXIT_PIPELINE_FAILED: "failed",
    EXIT_INVALID_INPUT: "invalid",
    EXIT_VERIFICATION_FAILED: "verification_failed",
    EXIT_PAUSED: "paused",
}


def _result(workspace: ProjectWorkspace, from_stage: int, ok: bool, exit_code: int, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": ok,
        "status": _STATUS_BY_EXIT.get(exit_code, "failed"),
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


def _persist(result: dict[str, Any], workspace: ProjectWorkspace) -> None:
    """Save the run result next to the run's other outputs (same object as ``--json``)."""
    try:
        (workspace.root / RUN_RESULT_FILENAME).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.check and (args.inject or args.new_version):
        parser.error("--check is read-only and cannot be combined with --inject or --new-version")
    if args.max_video_jobs is not None and args.max_video_jobs < 0:
        parser.error("--max-video-jobs must be >= 0")
    if args.offline:
        os.environ["KOL_OFFLINE"] = "1"
        args.video_mode = "ffmpeg"

    project_id = args.project_id or args.campaign
    topic = args.topic or args.archetype
    base_dir = Path(args.out_dir) if args.out_dir else None
    workspace = ProjectWorkspace.from_campaign_id(
        campaign_id=project_id,
        topic=topic,
        version=args.version,
        base_dir=base_dir,
    )
    # Topic resolution: explicit --topic/--archetype wins; else an existing workspace keeps its topic;
    # else classify from product name + link/description BEFORE the workspace directory is chosen.
    if topic:
        archetype_source = "explicit"
    elif workspace.project_root.is_dir():
        archetype_source = "workspace"
    else:
        archetype_source = "auto"
        detected = detect_product_archetype(args.product, args.url)
        if detected.value != workspace.topic:
            workspace = ProjectWorkspace.from_campaign_id(
                campaign_id=project_id,
                topic=detected,
                version=args.version,
                base_dir=base_dir,
            )
    topic = workspace.topic

    def _res(ws: ProjectWorkspace, from_stage: int, ok: bool, exit_code: int, **extra: Any) -> dict[str, Any]:
        extra.setdefault("archetype", ws.topic)
        extra.setdefault("archetype_source", archetype_source)
        return _result(ws, from_stage, ok, exit_code, **extra)

    if args.new_version:
        workspace = workspace.create_next_version()

    try:
        beats = load_json_arg(args.beats, "--beats")
        shot_overrides = load_json_arg(args.shot_overrides, "--shot-overrides")
        reference_overrides = load_json_arg(args.references, "--references")
        transitions = load_json_arg(args.transitions, "--transitions")
        character_path = resolve_character_path(args.character)
    except (OSError, ValueError) as exc:
        return _emit(_res(workspace, args.from_stage or 1, False, EXIT_INVALID_INPUT, error=str(exc)), args.json)

    injected: list[str] = []
    for spec in args.inject:
        name, sep, source = spec.partition("=")
        if not sep or not name.strip() or not source.strip():
            result = _res(
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
            return _emit(_res(workspace, args.from_stage or 1, False, EXIT_INVALID_INPUT, error=str(exc)), args.json)
        injected.append(name.strip())

    from_stage = args.from_stage or first_stage_after(injected)
    if args.pause_after_stage is not None and args.pause_after_stage < from_stage:
        error = f"--pause-after-stage {args.pause_after_stage} is before the first stage to run ({from_stage})"
        return _emit(_res(workspace, from_stage, False, EXIT_INVALID_INPUT, error=error), args.json)
    problems = workspace.check_prerequisites(from_stage)
    stages_to_run = list(range(from_stage, LAST_STAGE + 1))

    if args.check:
        estimate = estimate_for_workspace(workspace, args.video_mode, stages_to_run)
        planned = estimate.get("video_jobs")
        if args.max_video_jobs is not None and planned is not None and 5 in stages_to_run and planned > args.max_video_jobs:
            problems = [*problems, f"plan needs {planned} new video job(s), over --max-video-jobs {args.max_video_jobs}"]
        ok = not problems
        result = _res(
            workspace,
            from_stage,
            ok,
            EXIT_OK if ok else EXIT_INVALID_INPUT,
            check=True,
            status="checked" if ok else "invalid",
            stages_to_run=stages_to_run,
            problems=problems,
            estimate=estimate,
            max_video_jobs=args.max_video_jobs,
            error=None if ok else "; ".join(problems),
        )
        return _emit(result, args.json)

    if problems:
        result = _res(
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
    run_status: dict[str, Any] = {}
    with contextlib.redirect_stdout(chatter):
        ok = run_pipeline(
            campaign_id=project_id,
            project_id=project_id,
            product_name=args.product,
            product_url_or_query=args.url,
            archetype=topic,
            topic=topic,
            archetype_source=archetype_source,
            video_mode=args.video_mode,
            resume_from_stage=from_stage,
            output_dir=base_dir,
            workspace=workspace,
            beats=beats,
            shot_overrides=shot_overrides,
            reference_overrides=reference_overrides,
            character_path=character_path,
            strict_resolution=args.strict_resolution,
            keyframe_source=args.keyframe_source,
            transitions=transitions,
            strict_tts=args.strict_tts,
            pause_after_stage=args.pause_after_stage,
            max_video_jobs=args.max_video_jobs,
            result=run_status,
        )

    def _finish(result: dict[str, Any]) -> int:
        if run_status.get("last_completed_stage") is not None:
            result["last_completed_stage"] = run_status["last_completed_stage"]
        if run_status.get("estimate") is not None:
            result["estimate"] = run_status["estimate"]
        _persist(result, workspace)
        return _emit(result, args.json)

    if run_status.get("status") in ("budget_exceeded", "config_error"):
        return _finish(_res(
            workspace,
            from_stage,
            False,
            EXIT_INVALID_INPUT,
            status=run_status["status"] if run_status["status"] == "budget_exceeded" else "invalid",
            error=run_status.get("error"),
            error_code=run_status.get("error_code"),
            max_video_jobs=run_status.get("max_video_jobs"),
            next_stage=run_status.get("next_stage"),
            resume_hint=run_status.get("resume_hint"),
        ))

    if run_status.get("status") == "paused":
        stage = run_status.get("paused_after_stage")
        return _finish(_res(
            workspace,
            from_stage,
            False,
            EXIT_PAUSED,
            paused_after_stage=stage,
            next_stage=run_status.get("next_stage"),
            resume_hint=run_status.get("resume_hint"),
        ))

    if ok:
        master: Optional[Path] = workspace.master_video_path if workspace.master_video_path.exists() else None
        result = _res(
            workspace,
            from_stage,
            True,
            EXIT_OK,
            master_video_path=str(master) if master else None,
            thumbnail_path=str(workspace.thumbnail_path) if workspace.thumbnail_path.exists() else None,
        )
        return _finish(result)

    outcome = _run_outcome(workspace)
    code = EXIT_VERIFICATION_FAILED if outcome["failed_stage"] == VERIFICATION_STAGE else EXIT_PIPELINE_FAILED
    error = outcome["error"] or "Pipeline failed; see telemetry/state.json"
    return _finish(_res(workspace, from_stage, False, code, **{**outcome, "error": error}))


if __name__ == "__main__":
    sys.exit(main())
