"""Chief AI Commercial Director: Autonomous Pipeline Orchestrator."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from pipeline.briefing import create_product_brief
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from pipeline.identity_keyframe import generate_clean_keyframes
from pipeline.video_engine import render_all_video_clips
from pipeline.audio_lip_sync import produce_all_audio_and_lip_sync
from pipeline.composer import compose_master_commercial
from pipeline.verification import run_all_verification_gates
from pipeline.config import ARTIFACTS_DIR, OUTPUT_DIR


def run_pipeline(
    campaign_id: str = "campaign_lumina_mug_01",
    product_name: str = "Ly Giữ Nhiệt Thông Minh Lumina Pro",
    video_mode: str = "ffmpeg",  # "api" or "ffmpeg"
    resume_from_stage: int = 1,
) -> bool:
    """Executes the complete 8-stage commercial production pipeline."""
    start_time = time.time()
    print("=" * 80)
    print("CHIEF AI COMMERCIAL DIRECTOR: AUTONOMOUS PRODUCTION ENGINE")
    print(f"Campaign: {campaign_id} | Product: {product_name}")
    print("=" * 80)

    stages = [
        ("Step 1: Briefing & USP Analysis", 1),
        ("Step 2: High-Conversion Scriptwriting", 2),
        ("Step 3: Cinematic Storyboard & 6-Part Prompts", 3),
        ("Step 4: KOL Identity Locking & Clean Keyframes", 4),
        ("Step 5: Video Clip Generation", 5),
        ("Step 6: Neural TTS Audio & Lip-Sync Match", 6),
        ("Step 7: Final FFmpeg Composition & Audio Ducking", 7),
        ("Step 8: Quality Verification Gates & Packaging", 8),
    ]

    try:
        # Step 1
        if resume_from_stage <= 1:
            print(f"\n[Stage 1/8] {stages[0][0]}...")
            create_product_brief(campaign_id=campaign_id, product_name=product_name)

        # Step 2
        if resume_from_stage <= 2:
            print(f"\n[Stage 2/8] {stages[1][0]}...")
            generate_commercial_script()

        # Step 3
        if resume_from_stage <= 3:
            print(f"\n[Stage 3/8] {stages[2][0]}...")
            generate_scene_plan()

        # Step 4
        if resume_from_stage <= 4:
            print(f"\n[Stage 4/8] {stages[3][0]}...")
            generate_clean_keyframes()

        # Step 5
        if resume_from_stage <= 5:
            print(f"\n[Stage 5/8] {stages[4][0]}...")
            render_all_video_clips(mode=video_mode)

        # Step 6
        if resume_from_stage <= 6:
            print(f"\n[Stage 6/8] {stages[5][0]}...")
            produce_all_audio_and_lip_sync()

        # Step 7
        if resume_from_stage <= 7:
            print(f"\n[Stage 7/8] {stages[6][0]}...")
            compose_master_commercial()

        # Step 8
        if resume_from_stage <= 8:
            print(f"\n[Stage 8/8] {stages[7][0]}...")
            report = run_all_verification_gates()
            if report.overall_status != "PASSED":
                print(f"[DIRECTOR ERROR] Pipeline failed verification: {report}")
                return False

        elapsed = round(time.time() - start_time, 2)
        print("\n" + "=" * 80)
        print(f"COMMERCIAL PRODUCTION COMPLETE! Total execution time: {elapsed}s")
        print(f"Master Video: {OUTPUT_DIR / 'final_commercial_master.mp4'}")
        print(f"Thumbnail:    {OUTPUT_DIR / 'thumbnail_master.jpg'}")
        print(f"Artifacts:    {ARTIFACTS_DIR}")
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
    parser.add_argument("--video-mode", default="ffmpeg", choices=["ffmpeg", "api", "auto"], help="Video generator mode")
    parser.add_argument("--from-stage", type=int, default=1, choices=range(1, 9), help="Resume from stage (1-8)")
    args = parser.parse_args()

    ok = run_pipeline(
        campaign_id=args.campaign,
        product_name=args.product,
        video_mode=args.video_mode,
        resume_from_stage=args.from_stage,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
