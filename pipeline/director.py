"""Chief AI Commercial Director: Autonomous Pipeline Orchestrator.

Combines OpenMontage orchestration state machines with DramaClaw character identity locking,
spatial scene staging contracts, competitor viral research, and independent verification gates.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional, Union

from pipeline import telemetry
from pipeline.archetypes import ProductArchetype, detect_product_archetype
from pipeline.workspace import ProjectWorkspace
from pipeline.briefing import create_product_brief, create_product_brief_from_concept
from pipeline.researcher import run_research_pipeline
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from pipeline.identity_keyframe import generate_clean_keyframes
from pipeline.video_engine import render_all_video_clips
from pipeline.audio_lip_sync import produce_all_audio_and_lip_sync
from pipeline.composer import compose_master_commercial
from pipeline.verification import VERIFICATION_GATE_COUNT, run_all_verification_gates
from pipeline.cost import estimate_for_workspace, format_estimate, unavailable_estimate
from pipeline.config import MINIMAX_API_KEY, ARTIFACTS_DIR, OUTPUT_DIR, RAW_CLIPS_DIR, SYNCED_CLIPS_DIR, AUDIO_DIR, KEYFRAMES_DIR, BASE_DIR

LAST_PAUSABLE_STAGE = 7
LAST_STAGE = 8


class StageCapabilityError(RuntimeError):
    """A stage function cannot honour an explicit director instruction."""


def load_json_arg(value: Any, label: str) -> Any:
    """Return ``value`` as loaded JSON: pass-through objects, read ``str``/``Path`` files."""
    if value is None or isinstance(value, (list, dict)):
        return value
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(f"{label}: JSON file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_character_path(value: Any) -> Optional[Path]:
    """Resolve a character file, a character directory, or a persona id under assets/characters/."""
    if value is None:
        return None
    path = Path(value)
    candidates = [path, path / "character.json"]
    if not path.is_absolute() and len(path.parts) == 1:
        candidates.append(BASE_DIR / "assets" / "characters" / path.name / "character.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Character not found (file, directory or persona id): {value}")


def _synthesize_keyframes(keyframe_source: str, video_mode: str) -> bool:
    """Stage 4 renders scene first frames from references.

    ``auto`` synthesizes whenever real video is produced (not ``ffmpeg`` test mode, not offline):
    an i2v clip that starts from a padded studio portrait cannot show the planned scene.
    """
    if keyframe_source not in ("auto", "synth"):
        raise ValueError(f"keyframe_source must be auto|synth, got {keyframe_source!r}")
    if keyframe_source == "auto":
        from pipeline.offline import is_offline

        return video_mode != "ffmpeg" and not is_offline()
    return keyframe_source == "synth"


def _call_stage(fn: Any, base: dict[str, Any], optional: Optional[dict[str, Any]] = None) -> Any:
    """Call a stage function, adding only the director instructions that were actually given.

    ``None``/``False`` optional values are omitted so default behaviour is untouched.  An explicit
    instruction the callee cannot accept fails loudly instead of being silently ignored.
    """
    kwargs = dict(base)
    supplied = {k: v for k, v in (optional or {}).items() if v is not None and v is not False}
    if supplied:
        try:
            params = inspect.signature(fn).parameters
            accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        except (TypeError, ValueError):
            params, accepts_any = {}, True
        for key in supplied:
            if not accepts_any and key not in params:
                raise StageCapabilityError(
                    f"{getattr(fn, '__name__', fn)!s} does not accept '{key}'; "
                    f"cannot honour this director instruction"
                )
        kwargs.update(supplied)
    return fn(**kwargs)


def normalize_transition_specs(raw: Any) -> Optional[list[dict]]:
    """Coerce a transitions list into the composer's ``[{"type", "duration"?}, ...]`` (one per join).

    Strings become ``{"type": name}``; dicts pass through; ``None``/empty entries become ``{}``
    (a hard cut in the composer).  Returns None when there is nothing to direct.
    """
    if raw is None:
        return None
    specs: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            specs.append({"type": item})
        elif isinstance(item, dict):
            specs.append(dict(item))
        else:
            specs.append({})
    return specs if any(specs) else None


def _beat_transitions(artifacts_dir: Path) -> Optional[list[dict]]:
    """Joins directed by per-beat ``transition`` fields in script.json (None if none set).

    A beat's ``transition`` (str or ``{"type", "duration"}``) is the join *after* that beat, so the
    last beat's value is ignored.  Read defensively: ScriptBeat may not define the field.
    """
    script_file = artifacts_dir / "script.json"
    if not script_file.is_file():
        return None
    try:
        with open(script_file, "r", encoding="utf-8") as f:
            beats = (json.load(f) or {}).get("beats") or []
    except (OSError, ValueError, AttributeError):
        return None
    values = [b.get("transition") if isinstance(b, dict) else getattr(b, "transition", None) for b in beats]
    return normalize_transition_specs(values[:-1])


def run_pipeline(
    campaign_id: str = "campaign_lumina_mug_01",
    product_name: str = "Ly Giữ Nhiệt Thông Minh Lumina Pro",
    product_url_or_query: Optional[str] = None,
    archetype: Optional[ProductArchetype | str] = None,
    video_mode: str = "api",  # "api" (genuine video diffusion), "ffmpeg" (local test), or "auto"
    resume_from_stage: int = 1,
    output_dir: Optional[Path | str] = None,
    workspace: Optional[ProjectWorkspace] = None,
    topic: Optional[Union[str, ProductArchetype]] = None,
    project_id: Optional[str] = None,
    beats: Any = None,
    shot_overrides: Any = None,
    reference_overrides: Any = None,
    character_path: Any = None,
    strict_resolution: bool = False,
    keyframe_source: str = "auto",
    transitions: Any = None,
    strict_tts: bool = False,
    pause_after_stage: Optional[int] = None,
    result: Optional[dict] = None,
    archetype_source: Optional[str] = None,
    max_video_jobs: Optional[int] = None,
    **kwargs: Any,
) -> bool:
    """Executes the complete 8-stage commercial production pipeline.

    Agent direction (all optional; objects or JSON file paths where noted):
      ``beats`` -> stage 2 (strict), ``shot_overrides`` -> stage 3, ``reference_overrides`` /
      ``character_path`` / ``strict_resolution`` / ``keyframe_source`` -> stage 4, ``strict_tts`` -> stage 6,
      ``transitions`` -> stage 7 (default: per-beat ``transition`` in script.json).
    ``pause_after_stage`` stops cleanly after that stage (returns False, ``result["status"] ==
    "paused"``); resume with ``resume_from_stage=N+1``.  ``result`` (if given) is filled with the
    status dict (``status``, ``last_completed_stage``, ``paused_after_stage``, ``next_stage``, ``failed_stage``)
    that tools/director.py merges into its single machine-readable result (also saved as run_result.json).
    Before any paid call (stages 5-6) the plan of paid generation is estimated (see ``pipeline.cost``),
    printed, recorded in telemetry and ``result["estimate"]``; ``max_video_jobs`` aborts the run (status
    ``budget_exceeded``, before any submit) when the plan needs more new video jobs than that.
    """
    start_time = time.time()
    beats = load_json_arg(beats, "beats")
    if isinstance(beats, dict):
        beats = beats.get("beats", beats)
    shot_overrides = load_json_arg(shot_overrides, "shot_overrides")
    reference_overrides = load_json_arg(reference_overrides, "reference_overrides")
    transitions = load_json_arg(transitions, "transitions")
    if isinstance(transitions, dict):
        transitions = transitions.get("transitions", transitions)
    transitions = normalize_transition_specs(transitions)
    character_file = resolve_character_path(character_path)
    if pause_after_stage is not None and not 1 <= int(pause_after_stage) <= LAST_PAUSABLE_STAGE:
        raise ValueError(f"pause_after_stage must be 1-{LAST_PAUSABLE_STAGE}, got {pause_after_stage}")

    # Resolve project_id / campaign_id
    effective_project_id = project_id or (workspace.project_id if workspace is not None else campaign_id)

    # Resolve topic / archetype
    # Explicit topic/archetype always wins, then an existing workspace's topic; only when neither is
    # given is the archetype auto-detected from the product name + link/description (before the workspace
    # is created).  ``archetype_source`` lets a caller (tools/director.py) report how it already decided.
    effective_topic = topic or archetype
    resolved_source = "explicit"
    if effective_topic is None and workspace is not None:
        effective_topic, resolved_source = workspace.topic, "workspace"
    selected_archetype: ProductArchetype = ProductArchetype.GENERAL_COMMERCIAL
    if effective_topic is None:
        selected_archetype = detect_product_archetype(product_name, product_url_or_query)
        resolved_source = "auto"
    else:
        if isinstance(effective_topic, ProductArchetype):
            selected_archetype = effective_topic
        elif isinstance(effective_topic, str):
            try:
                selected_archetype = ProductArchetype(effective_topic)
            except ValueError:
                selected_archetype = ProductArchetype.GENERAL_COMMERCIAL

    archetype_source = archetype_source or resolved_source

    # Resolve workspace
    if workspace is None:
        workspace = ProjectWorkspace(
            topic=selected_archetype,
            project_id=effective_project_id,
            base_dir=output_dir,
        )
    workspace.ensure_dirs()

    # ADR 0001: a stage may only start when its prerequisite artifacts exist and validate.
    prerequisite_problems = workspace.check_prerequisites(resume_from_stage)
    if prerequisite_problems:
        print(
            f"[DIRECTOR ERROR] Cannot resume from stage {resume_from_stage}: " + "; ".join(prerequisite_problems),
            file=sys.stderr,
        )
        return False

    # Extract standard paths from workspace
    target_artifacts_dir = workspace.artifacts_dir
    target_clips_dir = workspace.raw_clips_dir
    target_synced_dir = workspace.synced_clips_dir
    target_audio_dir = workspace.audio_dir
    target_keyframes_dir = workspace.keyframes_dir
    out_master_video = workspace.master_video_path

    # Telemetry: one recorder per run, persisted under {workspace.root}/telemetry/.
    # Update project metadata with product title
    workspace.update_project_meta(title=product_name, archetype=selected_archetype.value)

    # Telemetry: one recorder per run, persisted under {workspace.root}/telemetry/.
    run_meta = {
        "campaign_id": campaign_id,
        "product_name": product_name,
        "product_url_or_query": product_url_or_query,
        "archetype": selected_archetype.value,
        "archetype_source": archetype_source,
        "video_mode": video_mode,
        "resume_from_stage": resume_from_stage,
        "failed_stage": None,  # clears a failure recorded by an earlier attempt of this run
        "project_id": workspace.project_id,
        "topic": workspace.topic,
        "version": workspace.version,
        "workspace_root": str(workspace.root),
        "artifacts_dir": str(target_artifacts_dir),
        "master_video_path": str(out_master_video),
        "thumbnail_path": str(workspace.thumbnail_path),
        "prompt_ledger_path": str(workspace.prompt_ledger_path),
    }
    recorder = telemetry.RunTelemetry(
        workspace.project_id,
        workspace.topic,
        telemetry_dir=workspace.root / telemetry.TELEMETRY_DIRNAME,
        base_dir=workspace.root,
        run_meta=run_meta,
    )

    # Stage identities come from the single source of truth in pipeline.telemetry.
    stages = telemetry.STAGE_CATALOG

    running_stage: int = 0
    last_stage_done: int = 0
    failed_stage: Optional[int] = None
    paid_estimate: Optional[dict] = None

    def _safe_len(value: Any) -> int:
        """Length of a stage output, tolerating objects that do not support ``len()``."""
        try:
            return len(value)
        except Exception:
            return 0

    def _stage_status(stage: int) -> Optional[str]:
        """Recorder status for ``stage`` (``None`` while telemetry is inactive)."""
        recorder_now = telemetry.current()
        if recorder_now is None:
            return None
        for entry in recorder_now.snapshot().get("stages") or []:
            if entry.get("stage") == stage:
                return entry.get("status")
        return None

    def _fail_stage_once(stage: int, error: str) -> None:
        """Fail ``stage`` unless the stage module already reported that failure itself."""
        if _stage_status(stage) != telemetry.STAGE_FAILED:
            telemetry.fail_stage(stage, error)

    def _run_stage(stage: int, work: Any, total: Optional[int] = None) -> Any:
        """Open ``stage``, run ``work`` and attribute any exception to that stage."""
        nonlocal running_stage, failed_stage
        running_stage = stage
        telemetry.start_stage(stage, message=stages[stage - 1].title, total=total)
        try:
            return work()
        except Exception as exc:
            failed_stage = stage
            _fail_stage_once(stage, str(exc))
            raise

    with telemetry.use_recorder(recorder), telemetry.capture_console():
        recorder.start_run(**run_meta)
        print("=" * 80)
        print("CHIEF AI COMMERCIAL DIRECTOR: AUTONOMOUS PRODUCTION ENGINE")
        print(f"Project ID:        {workspace.project_id}")
        print(f"Topic:             {workspace.topic}")
        print(f"Campaign ID:       {campaign_id}")
        print(f"Product Name:      {product_name}")
        print(f"Archetype:         {selected_archetype.value} ({archetype_source})")
        print(f"Video Mode:        {video_mode}")
        print(f"Project Workspace: {workspace.root}")
        print(f"Artifacts Dir:     {target_artifacts_dir}")
        print("=" * 80)

        if archetype_source == "auto":
            telemetry.note(
                f"Auto-detected archetype '{selected_archetype.value}' from product name/description",
                archetype=selected_archetype.value,
                archetype_source="auto",
            )

        # Resumed runs mark earlier stages as intentionally skipped (never "pending").
        for spec in stages:
            if resume_from_stage > spec.stage:
                telemetry.skip_stage(spec.stage, f"Skipped: resuming from stage {resume_from_stage}")

        def _emit_result(status: str, ok: bool, **extra: Any) -> dict:
            """Fill the caller's ``result`` out-param (tools/director.py builds the final JSON from it)."""
            payload = {
                "status": status,
                "ok": ok,
                "last_completed_stage": last_stage_done or None,
                "archetype": selected_archetype.value,
                "archetype_source": archetype_source,
                **extra,
            }
            if paid_estimate is not None:
                payload["estimate"] = paid_estimate
            if result is not None:
                result.clear()
                result.update(payload)
            return payload

        def _pause_check(stage: int) -> bool:
            """Record stage completion; True when the run must stop cleanly after ``stage``."""
            nonlocal last_stage_done
            last_stage_done = stage
            if pause_after_stage is None or int(pause_after_stage) != stage:
                return False
            next_stage = stage + 1
            elapsed = round(time.time() - start_time, 2)
            print(f"\n[Director] PAUSED after stage {stage} for human review. "
                  f"Resume with --from-stage {next_stage}.")
            workspace.update_project_meta(last_status="paused")
            with recorder._lock:
                recorder.state["status"] = "paused"
                recorder.state["finished_at"] = telemetry.now_iso()
                recorder.state["elapsed_seconds"] = elapsed
            telemetry.stage_message(stage, f"Paused after stage {stage}; resume from stage {next_stage}")
            recorder.flush()
            _emit_result(
                "paused",
                False,
                paused_after_stage=stage,
                next_stage=next_stage,
                resume_hint=f"--from-stage {next_stage}",
            )
            return True

        try:
            # Step 1: Competitor Research & Briefing
            if resume_from_stage <= 1:
                print(f"\n[Stage 1/8] {stages[0].title}...")

                def _stage_1() -> str:
                    if product_url_or_query:
                        print(f"[Director] Ingesting affiliate/product link: '{product_url_or_query[:60]}...'")
                        research_artifact, creative_concept = run_research_pipeline(
                            product_input=product_url_or_query,
                            campaign_id=campaign_id,
                            archetype=selected_archetype,
                            output_dir=target_artifacts_dir,
                            workspace=workspace,
                            use_llm=True,
                            auto_detect_archetype=False,  # decided once, up front, by the Director
                        )
                        telemetry.register_artifact(target_artifacts_dir / "competitor_research.json", stage=1)
                        telemetry.register_artifact(target_artifacts_dir / "creative_concept.json", stage=1)
                        winning_sel = creative_concept.winning_concept
                        winning_angle = next(
                            (a for a in creative_concept.concept_options if a.angle_id == winning_sel.selected_angle_id),
                            creative_concept.concept_options[0],
                        )
                        # Bridge the winning angle (character role, audio strategy, directives) into the brief.
                        create_product_brief_from_concept(
                            creative_concept,
                            research_artifact,
                            output_dir=target_artifacts_dir,
                            workspace=workspace,
                        )
                        print(f"[Director] Research complete! Winning Angle: '{winning_angle.title}' ({winning_angle.angle_archetype})")
                        return f"Research briefed: winning angle '{winning_angle.title}'"
                    create_product_brief(
                        campaign_id=campaign_id,
                        product_name=product_name,
                        archetype=selected_archetype,
                        output_dir=target_artifacts_dir,
                        workspace=workspace,
                    )
                    return f"Brief created for '{product_name}' (no product link supplied)"

                stage_1_summary = _run_stage(1, _stage_1)
                telemetry.register_artifact(target_artifacts_dir / "brief.json", stage=1)
                telemetry.complete_stage(1, message=str(stage_1_summary))

            if resume_from_stage <= 1 and _pause_check(1):
                return False

            # Step 2: Scriptwriting
            if resume_from_stage <= 2:
                print(f"\n[Stage 2/8] {stages[1].title}...")
                script = _run_stage(
                    2,
                    lambda: _call_stage(
                        generate_commercial_script,
                        dict(output_dir=target_artifacts_dir, archetype=selected_archetype, workspace=workspace),
                        # Directed beats are authoritative: validate them strictly.
                        {"beats": beats, "strict": True if beats else None},
                    ),
                )
                telemetry.register_artifact(target_artifacts_dir / "script.json", stage=2)
                print(f"[Director] Script generated with {_safe_len(script.beats)} structured commercial beats.")
                telemetry.complete_stage(2, message=f"Script ready: {_safe_len(script.beats)} beats")

            if resume_from_stage <= 2 and _pause_check(2):
                return False

            # Step 3: Storyboard & Spatial Staging
            if resume_from_stage <= 3:
                print(f"\n[Stage 3/8] {stages[2].title}...")
                scene_plan = _run_stage(
                    3,
                    lambda: _call_stage(
                        generate_scene_plan,
                        dict(output_dir=target_artifacts_dir, workspace=workspace),
                        {"shot_overrides": shot_overrides, "character_path": character_file},
                    ),
                )
                telemetry.register_artifact(target_artifacts_dir / "scene_plan.json", stage=3)
                risk = scene_plan.slideshow_risk or {}
                print(f"[Director] Storyboard planned with {_safe_len(scene_plan.shots)} shots. "
                      f"Slideshow Risk Score: {risk.get('average_score', 'N/A')} ({risk.get('verdict', 'N/A')})")
                telemetry.complete_stage(
                    3,
                    message=(
                        f"{_safe_len(scene_plan.shots)} shots planned | slideshow risk "
                        f"{risk.get('average_score', 'N/A')} ({risk.get('verdict', 'N/A')})"
                    ),
                )

            if resume_from_stage <= 3 and _pause_check(3):
                return False

            # Step 4: Keyframe Staging & Identity Locking
            if resume_from_stage <= 4:
                print(f"\n[Stage 4/8] {stages[3].title}...")
                manifest = _run_stage(
                    4,
                    lambda: _call_stage(
                        generate_clean_keyframes,
                        dict(output_dir=target_artifacts_dir, keyframes_dir=target_keyframes_dir, workspace=workspace),
                        {
                            "reference_overrides": reference_overrides,
                            "character_path": character_file,
                            "strict_resolution": strict_resolution,
                            "synthesize_frames": _synthesize_keyframes(keyframe_source, video_mode),
                        },
                    ),
                )
                telemetry.register_artifact(target_artifacts_dir / "asset_manifest.json", stage=4)
                print(f"[Director] Keyframes and first frames staged: {_safe_len(manifest.keyframes)} items.")
                telemetry.complete_stage(4, message=f"{_safe_len(manifest.keyframes)} identity-locked keyframes staged")

            if resume_from_stage <= 4 and _pause_check(4):
                return False

            # Paid-generation estimate + budget cap: computed before the first paid call (stage 5 / 6).
            if resume_from_stage <= 6:
                last_stage = int(pause_after_stage) if pause_after_stage is not None else LAST_STAGE
                paid_stages = [n for n in range(resume_from_stage, last_stage + 1)]
                try:
                    paid_estimate = estimate_for_workspace(workspace, video_mode, paid_stages)
                except Exception as exc:  # an unreadable artifact must not kill an uncapped run
                    paid_estimate = unavailable_estimate(f"estimate failed: {exc}")
                print(f"[Director] {format_estimate(paid_estimate)}")
                telemetry.note(format_estimate(paid_estimate), estimate=paid_estimate)
                with recorder._lock:
                    recorder.state["run_meta"]["paid_estimate"] = paid_estimate
                recorder.flush()
                if paid_estimate.get("paid_calls") and not MINIMAX_API_KEY:
                    error = (
                        f"Configuration error: {len(paid_stages)} paid stage(s) planned "
                        f"({paid_estimate['video_jobs']} video job(s), {paid_estimate['tts_calls']} TTS call(s)) but "
                        f"MINIMAX_API_KEY is not set. Export it or put it in .env (see .env.example), or run --offline."
                    )
                    print(f"[DIRECTOR ERROR] {error}", file=sys.stderr)
                    recorder.finish_run(False, summary=error, elapsed_seconds=round(time.time() - start_time, 2))
                    _emit_result("config_error", False, error=error, error_code="missing_api_key",
                                 next_stage=resume_from_stage, resume_hint=f"--from-stage {resume_from_stage}")
                    return False
                if max_video_jobs is not None and 5 in paid_stages:
                    planned = paid_estimate.get("video_jobs")
                    if planned is None or planned > max_video_jobs:
                        reason = (
                            f"cannot verify the video job count ({paid_estimate.get('reason')})"
                            if planned is None
                            else f"plan needs {planned} new video job(s), over --max-video-jobs {max_video_jobs}"
                        )
                        error = f"Budget cap: {reason}. No paid call was made; raise the cap and resume with --from-stage 5."
                        print(f"[DIRECTOR ERROR] {error}", file=sys.stderr)
                        workspace.update_project_meta(last_status="budget_exceeded")
                        recorder.finish_run(
                            False,
                            summary=error,
                            elapsed_seconds=round(time.time() - start_time, 2),
                            failed_stage=None,
                        )
                        _emit_result(
                            "budget_exceeded", False, error=error, error_code="max_video_jobs_exceeded",
                            max_video_jobs=max_video_jobs, next_stage=5, resume_hint="--from-stage 5",
                        )
                        return False

            # Step 5: Video Generation (pipeline.video_engine owns the stage-5 completion).
            if resume_from_stage <= 5:
                print(f"\n[Stage 5/8] {stages[4].title}...")
                rendered_clips = _run_stage(
                    5,
                    lambda: render_all_video_clips(
                        artifacts_dir=target_artifacts_dir,
                        raw_clips_dir=target_clips_dir,
                        mode=video_mode,
                        workspace=workspace,
                    ),
                )
                for clip in rendered_clips:
                    telemetry.register_artifact(clip, stage=5)
                print(f"[Director] Rendered {_safe_len(rendered_clips)} genuine diffusion video clips.")

            if resume_from_stage <= 5 and _pause_check(5):
                return False

            # Step 6: Audio & Lip-Sync
            if resume_from_stage <= 6:
                print(f"\n[Stage 6/8] {stages[5].title}...")
                stems, synced = _run_stage(
                    6,
                    lambda: _call_stage(
                        produce_all_audio_and_lip_sync,
                        dict(
                            artifacts_dir=target_artifacts_dir,
                            audio_dir=target_audio_dir,
                            synced_clips_dir=target_synced_dir,
                            workspace=workspace,
                        ),
                        {"strict_tts": strict_tts},
                    ),
                )
                # Voice stems and synced clips are registered by pipeline.audio_lip_sync itself.
                print(f"[Director] Generated {_safe_len(stems)} audio stems and aligned {_safe_len(synced)} synced clips.")
                telemetry.complete_stage(6, message=f"{_safe_len(stems)} voice stems, {_safe_len(synced)} lip-synced clips")

            if resume_from_stage <= 6 and _pause_check(6):
                return False

            # Step 7: Composition & Multi-track Audio Ducking
            if resume_from_stage <= 7:
                print(f"\n[Stage 7/8] {stages[6].title}...")
                edit_decisions = _run_stage(
                    7,
                    lambda: _call_stage(
                        compose_master_commercial,
                        dict(
                            artifacts_dir=target_artifacts_dir,
                            output_master_path=out_master_video,
                            workspace=workspace,
                        ),
                        {"transitions": transitions if transitions is not None else _beat_transitions(target_artifacts_dir)},
                    ),
                )
                # edit_decisions.json + master video are registered by pipeline.composer itself.
                print(f"[Director] Master video assembled: {out_master_video.name}")
                telemetry.complete_stage(
                    7,
                    message=(
                        f"Master assembled: {out_master_video.name} "
                        f"({_safe_len(getattr(edit_decisions, 'timeline_clips', None))} timeline clips)"
                    ),
                )

            if resume_from_stage <= 7 and _pause_check(7):
                return False

            # Step 8: Quality Verification Gates (pipeline.verification owns the completion).
            if resume_from_stage <= 8:
                print(f"\n[Stage 8/8] {stages[7].title}...")
                report = _run_stage(
                    8,
                    lambda: run_all_verification_gates(
                        master_video_path=out_master_video,
                        artifacts_dir=target_artifacts_dir,
                        workspace=workspace,
                    ),
                    total=VERIFICATION_GATE_COUNT,
                )
                # render_report.json, publish_log.json and the thumbnail are registered by
                # pipeline.verification itself.
                if report.overall_status != "PASSED":
                    print(f"[DIRECTOR ERROR] Pipeline failed verification: {report}")
                    elapsed = round(time.time() - start_time, 2)
                    workspace.update_project_meta(last_status="verification_failed")
                    recorder.finish_run(
                        False,
                        summary=f"Verification gates failed (overall: {report.overall_status})",
                        elapsed_seconds=elapsed,
                        failed_stage=8,
                    )
                    _emit_result("failed", False, failed_stage=8, error=f"Verification gates failed ({report.overall_status})")
                    return False
                print(f"[Director] All {VERIFICATION_GATE_COUNT} Quality Verification Gates PASSED!")

            elapsed = round(time.time() - start_time, 2)
            print("\n" + "=" * 80)
            print(f"COMMERCIAL PRODUCTION COMPLETE! Total execution time: {elapsed}s")
            print(f"Project Workspace: {workspace.root}")
            print(f"Master Video:      {out_master_video}")
            print(f"Artifacts:         {target_artifacts_dir}")
            print("=" * 80)
            # Persist prompt_ledger.json and create master.mp4/thumbnail.jpg aliases
            prompts = recorder.snapshot().get("prompts") or {}
            if prompts:
                workspace.write_prompt_ledger(prompts)
                telemetry.register_artifact(workspace.prompt_ledger_path, stage=5, kind="json", label="Prompt Ledger")
            if out_master_video.exists() and not workspace.master_video_short_path.exists():
                try:
                    os.link(out_master_video, workspace.master_video_short_path)
                except OSError:
                    pass
            if workspace.thumbnail_path.exists() and not workspace.thumbnail_short_path.exists():
                try:
                    os.link(workspace.thumbnail_path, workspace.thumbnail_short_path)
                except OSError:
                    pass
            workspace.update_project_meta(last_status="completed")

            recorder.finish_run(
                True,
                summary=f"Commercial master published in {elapsed}s: {out_master_video.name}",
                elapsed_seconds=elapsed,
            )
            _emit_result("completed", True, last_completed_stage=8)
            return True

        except Exception as exc:
            print(f"\n[FATAL ERROR] Autonomous pipeline stopped at error: {exc}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            if failed_stage is None and running_stage:
                _fail_stage_once(running_stage, str(exc))
            elapsed = round(time.time() - start_time, 2)
            recorder.finish_run(
                False,
                summary=f"Pipeline stopped at stage {running_stage or '?'}: {exc}",
                elapsed_seconds=elapsed,
                failed_stage=running_stage or None,
            )
            _emit_result("failed", False, failed_stage=running_stage or None, error=str(exc))
            return False


def main(argv: Optional[list[str]] = None) -> int:
    """Delegate to the single canonical CLI in ``tools/director.py`` (``python -m pipeline.director``)."""
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from tools.director import main as tools_main

    return tools_main(argv)


if __name__ == "__main__":
    sys.exit(main())
