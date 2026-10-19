"""Chief AI Commercial Director: Autonomous Pipeline Orchestrator.

Combines OpenMontage orchestration state machines with DramaClaw character identity locking,
spatial scene staging contracts, competitor viral research, and independent verification gates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional, Union

from pipeline import telemetry
from pipeline.archetypes import ProductArchetype
from pipeline.workspace import ProjectWorkspace
from pipeline.briefing import create_product_brief
from pipeline.researcher import run_research_pipeline
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from pipeline.identity_keyframe import generate_clean_keyframes
from pipeline.video_engine import render_all_video_clips
from pipeline.audio_lip_sync import produce_all_audio_and_lip_sync
from pipeline.composer import compose_master_commercial
from pipeline.verification import run_all_verification_gates
from pipeline.config import ARTIFACTS_DIR, OUTPUT_DIR, RAW_CLIPS_DIR, SYNCED_CLIPS_DIR, AUDIO_DIR, KEYFRAMES_DIR


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
    **kwargs: Any,
) -> bool:
    """Executes the complete 8-stage commercial production pipeline."""
    start_time = time.time()

    # Resolve project_id / campaign_id
    effective_project_id = project_id or (workspace.project_id if workspace is not None else campaign_id)

    # Resolve topic / archetype
    effective_topic = topic or archetype or (workspace.topic if workspace is not None else None)
    selected_archetype: ProductArchetype = ProductArchetype.GENERAL_COMMERCIAL
    if effective_topic is not None:
        if isinstance(effective_topic, ProductArchetype):
            selected_archetype = effective_topic
        elif isinstance(effective_topic, str):
            try:
                selected_archetype = ProductArchetype(effective_topic)
            except ValueError:
                selected_archetype = ProductArchetype.GENERAL_COMMERCIAL

    # Resolve workspace
    if workspace is None:
        workspace = ProjectWorkspace(
            topic=selected_archetype,
            project_id=effective_project_id,
            base_dir=output_dir,
        )
    workspace.ensure_dirs()

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
        "video_mode": video_mode,
        "resume_from_stage": resume_from_stage,
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
    failed_stage: Optional[int] = None

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
        print(f"Archetype:         {selected_archetype.value}")
        print(f"Video Mode:        {video_mode}")
        print(f"Project Workspace: {workspace.root}")
        print(f"Artifacts Dir:     {target_artifacts_dir}")
        print("=" * 80)

        # Resumed runs mark earlier stages as intentionally skipped (never "pending").
        for spec in stages:
            if resume_from_stage > spec.stage:
                telemetry.skip_stage(spec.stage, f"Skipped: resuming from stage {resume_from_stage}")

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
                        )
                        telemetry.register_artifact(target_artifacts_dir / "competitor_research.json", stage=1)
                        telemetry.register_artifact(target_artifacts_dir / "creative_concept.json", stage=1)
                        winning_sel = creative_concept.winning_concept
                        winning_angle = next(
                            (a for a in creative_concept.concept_options if a.angle_id == winning_sel.selected_angle_id),
                            creative_concept.concept_options[0],
                        )
                        actual_product_name = research_artifact.product_intel.title or product_name
                        create_product_brief(
                            campaign_id=campaign_id,
                            product_name=actual_product_name,
                            target_persona=research_artifact.primary_persona,
                            pain_points=research_artifact.product_intel.features[:3] or None,
                            usps=research_artifact.product_intel.dramatic_benefits[:3] or None,
                            visual_tone=f"{winning_angle.title} | {winning_sel.directorial_directives.lighting_mood}",
                            archetype=selected_archetype,
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

            # Step 2: Scriptwriting
            if resume_from_stage <= 2:
                print(f"\n[Stage 2/8] {stages[1].title}...")
                script = _run_stage(
                    2,
                    lambda: generate_commercial_script(
                        output_dir=target_artifacts_dir,
                        archetype=selected_archetype,
                        workspace=workspace,
                    ),
                )
                telemetry.register_artifact(target_artifacts_dir / "script.json", stage=2)
                print(f"[Director] Script generated with {_safe_len(script.beats)} structured commercial beats.")
                telemetry.complete_stage(2, message=f"Script ready: {_safe_len(script.beats)} beats")

            # Step 3: Storyboard & Spatial Staging
            if resume_from_stage <= 3:
                print(f"\n[Stage 3/8] {stages[2].title}...")
                scene_plan = _run_stage(
                    3,
                    lambda: generate_scene_plan(
                        output_dir=target_artifacts_dir,
                        workspace=workspace,
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

            # Step 4: Keyframe Staging & Identity Locking
            if resume_from_stage <= 4:
                print(f"\n[Stage 4/8] {stages[3].title}...")
                manifest = _run_stage(
                    4,
                    lambda: generate_clean_keyframes(
                        output_dir=target_artifacts_dir,
                        keyframes_dir=target_keyframes_dir,
                        workspace=workspace,
                    ),
                )
                telemetry.register_artifact(target_artifacts_dir / "asset_manifest.json", stage=4)
                print(f"[Director] Keyframes and first frames staged: {_safe_len(manifest.keyframes)} items.")
                telemetry.complete_stage(4, message=f"{_safe_len(manifest.keyframes)} identity-locked keyframes staged")

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

            # Step 6: Audio & Lip-Sync
            if resume_from_stage <= 6:
                print(f"\n[Stage 6/8] {stages[5].title}...")
                stems, synced = _run_stage(
                    6,
                    lambda: produce_all_audio_and_lip_sync(
                        artifacts_dir=target_artifacts_dir,
                        audio_dir=target_audio_dir,
                        synced_clips_dir=target_synced_dir,
                        workspace=workspace,
                    ),
                )
                # Voice stems and synced clips are registered by pipeline.audio_lip_sync itself.
                print(f"[Director] Generated {_safe_len(stems)} audio stems and aligned {_safe_len(synced)} synced clips.")
                telemetry.complete_stage(6, message=f"{_safe_len(stems)} voice stems, {_safe_len(synced)} lip-synced clips")

            # Step 7: Composition & Multi-track Audio Ducking
            if resume_from_stage <= 7:
                print(f"\n[Stage 7/8] {stages[6].title}...")
                edit_decisions = _run_stage(
                    7,
                    lambda: compose_master_commercial(
                        artifacts_dir=target_artifacts_dir,
                        output_master_path=out_master_video,
                        workspace=workspace,
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
                    total=4,
                )
                # render_report.json, publish_log.json and the thumbnail are registered by
                # pipeline.verification itself.
                if report.overall_status != "PASSED":
                    print(f"[DIRECTOR ERROR] Pipeline failed verification: {report}")
                    elapsed = round(time.time() - start_time, 2)
                    recorder.finish_run(
                        False,
                        summary=f"Verification gates failed (overall: {report.overall_status})",
                        elapsed_seconds=elapsed,
                    )
                    return False
                print(f"[Director] All 4 Quality Verification Gates PASSED!")

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
            return False


def main():
    parser = argparse.ArgumentParser(description="Chief AI Commercial Director Autonomous Pipeline")
    parser.add_argument("--campaign", default="campaign_lumina_mug_01", help="Campaign ID")
    parser.add_argument("--project-id", default=None, help="Project ID (alias for campaign ID)")
    parser.add_argument("--product", default="Ly Giữ Nhiệt Thông Minh Lumina Pro", help="Product name")
    parser.add_argument("--url", default=None, help="Affiliate link or raw product description")
    parser.add_argument("--topic", default=None, help="Domain topic or product archetype")
    parser.add_argument("--archetype", default=None, choices=[a.value for a in ProductArchetype], help="Directorial archetype")
    parser.add_argument("--video-mode", default="api", choices=["ffmpeg", "api", "auto"], help="Video generator mode")
    parser.add_argument("--from-stage", type=int, default=1, choices=range(1, 9), help="Resume from stage (1-8)")
    parser.add_argument("--out-dir", default=None, help="Output directory root")
    args = parser.parse_args()

    project_id = args.project_id or args.campaign
    topic = args.topic or args.archetype

    ok = run_pipeline(
        campaign_id=project_id,
        project_id=project_id,
        product_name=args.product,
        product_url_or_query=args.url,
        archetype=topic,
        topic=topic,
        video_mode=args.video_mode,
        resume_from_stage=args.from_stage,
        output_dir=Path(args.out_dir) if args.out_dir else None,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
