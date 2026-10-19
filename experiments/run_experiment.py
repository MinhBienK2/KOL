"""Autoresearch Experiment Runner for Character & Wardrobe Consistency.

Runs experiments against test campaigns, measures consistency metrics,
and logs results to experiments/results.tsv following the autoresearch pattern.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from pipeline.archetypes import ProductArchetype
from pipeline.briefing import create_product_brief
from pipeline.config import BASE_DIR
from pipeline.schemas import AssetManifestArtifact, ScenePlanArtifact
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from pipeline.workspace import ProjectWorkspace
from experiments.prepare_consistency import evaluate_manifest_consistency, ConsistencyMetrics

RESULTS_TSV = BASE_DIR / "experiments" / "results.tsv"


def init_results_tsv() -> None:
    if not RESULTS_TSV.exists():
        with open(RESULTS_TSV, "w", encoding="utf-8") as f:
            f.write("exp_id\tconsistency_loss\twardrobe_mismatch\tproduct_leakage\tstatus\tdescription\n")


def log_experiment(
    exp_id: str,
    metrics: ConsistencyMetrics,
    status: str,
    description: str,
) -> None:
    init_results_tsv()
    with open(RESULTS_TSV, "a", encoding="utf-8") as f:
        f.write(
            f"{exp_id}\t"
            f"{metrics.consistency_loss:.4f}\t"
            f"{metrics.wardrobe_mismatch_rate:.4f}\t"
            f"{metrics.product_leakage_rate:.4f}\t"
            f"{status}\t"
            f"{description}\n"
        )
    print(
        f"[Experiment {exp_id}] Loss: {metrics.consistency_loss:.4f} | "
        f"Wardrobe Mismatch: {metrics.wardrobe_mismatch_rate:.2%} | "
        f"Product Leakage: {metrics.product_leakage_rate:.2%} | Status: {status}"
    )


def test_suite_campaigns(tmp_dir: Path) -> List[Tuple[ProductArchetype, str, ScenePlanArtifact]]:
    """Generates standard test scene plans across archetypes."""
    campaigns = [
        (ProductArchetype.FASHION_APPAREL, "test_blazer", "Áo Khoác Blazer Nữ Form Rộng"),
        (ProductArchetype.TECH_GADGETS, "test_gadget", "Bàn Phím Cơ Không Dây CyberKey"),
        (ProductArchetype.BEAUTY_SKINCARE, "test_serum", "Serum Dưỡng Trắng Căng Bóng"),
    ]
    plans = []
    for arch, pid, pname in campaigns:
        pdir = tmp_dir / pid
        pdir.mkdir(parents=True, exist_ok=True)
        brief = create_product_brief(
            campaign_id=f"campaign_{pid}",
            product_name=pname,
            category="Test",
            archetype=arch,
            output_dir=pdir,
        )
        script = generate_commercial_script(brief=brief, output_dir=pdir)
        plan = generate_scene_plan(script=script, output_dir=pdir)
        plans.append((arch, pid, plan))
    return plans


def run_eval_batch(
    keyframe_gen_fn: Callable[[ScenePlanArtifact, Path], AssetManifestArtifact],
    suite: List[Tuple[ProductArchetype, str, ScenePlanArtifact]],
    tmp_dir: Path,
) -> ConsistencyMetrics:
    """Runs a batch evaluation across test campaigns and aggregates metrics."""
    total_shots = 0
    total_char = 0
    total_prod = 0
    total_mismatches = 0
    total_leakages = 0
    entropy_sum = 0.0
    lighting_sum = 0.0

    for arch, pid, plan in suite:
        out_dir = tmp_dir / f"run_{pid}"
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = keyframe_gen_fn(plan, out_dir)
        m = evaluate_manifest_consistency(plan, manifest, arch)
        total_shots += m.total_shots
        total_char += m.character_shots
        total_prod += m.product_shots
        total_mismatches += m.wardrobe_mismatches
        total_leakages += m.product_leakages
        entropy_sum += m.identity_prompt_entropy
        lighting_sum += m.lighting_contract_divergence

    n = len(suite)
    w_rate = total_mismatches / max(1, total_char)
    p_rate = total_leakages / max(1, total_prod)
    avg_entropy = entropy_sum / n
    avg_lighting = lighting_sum / n

    loss = (
        0.45 * w_rate
        + 0.35 * p_rate
        + 0.15 * avg_entropy
        + 0.05 * min(1.0, avg_lighting)
    )

    return ConsistencyMetrics(
        total_shots=total_shots,
        character_shots=total_char,
        product_shots=total_prod,
        wardrobe_mismatches=total_mismatches,
        wardrobe_mismatch_rate=round(w_rate, 4),
        product_leakages=total_leakages,
        product_leakage_rate=round(p_rate, 4),
        identity_prompt_entropy=round(avg_entropy, 4),
        lighting_contract_divergence=round(avg_lighting, 4),
        consistency_loss=round(loss, 4),
    )
