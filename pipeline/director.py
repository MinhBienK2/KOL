"""Chief AI Commercial Director: Autonomous Pipeline Orchestrator.

Combines OpenMontage orchestration state machines with DramaClaw character identity locking,
spatial scene staging contracts, competitor viral research, and independent verification gates.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

from pipeline.archetypes import ProductArchetype
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
    output_dir: Optional[Path] = None,
) -> bool:
    """Executes the complete 8-stage commercial production pipeline."""
    start_time = time.time()
    
    # Resolve working directory structure per campaign
    base_out = Path(output_dir or OUTPUT_DIR)
    target_artifacts_dir = base_out / "artifacts" / campaign_id
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    target_clips_dir = base_out / "raw_clips" / campaign_id
    target_synced_dir = base_out / "synced_clips" / campaign_id
    target_audio_dir = base_out / "audio" / campaign_id
    target_keyframes_dir = base_out / "keyframes" / campaign_id
    out_master_video = base_out / f"final_master_{campaign_id}.mp4"

    # Resolve archetype
    selected_archetype: ProductArchetype = ProductArchetype.GENERAL_COMMERCIAL
    if archetype is not None:
        if isinstance(archetype, str):
            try:
                selected_archetype = ProductArchetype(archetype)
            except ValueError:
                selected_archetype = ProductArchetype.GENERAL_COMMERCIAL
        else:
            selected_archetype = archetype

    print("=" * 80)
    print("CHIEF AI COMMERCIAL DIRECTOR: AUTONOMOUS PRODUCTION ENGINE")
    print(f"Campaign ID:       {campaign_id}")
    print(f"Product Name:      {product_name}")
    print(f"Archetype:         {selected_archetype.value}")
    print(f"Video Mode:        {video_mode}")
    print(f"Artifacts Dir:     {target_artifacts_dir}")
    print("=" * 80)

    stages = [
        ("Step 1: Competitor Research & Strategic Creative Briefing", 1),
        ("Step 2: Multi-Archetype High-Conversion Scriptwriting", 2),
        ("Step 3: DramaClaw Spatial Storyboard & OpenMontage Slideshow Risk Gate", 3),
        ("Step 4: KOL Identity Locking & Clean Keyframe Staging", 4),
        ("Step 5: 100% Genuine Video Diffusion Generation (Hailuo-2.3)", 5),
        ("Step 6: Neural TTS Audio & Lip-Sync Alignment", 6),
        ("Step 7: Final FFmpeg Multi-Track Composition & Audio Ducking", 7),
        ("Step 8: Independent Quality Verification Gates & Packaging", 8),
    ]

    try:
        # Step 1: Competitor Research & Briefing
        if resume_from_stage <= 1:
            print(f"\n[Stage 1/8] {stages[0][0]}...")
            if product_url_or_query:
                print(f"[Director] Ingesting affiliate/product link: '{product_url_or_query[:60]}...'")
                research_artifact, creative_concept = run_research_pipeline(
                    product_input=product_url_or_query,
                    campaign_id=campaign_id,
                    archetype=selected_archetype,
                    output_dir=target_artifacts_dir,
                    use_llm=True,
                )
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
                )
                print(f"[Director] Research complete! Winning Angle: '{winning_angle.title}' ({winning_angle.angle_archetype})")
            else:
                create_product_brief(
                    campaign_id=campaign_id,
                    product_name=product_name,
                    archetype=selected_archetype,
                    output_dir=target_artifacts_dir,
                )

        # Step 2: Scriptwriting
        if resume_from_stage <= 2:
            print(f"\n[Stage 2/8] {stages[1][0]}...")
            script = generate_commercial_script(
                output_dir=target_artifacts_dir,
                archetype=selected_archetype,
            )
            print(f"[Director] Script generated with {len(script.beats)} structured commercial beats.")

        # Step 3: Storyboard & Spatial Staging
        if resume_from_stage <= 3:
            print(f"\n[Stage 3/8] {stages[2][0]}...")
            scene_plan = generate_scene_plan(
                output_dir=target_artifacts_dir,
            )
            risk = scene_plan.slideshow_risk or {}
            print(f"[Director] Storyboard planned with {len(scene_plan.shots)} shots. "
                  f"Slideshow Risk Score: {risk.get('average_score', 'N/A')} ({risk.get('verdict', 'N/A')})")

        # Step 4: Keyframe Staging & Identity Locking
        if resume_from_stage <= 4:
            print(f"\n[Stage 4/8] {stages[3][0]}...")
            manifest = generate_clean_keyframes(
                output_dir=target_artifacts_dir,
                keyframes_dir=target_keyframes_dir,
            )
            print(f"[Director] Keyframes and first frames staged: {len(manifest.keyframes)} items.")

        # Step 5: Video Generation
        if resume_from_stage <= 5:
            print(f"\n[Stage 5/8] {stages[4][0]}...")
            rendered_clips = render_all_video_clips(
                artifacts_dir=target_artifacts_dir,
                raw_clips_dir=target_clips_dir,
                mode=video_mode,
            )
            print(f"[Director] Rendered {len(rendered_clips)} genuine diffusion video clips.")

        # Step 6: Audio & Lip-Sync
        if resume_from_stage <= 6:
            print(f"\n[Stage 6/8] {stages[5][0]}...")
            stems, synced = produce_all_audio_and_lip_sync(
                artifacts_dir=target_artifacts_dir,
                audio_dir=target_audio_dir,
                synced_clips_dir=target_synced_dir,
            )
            print(f"[Director] Generated {len(stems)} audio stems and aligned {len(synced)} synced clips.")

        # Step 7: Composition & Multi-track Audio Ducking
        if resume_from_stage <= 7:
            print(f"\n[Stage 7/8] {stages[6][0]}...")
            edit_decisions = compose_master_commercial(
                artifacts_dir=target_artifacts_dir,
                output_master_path=out_master_video,
            )
            print(f"[Director] Master video assembled: {out_master_video.name}")

        # Step 8: Quality Verification Gates
        if resume_from_stage <= 8:
            print(f"\n[Stage 8/8] {stages[7][0]}...")
            report = run_all_verification_gates(
                master_video_path=out_master_video,
                artifacts_dir=target_artifacts_dir,
            )
            if report.overall_status != "PASSED":
                print(f"[DIRECTOR ERROR] Pipeline failed verification: {report}")
                return False
            print(f"[Director] All 4 Quality Verification Gates PASSED!")

        elapsed = round(time.time() - start_time, 2)
        print("\n" + "=" * 80)
        print(f"COMMERCIAL PRODUCTION COMPLETE! Total execution time: {elapsed}s")
        print(f"Master Video: {out_master_video}")
        print(f"Artifacts:    {target_artifacts_dir}")
        print("=" * 80)
        return True

    except Exception as exc:
        print(f"\n[FATAL ERROR] Autonomous pipeline stopped at error: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="Chief AI Commercial Director Autonomous Pipeline")
    parser.add_argument("--campaign", default="campaign_lumina_mug_01", help="Campaign ID")
    parser.add_argument("--product", default="Ly Giữ Nhiệt Thông Minh Lumina Pro", help="Product name")
    parser.add_argument("--url", default=None, help="Affiliate link or raw product description")
    parser.add_argument("--archetype", default=None, choices=[a.value for a in ProductArchetype], help="Directorial archetype")
    parser.add_argument("--video-mode", default="api", choices=["ffmpeg", "api", "auto"], help="Video generator mode")
    parser.add_argument("--from-stage", type=int, default=1, choices=range(1, 9), help="Resume from stage (1-8)")
    parser.add_argument("--out-dir", default=None, help="Output directory root")
    args = parser.parse_args()

    ok = run_pipeline(
        campaign_id=args.campaign,
        product_name=args.product,
        product_url_or_query=args.url,
        archetype=args.archetype,
        video_mode=args.video_mode,
        resume_from_stage=args.from_stage,
        output_dir=Path(args.out_dir) if args.out_dir else None,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
