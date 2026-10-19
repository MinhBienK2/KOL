"""Autoresearch Evaluation Harness for KOL Character & Wardrobe Consistency.

Fixed ground truth evaluation rules, test cases, and consistency metrics.
Modeled after autoresearch/prepare.py principles.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline.archetypes import CharacterRole, ProductArchetype
from pipeline.config import BASE_DIR, CHARACTER_PATH
from pipeline.schemas import ScenePlanArtifact, StoryboardShot, AssetManifestArtifact
from pipeline.storyboard import generate_scene_plan
from pipeline.scriptwriter import generate_commercial_script
from pipeline.briefing import create_product_brief


@dataclass
class ConsistencyMetrics:
    """Quantitative evaluation metrics for character & wardrobe consistency across scenes."""
    total_shots: int
    character_shots: int
    product_shots: int
    wardrobe_mismatches: int
    wardrobe_mismatch_rate: float
    product_leakages: int
    product_leakage_rate: float
    identity_prompt_entropy: float
    lighting_contract_divergence: float
    consistency_loss: float  # Lower is better (0.0 is perfect consistency)
    details: Dict[str, Any] = field(default_factory=dict)


def evaluate_manifest_consistency(
    scene_plan: ScenePlanArtifact,
    manifest: AssetManifestArtifact,
    archetype: ProductArchetype,
) -> ConsistencyMetrics:
    """Ground truth evaluation of a generated keyframe manifest and scene plan."""
    total_shots = len(scene_plan.shots)
    char_shots = 0
    prod_shots = 0
    wardrobe_mismatches = 0
    product_leakages = 0

    kf_map = {kf.shot_id: kf for kf in manifest.keyframes}
    
    # Track reference image outfits observed
    char_outfits_detected: List[str] = []

    for shot in scene_plan.shots:
        is_prod = (
            getattr(shot, "character_role", None) == CharacterRole.PRODUCT_ONLY
            or (hasattr(shot.character_role, "value") and shot.character_role.value == "product_only")
        )
        kf = kf_map.get(shot.shot_id)
        img_path = (kf.image_path if kf else "") or ""

        if is_prod:
            prod_shots += 1
            # Product shot MUST NOT have character face reference
            if "character" in img_path.lower() or "kol_main" in img_path.lower() or "ref_10" in img_path.lower():
                product_leakages += 1
        else:
            char_shots += 1
            # Classify outfit / source of reference image
            if "ref_10" in img_path or "speaking_hand_gesture" in img_path:
                outfit = "archive_black_hoodie"
            elif "01_standing_front_0deg" in img_path:
                outfit = "white_shirt_navy_trousers"
            elif "fashion_cherry_dress" in img_path or "french_dress" in img_path:
                outfit = "cherry_dress"
            elif "kol_main_fashion" in img_path:
                outfit = "haute_couture_evening"
            elif "kol_main_techwear" in img_path:
                outfit = "techwear_hoodie"
            elif "kol_main_spa" in img_path:
                outfit = "spa_silk_wrap"
            elif "kol_main_office" in img_path or "expressions" in img_path:
                outfit = "office_white_shirt"
            else:
                outfit = f"other_{Path(img_path).stem}"
            char_outfits_detected.append(outfit)

    # Wardrobe mismatch occurs when multiple different outfits are mixed within the same campaign
    distinct_outfits = set(char_outfits_detected)
    if len(distinct_outfits) > 1:
        # Penalize shots that deviate from the primary outfit
        from collections import Counter
        counts = Counter(char_outfits_detected)
        primary_outfit, primary_count = counts.most_common(1)[0]
        wardrobe_mismatches = len(char_outfits_detected) - primary_count
    else:
        wardrobe_mismatches = 0

    wardrobe_mismatch_rate = (wardrobe_mismatches / max(1, char_shots))
    product_leakage_rate = (product_leakages / max(1, prod_shots))

    # Evaluate prompt identity entropy (variance of character descriptions)
    identity_tokens: List[set] = []
    for shot in scene_plan.shots:
        if shot.identity_lock_directive:
            tokens = set(shot.identity_lock_directive.lower().replace(",", " ").split())
            identity_tokens.append(tokens)

    if len(identity_tokens) > 1:
        all_tokens = set.union(*identity_tokens)
        shared_tokens = set.intersection(*identity_tokens)
        prompt_entropy = 1.0 - (len(shared_tokens) / max(1, len(all_tokens)))
    else:
        prompt_entropy = 0.0

    # Lighting contract divergence
    lightings = {shot.lighting_contract for shot in scene_plan.shots if shot.lighting_contract}
    lighting_divergence = 0.0 if len(lightings) <= 1 else (len(lightings) - 1) * 0.1

    # Composite consistency loss (0.0 is perfect)
    # Weights: wardrobe mismatch (0.45), product leakage (0.35), prompt entropy (0.15), lighting (0.05)
    consistency_loss = (
        0.45 * wardrobe_mismatch_rate
        + 0.35 * product_leakage_rate
        + 0.15 * prompt_entropy
        + 0.05 * min(1.0, lighting_divergence)
    )

    return ConsistencyMetrics(
        total_shots=total_shots,
        character_shots=char_shots,
        product_shots=prod_shots,
        wardrobe_mismatches=wardrobe_mismatches,
        wardrobe_mismatch_rate=round(wardrobe_mismatch_rate, 4),
        product_leakages=product_leakages,
        product_leakage_rate=round(product_leakage_rate, 4),
        identity_prompt_entropy=round(prompt_entropy, 4),
        lighting_contract_divergence=round(lighting_divergence, 4),
        consistency_loss=round(consistency_loss, 4),
        details={
            "distinct_outfits": list(distinct_outfits),
            "outfits_sequence": char_outfits_detected,
        },
    )
