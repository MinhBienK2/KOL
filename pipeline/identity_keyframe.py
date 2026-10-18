"""Step 4: KOL Identity Locking & Clean Keyframe Generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
import cv2
import numpy as np
from PIL import Image

from pipeline.config import ARTIFACTS_DIR, BASE_DIR, CHARACTER_PATH, KEYFRAMES_DIR
from pipeline.archetypes import CharacterRole, ProductArchetype
from pipeline.wardrobe import resolve_wardrobe_and_environment
from pipeline.schemas import AssetManifestArtifact, KeyframeAsset, ScenePlanArtifact
from pipeline.workspace import ProjectWorkspace
from tools.dramaclaw_shot_builder import clean_watermark_inpaint


def prepare_9_16_frame(
    src_img_path: str | Path,
    out_img_path: str | Path,
    target_width: int = 1080,
    target_height: int = 1920,
) -> tuple[int, int]:
    """Pads or resizes image to exact 9:16 target dimensions (1080x1920) with blurred ambient background."""
    src_path = Path(src_img_path)
    if not src_path.is_absolute():
        src_path = BASE_DIR / src_path
    if not src_path.exists():
        raise FileNotFoundError(f"Source image not found: {src_path}")

    img = Image.open(src_path).convert("RGB")
    src_w, src_h = img.size

    # Target 9:16 aspect ratio
    target_ratio = target_width / target_height
    src_ratio = src_w / src_h

    # Create background by stretching and heavily blurring original
    bg = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    bg_cv = cv2.cvtColor(np.array(bg), cv2.COLOR_RGB2BGR)
    bg_cv = cv2.GaussianBlur(bg_cv, (99, 99), 30)

    # Scale original image to fit within target frame while maintaining aspect ratio
    if src_ratio > target_ratio:
        # Source is wider than 9:16 -> scale to target width
        new_w = target_width
        new_h = int(target_width / src_ratio)
    else:
        # Source is taller or equal -> scale to target height
        new_h = target_height
        new_w = int(target_height * src_ratio)

    img_scaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    img_cv = cv2.cvtColor(np.array(img_scaled), cv2.COLOR_RGB2BGR)

    # Center overlay onto blurred background
    x_offset = (target_width - new_w) // 2
    y_offset = (target_height - new_h) // 2
    bg_cv[y_offset : y_offset + new_h, x_offset : x_offset + new_w] = img_cv

    out_path = Path(out_img_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() in (".jpg", ".jpeg"):
        cv2.imwrite(str(out_path), bg_cv, [cv2.IMWRITE_JPEG_QUALITY, 92])
    else:
        cv2.imwrite(str(out_path), bg_cv)
    # Clean bottom-right watermark area with Telea Inpainting
    clean_watermark_inpaint(out_path, out_path)

    return target_width, target_height


def generate_clean_keyframes(
    scene_plan: ScenePlanArtifact | None = None,
    scene_plan_path: Path | None = None,
    output_dir: Path | None = None,
    keyframes_dir: Path | None = None,
    workspace: Optional[ProjectWorkspace] = None,
) -> AssetManifestArtifact:
    """Generates identity-locked, watermark-cleaned keyframes for all storyboard shots."""
    target_artifacts_dir = workspace.artifacts_dir if workspace is not None else (output_dir or ARTIFACTS_DIR)
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)
    target_keyframes_dir = workspace.keyframes_dir if workspace is not None else (keyframes_dir or KEYFRAMES_DIR)
    target_keyframes_dir.mkdir(parents=True, exist_ok=True)

    if scene_plan is None:
        source_plan = scene_plan_path or (target_artifacts_dir / "scene_plan.json")
        if not source_plan.exists():
            raise FileNotFoundError(f"Scene plan file not found at {source_plan}")
        with open(source_plan, "r", encoding="utf-8") as f:
            scene_plan = ScenePlanArtifact.model_validate(json.load(f))

    with open(CHARACTER_PATH, "r", encoding="utf-8") as f:
        char_data = json.load(f)

    default_portrait = BASE_DIR / char_data.get("portrait_image", "assets/characters/kol_main/portrait.png")
    # Resolve active wardrobe and staging profile from script.json
    script_file = target_artifacts_dir / "script.json"
    archetype_val = ProductArchetype.GENERAL_COMMERCIAL
    custom_costume = None
    custom_env = None
    if script_file.exists():
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                s_data = json.load(f)
                archetype_val = ProductArchetype(s_data.get("archetype", "general_commercial"))
                p_name = s_data.get("product_name", "").lower()
                if "cherry" in p_name or "đầm xòe" in p_name:
                    custom_costume = "costume_french_cherry_dress"
                    custom_env = "env_paris_cafe_terrace"
        except Exception:
            pass

    wardrobe, environment = resolve_wardrobe_and_environment(archetype_val, custom_costume, custom_env)

    keyframe_assets: List[KeyframeAsset] = []

    for shot in scene_plan.shots:
        is_prod_only = getattr(shot, "character_role", None) == CharacterRole.PRODUCT_ONLY or (
            hasattr(shot.character_role, "value") and shot.character_role.value == "product_only"
        )
        # Authoritative reference selection: 100% locked to canonical KOL Minh Anh
        char_base = BASE_DIR / "assets" / "characters" / "kol_main"
        archive_base = BASE_DIR / "archive_raw"

        # Map shot narrative beat to Minh Anh's canonical visual anchors:
        kol_beat_map = {
            "shot_01": archive_base / "ref_10_speaking_hand_gesture.jpg",
            "shot_02": char_base / "full_body" / "01_standing_front_0deg.jpg",
            "shot_03": archive_base / "ref_10_speaking_hand_gesture.jpg",
            "shot_04": char_base / "expressions" / "04_looking_down.jpg",
            "shot_05": archive_base / "ref_09_three_quarter_left_45deg.jpg",
            "shot_06": char_base / "expressions" / "02_smiling.jpg",
        }

        if getattr(wardrobe, "shot_references", None) and shot.shot_id in wardrobe.shot_references:
            custom_ref = BASE_DIR / wardrobe.shot_references[shot.shot_id]
            if custom_ref.exists():
                ref_path = custom_ref
            else:
                ref_path = kol_beat_map.get(shot.shot_id, default_portrait)
        elif shot.reference_expression:
            custom_ref = BASE_DIR / shot.reference_expression
            if custom_ref.exists():
                ref_path = custom_ref
            else:
                ref_path = kol_beat_map.get(shot.shot_id, default_portrait)
        else:
            ref_path = kol_beat_map.get(shot.shot_id, default_portrait)

        if not ref_path or not ref_path.exists():
            ref_path = default_portrait
        clean_keyframe_path = target_keyframes_dir / f"{shot.shot_id}_clean.jpg"

        # Format and fit into 9:16 target with Telea Inpainting
        w, h = prepare_9_16_frame(ref_path, clean_keyframe_path, target_width=1080, target_height=1920)

        keyframe_assets.append(
            KeyframeAsset(
                shot_id=shot.shot_id,
                image_path=str(ref_path),
                cleaned_image_path=str(clean_keyframe_path),
                watermark_removed=True,
                width=w,
                height=h,
            )
        )
    manifest = AssetManifestArtifact(
        campaign_id=scene_plan.campaign_id,
        keyframes=keyframe_assets,
    )

    out_file = target_artifacts_dir / "asset_manifest.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)

    return manifest
