"""Step 4: KOL Identity Locking & Clean Keyframe Generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
import cv2
import numpy as np
from PIL import Image

from pipeline import telemetry
from pipeline.config import ARTIFACTS_DIR, BASE_DIR, CHARACTER_PATH, KEYFRAMES_DIR
from pipeline.archetypes import CharacterRole, ProductArchetype
from pipeline.wardrobe import resolve_wardrobe_and_environment
from pipeline.schemas import AssetManifestArtifact, KeyframeAsset, ScenePlanArtifact
from pipeline.workspace import ProjectWorkspace
from tools.dramaclaw_shot_builder import clean_watermark_inpaint

STAGE_IDENTITY_KEYFRAMES = telemetry.stage_number("identity_keyframes")

ARCHETYPE_IDENTITY_MAP = {
    ProductArchetype.FASHION_APPAREL: "kol_main_fashion",
    ProductArchetype.TECH_GADGETS: "kol_main_techwear",
    ProductArchetype.BEAUTY_SKINCARE: "kol_main_spa",
    ProductArchetype.HOME_LIFESTYLE: "kol_main_cozy",
    ProductArchetype.GENERAL_COMMERCIAL: "kol_main_office",
}


def resolve_canonical_identity_reference(
    archetype: ProductArchetype,
    char_data: dict,
    default_portrait: Path,
) -> Path:
    """Binds character shots uniformly to the campaign's archetype identity sheet."""
    identities = {ident["identity_id"]: ident for ident in char_data.get("identities", [])}
    ident_id = ARCHETYPE_IDENTITY_MAP.get(archetype, "kol_main_office")
    ident = identities.get(ident_id)
    if ident and ident.get("reference_sheet"):
        sheet_path = BASE_DIR / ident["reference_sheet"]
        if sheet_path.exists():
            return sheet_path
    return default_portrait


def resolve_canonical_character_sheet(
    archetype: ProductArchetype,
    char_data: dict,
    default_sheet: Path | None = None,
) -> Path:
    """Resolves the canonical 6-panel character sheet for the active identity."""
    identities = {ident["identity_id"]: ident for ident in char_data.get("identities", [])}
    ident_id = ARCHETYPE_IDENTITY_MAP.get(archetype, "kol_main_office")
    ident = identities.get(ident_id, {})
    sheet_rel = ident.get("character_sheet") or ident.get("reference_sheet") or char_data.get("character_sheet")
    if sheet_rel:
        sheet_path = BASE_DIR / sheet_rel
        if sheet_path.exists():
            return sheet_path
    if default_sheet and default_sheet.exists():
        return default_sheet
    default_sheet_path = BASE_DIR / "assets" / "characters" / "kol_main" / "character_sheet_default.png"
    if default_sheet_path.exists():
        return default_sheet_path
    return BASE_DIR / char_data.get("portrait_image", "assets/characters/kol_main/portrait.png")


def resolve_canonical_face_anchor(
    char_data: dict,
    default_portrait: Path,
) -> Path:
    """Resolves the canonical neutral face anchor portrait."""
    face_rel = char_data.get("face_anchor") or char_data.get("portrait_image")
    if face_rel:
        p = BASE_DIR / face_rel
        if p.exists():
            return p
    return default_portrait


def resolve_product_hero_reference(
    wardrobe: Optional[Any] = None,
    workspace: Optional[ProjectWorkspace] = None,
) -> Path:
    """Resolves a pure product visual reference free of character facial features."""
    if workspace and hasattr(workspace, "input_dir") and workspace.input_dir.exists():
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            found = sorted(workspace.input_dir.glob(ext))
            if found:
                return found[0]
    default_prod = BASE_DIR / "assets" / "products" / "default_product.jpg"
    if default_prod.exists():
        return default_prod
    return BASE_DIR / "assets" / "characters" / "kol_main" / "portrait.png"


def _repo_rel(path: str | Path) -> str:
    """Path relative to the repo root (identity anchors live outside the run root)."""
    try:
        return str(Path(path).resolve().relative_to(BASE_DIR))
    except Exception:
        return str(path)


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
    canonical_identity_ref = resolve_canonical_identity_reference(archetype_val, char_data, default_portrait)
    canonical_char_sheet = resolve_canonical_character_sheet(archetype_val, char_data)
    canonical_face_anchor = resolve_canonical_face_anchor(char_data, default_portrait)
    product_hero_ref = resolve_product_hero_reference(wardrobe, workspace=workspace)
    keyframe_assets: List[KeyframeAsset] = []
    telea_inpainted = 0
    fallback_references = 0

    for idx, shot in enumerate(scene_plan.shots, start=1):
        is_prod_only = getattr(shot, "character_role", None) == CharacterRole.PRODUCT_ONLY or (
            hasattr(shot.character_role, "value") and shot.character_role.value == "product_only"
        )
        is_model_role = getattr(shot, "character_role", None) == CharacterRole.MODEL or (
            hasattr(shot.character_role, "value") and shot.character_role.value == "model"
        )
        reference_is_fallback = True

        if is_prod_only:
            gen_mode = "product_hero"
            # Product isolation: strictly avoid character face injection in product macro shots
            if getattr(wardrobe, "shot_references", None) and shot.shot_id in wardrobe.shot_references:
                custom_ref = BASE_DIR / wardrobe.shot_references[shot.shot_id]
                if custom_ref.exists():
                    ref_path = custom_ref
                    reference_is_fallback = False
                else:
                    ref_path = product_hero_ref
            else:
                ref_path = product_hero_ref
            ref_assets = [_repo_rel(ref_path)]
        elif is_model_role or getattr(shot, "generation_mode", None) == "r2v":
            # Model role / kinetic action: Directorial Dispatch routes to R2V with Dual-Anchor
            gen_mode = "r2v"
            ref_path = canonical_char_sheet
            reference_is_fallback = False
            ref_assets = [_repo_rel(canonical_char_sheet), _repo_rel(canonical_face_anchor)]
        else:
            # Presenter role (or direct speech): Directorial Dispatch routes to I2V with First Frame
            gen_mode = "i2v"
            if getattr(wardrobe, "shot_references", None) and shot.shot_id in wardrobe.shot_references:
                custom_ref = BASE_DIR / wardrobe.shot_references[shot.shot_id]
                if custom_ref.exists():
                    ref_path = custom_ref
                    reference_is_fallback = False
                else:
                    ref_path = canonical_identity_ref
            elif shot.reference_expression:
                custom_ref = BASE_DIR / shot.reference_expression
                if custom_ref.exists():
                    ref_path = custom_ref
                    reference_is_fallback = False
                else:
                    ref_path = canonical_identity_ref
            else:
                ref_path = canonical_identity_ref
            ref_assets = [_repo_rel(ref_path)]
        if not ref_path or not ref_path.exists():
            ref_path = default_portrait
            reference_is_fallback = True
        clean_keyframe_path = target_keyframes_dir / f"{shot.shot_id}_clean.jpg"

        # Format and fit into 9:16 target with Telea Inpainting
        # (prepare_9_16_frame always ends with clean_watermark_inpaint, or raises).
        w, h = prepare_9_16_frame(ref_path, clean_keyframe_path, target_width=1080, target_height=1920)
        telea_inpainted += 1
        if reference_is_fallback:
            fallback_references += 1

        recorder = telemetry.current()
        keyframe_record = (
            recorder.register_artifact(
                clean_keyframe_path,
                stage=STAGE_IDENTITY_KEYFRAMES,
                label=f"{shot.shot_id} clean 9:16 keyframe",
            )
            if recorder is not None
            else None
        )
        telemetry.stage_progress(
            STAGE_IDENTITY_KEYFRAMES,
            idx,
            len(scene_plan.shots),
            unit="shots",
            label=f"Keyframe {shot.shot_id}",
            item={
                "id": shot.shot_id,
                "status": "keyframe_ready",
                "source_image": _repo_rel(ref_path),
                "cleaned_image": (keyframe_record or {}).get("rel_path") or str(clean_keyframe_path),
                "watermark_removed": True,
                "telea_inpaint": True,
                "width": w,
                "height": h,
                "fallback_reference": reference_is_fallback,
                "generation_mode": gen_mode,
                "reference_assets": ref_assets,
            },
        )

        keyframe_assets.append(
            KeyframeAsset(
                shot_id=shot.shot_id,
                image_path=str(ref_path),
                cleaned_image_path=str(clean_keyframe_path),
                watermark_removed=True,
                width=w,
                height=h,
                generation_mode=gen_mode,
                reference_assets=ref_assets,
            )
        )
    total_shots = len(scene_plan.shots)
    telemetry.note(
        f"Telea watermark inpaint applied to {telea_inpainted}/{total_shots} keyframes "
        f"({fallback_references} identity anchors resolved from fallback references)",
        telea_inpaint_applied=telea_inpainted,
        total_keyframes=total_shots,
        fallback_references=fallback_references,
    )
    manifest = AssetManifestArtifact(
        campaign_id=scene_plan.campaign_id,
        keyframes=keyframe_assets,
    )

    out_file = target_artifacts_dir / "asset_manifest.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)

    return manifest
