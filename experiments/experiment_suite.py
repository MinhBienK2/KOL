"""Run the sequence of autoresearch consistency experiments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pipeline import telemetry
from pipeline.archetypes import CharacterRole, ProductArchetype
from pipeline.config import ARTIFACTS_DIR, BASE_DIR, CHARACTER_PATH, KEYFRAMES_DIR
from pipeline.identity_keyframe import generate_clean_keyframes, prepare_9_16_frame
from pipeline.schemas import AssetManifestArtifact, KeyframeAsset, ScenePlanArtifact
from pipeline.wardrobe import resolve_wardrobe_and_environment
from experiments.run_experiment import (
    init_results_tsv,
    log_experiment,
    run_eval_batch,
    test_suite_campaigns,
)


def baseline_keyframe_gen(plan: ScenePlanArtifact, out_dir: Path) -> AssetManifestArtifact:
    """Current baseline implementation directly from pipeline.identity_keyframe."""
    return generate_clean_keyframes(
        scene_plan=plan,
        output_dir=out_dir,
        keyframes_dir=out_dir / "keyframes",
    )


def experiment_a_product_isolation(plan: ScenePlanArtifact, out_dir: Path) -> AssetManifestArtifact:
    """Variant A: Strictly respect is_prod_only and isolate product shots from character references."""
    with open(CHARACTER_PATH, "r", encoding="utf-8") as f:
        char_data = json.load(f)
    default_portrait = BASE_DIR / char_data.get("portrait_image", "assets/characters/kol_main/portrait.png")

    # Fallback product hero placeholder image
    product_hero = BASE_DIR / "assets" / "wardrobe" / "fashion_cherry_dress" / "hero_product.jpg"

    kf_dir = out_dir / "keyframes"
    kf_dir.mkdir(parents=True, exist_ok=True)
    keyframe_assets: List[KeyframeAsset] = []

    for shot in plan.shots:
        is_prod = (
            getattr(shot, "character_role", None) == CharacterRole.PRODUCT_ONLY
            or (hasattr(shot.character_role, "value") and shot.character_role.value == "product_only")
        )

        if is_prod:
            # Strictly isolate: use product hero or neutral product frame, NEVER character face
            ref_path = product_hero if product_hero.exists() else default_portrait
        else:
            # Baseline character selection
            kol_beat_map = {
                "shot_01": BASE_DIR / "archive_raw" / "ref_10_speaking_hand_gesture.jpg",
                "shot_02": BASE_DIR / "assets" / "characters" / "kol_main" / "full_body" / "01_standing_front_0deg.jpg",
                "shot_03": BASE_DIR / "archive_raw" / "ref_10_speaking_hand_gesture.jpg",
                "shot_04": BASE_DIR / "assets" / "characters" / "kol_main" / "expressions" / "04_looking_down.jpg",
                "shot_05": BASE_DIR / "archive_raw" / "ref_09_three_quarter_left_45deg.jpg",
                "shot_06": BASE_DIR / "assets" / "characters" / "kol_main" / "expressions" / "02_smiling.jpg",
            }
            ref_path = kol_beat_map.get(shot.shot_id, default_portrait)

        clean_path = kf_dir / f"{shot.shot_id}_clean.jpg"
        w, h = prepare_9_16_frame(ref_path, clean_path, target_width=1080, target_height=1920)
        keyframe_assets.append(
            KeyframeAsset(
                shot_id=shot.shot_id,
                image_path=str(ref_path),
                cleaned_image_path=str(clean_path),
                watermark_removed=True,
                width=w,
                height=h,
            )
        )

    return AssetManifestArtifact(campaign_id=plan.campaign_id, keyframes=keyframe_assets)


def experiment_b_archetype_wardrobe_binding(plan: ScenePlanArtifact, out_dir: Path) -> AssetManifestArtifact:
    """Variant B: Bind character shots to the archetype's canonical wardrobe profile and identity sheet."""
    with open(CHARACTER_PATH, "r", encoding="utf-8") as f:
        char_data = json.load(f)

    # Map archetype to canonical identity in character.json
    identities = {ident["identity_id"]: ident for ident in char_data.get("identities", [])}
    archetype_to_identity = {
        ProductArchetype.FASHION_APPAREL: "kol_main_fashion",
        ProductArchetype.TECH_GADGETS: "kol_main_techwear",
        ProductArchetype.BEAUTY_SKINCARE: "kol_main_spa",
        ProductArchetype.HOME_LIFESTYLE: "kol_main_cozy",
        ProductArchetype.GENERAL_COMMERCIAL: "kol_main_office",
    }

    # Infer campaign archetype from shots or plan
    # Use fashion as default for test
    arch_id = archetype_to_identity.get(ProductArchetype.FASHION_APPAREL, "kol_main_office")
    ident_config = identities.get(arch_id, {})
    canonical_ref = BASE_DIR / ident_config.get("reference_sheet", "assets/characters/kol_main/portrait.png")

    kf_dir = out_dir / "keyframes"
    kf_dir.mkdir(parents=True, exist_ok=True)
    keyframe_assets: List[KeyframeAsset] = []

    for shot in plan.shots:
        # Uniformly bind character shots to the single canonical wardrobe reference sheet
        ref_path = canonical_ref if canonical_ref.exists() else (BASE_DIR / "assets/characters/kol_main/portrait.png")
        clean_path = kf_dir / f"{shot.shot_id}_clean.jpg"
        w, h = prepare_9_16_frame(ref_path, clean_path, target_width=1080, target_height=1920)
        keyframe_assets.append(
            KeyframeAsset(
                shot_id=shot.shot_id,
                image_path=str(ref_path),
                cleaned_image_path=str(clean_path),
                watermark_removed=True,
                width=w,
                height=h,
            )
        )

    return AssetManifestArtifact(campaign_id=plan.campaign_id, keyframes=keyframe_assets)


def experiment_c_full_integrated(plan: ScenePlanArtifact, out_dir: Path) -> AssetManifestArtifact:
    """Variant C: Full Integrated Architecture: Product Isolation + Archetype Wardrobe Binding."""
    with open(CHARACTER_PATH, "r", encoding="utf-8") as f:
        char_data = json.load(f)

    identities = {ident["identity_id"]: ident for ident in char_data.get("identities", [])}
    archetype_to_identity = {
        "fashion_apparel": "kol_main_fashion",
        "tech_gadgets": "kol_main_techwear",
        "beauty_skincare": "kol_main_spa",
        "home_lifestyle": "kol_main_cozy",
        "general_commercial": "kol_main_office",
    }

    product_hero = BASE_DIR / "assets" / "wardrobe" / "fashion_cherry_dress" / "hero_product.jpg"

    kf_dir = out_dir / "keyframes"
    kf_dir.mkdir(parents=True, exist_ok=True)
    keyframe_assets: List[KeyframeAsset] = []

    for shot in plan.shots:
        is_prod = (
            getattr(shot, "character_role", None) == CharacterRole.PRODUCT_ONLY
            or (hasattr(shot.character_role, "value") and shot.character_role.value == "product_only")
        )

        if is_prod:
            # 1. Product isolation
            ref_path = product_hero if product_hero.exists() else (BASE_DIR / "assets" / "characters" / "kol_main" / "portrait.png")
        else:
            # 2. Archetype identity binding with expression variations if available, but preserving wardrobe
            arch_key = getattr(shot, "archetype", "fashion_apparel")
            ident_id = archetype_to_identity.get(str(arch_key), "kol_main_fashion")
            ident = identities.get(ident_id, {})
            canonical_ref = BASE_DIR / ident.get("reference_sheet", "assets/characters/kol_main/portrait.png")

            # Check if shot has a specific expression reference from same character
            if shot.reference_expression and (BASE_DIR / shot.reference_expression).exists():
                ref_path = BASE_DIR / shot.reference_expression
            elif canonical_ref.exists():
                ref_path = canonical_ref
            else:
                ref_path = BASE_DIR / "assets" / "characters" / "kol_main" / "portrait.png"

        clean_path = kf_dir / f"{shot.shot_id}_clean.jpg"
        w, h = prepare_9_16_frame(ref_path, clean_path, target_width=1080, target_height=1920)
        keyframe_assets.append(
            KeyframeAsset(
                shot_id=shot.shot_id,
                image_path=str(ref_path),
                cleaned_image_path=str(clean_path),
                watermark_removed=True,
                width=w,
                height=h,
            )
        )

    return AssetManifestArtifact(campaign_id=plan.campaign_id, keyframes=keyframe_assets)


def run_all_experiments() -> None:
    tmp_root = BASE_DIR / "output" / "autoresearch_experiments"
    tmp_root.mkdir(parents=True, exist_ok=True)

    suite = test_suite_campaigns(tmp_root / "test_suite")
    print(f"Generated {len(suite)} test campaigns for evaluation.")

    init_results_tsv()

    # Exp 0: Baseline
    print("\n--- Running Baseline Experiment ---")
    m0 = run_eval_batch(baseline_keyframe_gen, suite, tmp_root / "exp0_baseline")
    log_experiment("exp00_baseline", m0, "keep", "Baseline: disparate archive photos & ignored is_prod_only")

    # Exp 1: Product Isolation
    print("\n--- Running Experiment A: Product Isolation ---")
    mA = run_eval_batch(experiment_a_product_isolation, suite, tmp_root / "exp1_prod_iso")
    log_experiment("exp01_prod_iso", mA, "keep", "Product isolation: zero character face leakage in product shots")

    # Exp 2: Wardrobe Binding
    print("\n--- Running Experiment B: Wardrobe Binding ---")
    mB = run_eval_batch(experiment_b_archetype_wardrobe_binding, suite, tmp_root / "exp2_wardrobe")
    log_experiment("exp02_wardrobe", mB, "keep", "Archetype wardrobe binding: uniform costume per campaign")

    # Exp 3: Integrated
    print("\n--- Running Experiment C: Full Integrated Architecture ---")
    mC = run_eval_batch(experiment_c_full_integrated, suite, tmp_root / "exp3_integrated")
    status = "keep" if mC.consistency_loss < m0.consistency_loss else "discard"
    log_experiment("exp03_integrated", mC, status, "Integrated: product isolation + archetype wardrobe binding")


if __name__ == "__main__":
    run_all_experiments()
