"""Batch Rebuild Script for Previous Unsatisfactory Campaigns.

Re-runs the overhauled pipeline stages (Scriptwriting, Storyboard, Keyframe Staging,
Audio Alignment at natural 1.0x speed, and Composition with smooth BGM ducking)
to produce brand-new, broadcast-quality final master commercial videos.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline.archetypes import ProductArchetype
from pipeline.audio_lip_sync import produce_all_audio_and_lip_sync
from pipeline.briefing import create_product_brief
from pipeline.composer import compose_master_commercial
from pipeline.config import ARTIFACTS_DIR, BASE_DIR, OUTPUT_DIR
from pipeline.identity_keyframe import generate_clean_keyframes
from pipeline.schemas import BriefArtifact
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan


CAMPAIGNS = [
    {
        "campaign_id": "campaign_cherry_dress_01",
        "archetype": ProductArchetype.FASHION_APPAREL,
        "product_name": "Đầm Xòe Nơ Quả Cherry Vintage Kiểu Pháp",
        "category": "fashion_apparel",
    },
    {
        "campaign_id": "campaign_blazer_minhanh_master",
        "archetype": ProductArchetype.FASHION_APPAREL,
        "product_name": "Áo Khoác Blazer Nữ Form Rộng Phong Cách Hàn Quốc Vải Tuyết Mưa",
        "category": "fashion_apparel",
    },
    {
        "campaign_id": "campaign_fashion_couture_v2",
        "archetype": ProductArchetype.FASHION_APPAREL,
        "product_name": "Đầm Dạ Hội Lụa Satin Pháp Xẻ Tà Cao Cấp",
        "category": "fashion_apparel",
    },
    {
        "campaign_id": "campaign_tech_cyberkey_02",
        "archetype": ProductArchetype.TECH_GADGETS,
        "product_name": "Bàn Phím Cơ Không Dây CyberKey Pro Khung Nhôm CNC",
        "category": "tech_gadgets",
    },
    {
        "campaign_id": "campaign_beauty_glow_03",
        "archetype": ProductArchetype.BEAUTY_SKINCARE,
        "product_name": "Serum Tinh Chất Phục Hồi Da Căng Bóng GlowRevive",
        "category": "beauty_skincare",
    },
]


def rebuild_campaign(cfg: dict) -> Path:
    cid = cfg["campaign_id"]
    arch = cfg["archetype"]
    pname = cfg["product_name"]
    print(f"\n{'='*70}\n[Rebuild] Starting overhaul for campaign: {cid}\n{'='*70}")

    artifacts_dir = OUTPUT_DIR / "artifacts" / cid
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    keyframes_dir = OUTPUT_DIR / "keyframes" / cid
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = OUTPUT_DIR / "audio" / cid
    audio_dir.mkdir(parents=True, exist_ok=True)
    synced_dir = OUTPUT_DIR / "synced_clips" / cid
    synced_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = OUTPUT_DIR / "raw_clips" / cid

    out_master_path = OUTPUT_DIR / f"final_master_{cid}.mp4"

    # Step 1: Ensure brief exists with proper archetype and product name
    brief_file = artifacts_dir / "brief.json"
    if brief_file.exists():
        with open(brief_file, "r", encoding="utf-8") as f:
            b_data = json.load(f)
        b_data["archetype"] = arch.value
        b_data["category"] = cfg.get("category", arch.value)
        b_data["product_name"] = pname
        brief = BriefArtifact.model_validate(b_data)
        with open(brief_file, "w", encoding="utf-8") as f:
            json.dump(brief.model_dump(), f, ensure_ascii=False, indent=2)
    else:
        brief = create_product_brief(
            campaign_id=cid,
            product_name=pname,
            archetype=arch,
            output_dir=artifacts_dir,
        )

    # Step 2: Overhauled Scriptwriting (natural copy, punchy captions, creative concept integration)
    print(f"[Rebuild] [{cid}] Generating overhauled script...")
    script = generate_commercial_script(
        brief=brief,
        output_dir=artifacts_dir,
        archetype=arch,
    )
    print(f"  Script generated with {len(script.beats)} beats:")
    for b in script.beats:
        print(f"    - [{b.beat_type}] Spoken: {b.spoken_text}")
        print(f"      Caption: {b.on_screen_text}")

    # Step 3: Storyboard & Scene Planning
    print(f"[Rebuild] [{cid}] Generating cinematic scene plan...")
    plan = generate_scene_plan(
        script=script,
        output_dir=artifacts_dir,
    )

    # Step 4: Keyframe Staging with Product Isolation & Archetype Binding
    print(f"[Rebuild] [{cid}] Generating identity-locked clean keyframes...")
    manifest = generate_clean_keyframes(
        scene_plan=plan,
        output_dir=artifacts_dir,
        keyframes_dir=keyframes_dir,
    )

    # Ensure raw video clips are mapped
    raw_clips: List[str] = []
    for shot in plan.shots:
        raw_p = raw_dir / f"{shot.shot_id}.mp4"
        if raw_p.exists():
            raw_clips.append(str(raw_p.resolve()))
        else:
            # Fallback to shared raw clip
            alt = OUTPUT_DIR / "raw_clips" / f"{shot.shot_id}.mp4"
            if alt.exists():
                raw_clips.append(str(alt.resolve()))
            else:
                raw_clips.append(str(raw_p))

    manifest.raw_video_clips = raw_clips

    # Step 6: Audio Production & Natural 1.0x Speed Lip-Sync Alignment
    print(f"[Rebuild] [{cid}] Aligning video-audio timing at natural 1.0x speed...")
    stems, synced = produce_all_audio_and_lip_sync(
        script=script,
        manifest=manifest,
        artifacts_dir=artifacts_dir,
        audio_dir=audio_dir,
        synced_clips_dir=synced_dir,
    )
    manifest.audio_stems = stems
    manifest.synced_video_clips = synced

    # Save updated manifest
    with open(artifacts_dir / "asset_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)

    # Step 7: Composition with gentle BGM ducking and safe-zone captions
    print(f"[Rebuild] [{cid}] Composing master commercial MP4...")
    compose_master_commercial(
        script=script,
        manifest=manifest,
        output_master_path=out_master_path,
        artifacts_dir=artifacts_dir,
    )

    print(f"[Rebuild] [{cid}] COMPLETED! Master video rendered to: {out_master_path}")
    return out_master_path


def main() -> None:
    results = []
    for cfg in CAMPAIGNS:
        p = rebuild_campaign(cfg)
        results.append(p)
    print("\n" + "=" * 80)
    print(f"REBUILD FINISHED! Rendered {len(results)} updated master commercial videos:")
    for r in results:
        sz_mb = r.stat().st_size / 1024 / 1024 if r.exists() else 0
        print(f"  - {r.name} ({sz_mb:.2f} MB)")


if __name__ == "__main__":
    main()
