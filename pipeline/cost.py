"""Pre-generation cost estimate: what paid calls a run is about to make (no network, no writes).

``estimate_paid_generation`` counts the paid MiniMax video jobs Stage 5 would submit (shots whose
clip is not already cached), the Stage 6 TTS calls and any image calls, plus the total generated
seconds. Prices are unknown by default: supply a per-model unit-cost table through
``KOL_UNIT_COSTS`` (a JSON object, or a path to a JSON file)::

    {"currency": "USD",
     "MiniMax-Hailuo-2.3": {"per_job": 0.28},          # or "per_second"
     "tts-1": {"per_call": 0.01}}

A bare number for a model means ``per_job`` (video) / ``per_call`` (TTS). Anything not in the
table has a ``null`` cost, and ``estimated_cost`` is ``null`` unless every paid item is priced.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from pipeline.config import DEFAULT_TTS_MODEL
from pipeline.offline import is_offline
from pipeline.schemas import AssetManifestArtifact, ScenePlanArtifact, ScriptArtifact
from pipeline.video_engine import plan_video_jobs, resolve_video_mode

UNIT_COSTS_ENV = "KOL_UNIT_COSTS"


def load_unit_costs(raw: Optional[str] = None) -> dict[str, Any]:
    """Load the unit-cost table from ``raw`` / ``$KOL_UNIT_COSTS`` (JSON text or file path); ``{}`` if unset."""
    text = (raw if raw is not None else os.environ.get(UNIT_COSTS_ENV, "")).strip()
    if not text:
        return {}
    if not text.lstrip().startswith("{"):
        text = Path(text).read_text(encoding="utf-8")
    table = json.loads(text)
    if not isinstance(table, dict):
        raise ValueError(f"{UNIT_COSTS_ENV} must be a JSON object keyed by model name")
    return table


def _entry(table: Mapping[str, Any], model: str, unit: str) -> Optional[float]:
    """Price of one ``unit`` (``per_job``/``per_second``/``per_call``) for ``model``; ``None`` if unknown."""
    spec = table.get(model)
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        spec = {"per_call" if unit == "per_call" else "per_job": spec}
    if not isinstance(spec, dict):
        return None
    value = spec.get(unit)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def estimate_paid_generation(
    scene_plan: Optional[ScenePlanArtifact],
    manifest: Optional[AssetManifestArtifact],
    script: Optional[ScriptArtifact],
    raw_clips_dir: Path,
    *,
    video_mode: str = "api",
    include_video: bool = True,
    include_tts: bool = True,
    unit_costs: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Plan of paid calls for the stages about to run. JSON-serialisable.

    ``video_mode`` follows :func:`pipeline.video_engine.resolve_video_mode` (``ffmpeg`` and
    offline runs make no paid calls). ``include_video`` / ``include_tts`` say whether Stage 5 /
    Stage 6 will actually run. Image calls are always 0: the director pipeline generates no images
    through a paid API (Stage 4 stages existing references locally).
    """
    table = load_unit_costs() if unit_costs is None else dict(unit_costs)
    resolved_video = resolve_video_mode(video_mode)
    paid_video = include_video and resolved_video == "api" and scene_plan is not None and manifest is not None

    jobs: list[dict[str, Any]] = []
    cached = 0
    shots_total = len(scene_plan.shots) if scene_plan is not None else 0
    if paid_video:
        plan = plan_video_jobs(scene_plan, manifest, Path(raw_clips_dir))
        jobs = [j for j in plan if j["submit"]]
        cached = len(plan) - len(jobs)

    tts_calls = 0
    tts_seconds = 0.0
    if include_tts and script is not None and not is_offline():
        for beat in script.beats:
            if beat.spoken_text and beat.spoken_text.strip():
                tts_calls += 1
                tts_seconds += float(beat.estimated_duration or 0)

    video_seconds = float(sum(j["duration"] for j in jobs))
    by_model: dict[str, dict[str, Any]] = {}
    unpriced: list[str] = []
    cost_total: Optional[float] = 0.0

    def _add(model: str, kind: str, count: int, seconds: float, unit_price: Optional[float]) -> None:
        nonlocal cost_total
        row = by_model.setdefault(model, {"kind": kind, "calls": 0, "seconds": 0.0, "cost": None})
        row["calls"] += count
        row["seconds"] = round(row["seconds"] + seconds, 3)
        if unit_price is None:
            if model not in unpriced:
                unpriced.append(model)
            cost_total = None
        else:
            row["cost"] = round((row["cost"] or 0.0) + unit_price, 6)
            if cost_total is not None:
                cost_total += unit_price

    for job in jobs:
        per_job = _entry(table, job["model"], "per_job")
        per_second = _entry(table, job["model"], "per_second")
        price = per_job if per_job is not None else (per_second * job["duration"] if per_second is not None else None)
        _add(job["model"], "video", 1, float(job["duration"]), price)
    if tts_calls:
        per_call = _entry(table, DEFAULT_TTS_MODEL, "per_call")
        _add(DEFAULT_TTS_MODEL, "tts", tts_calls, tts_seconds, None if per_call is None else per_call * tts_calls)

    paid_calls = len(jobs) + tts_calls
    return {
        "available": True,
        "video_mode": resolved_video,
        "shots_total": shots_total,
        "video_jobs": len(jobs),
        "video_jobs_cached": cached,
        "video_seconds": video_seconds,
        "tts_calls": tts_calls,
        "tts_seconds": round(tts_seconds, 3),
        "image_calls": 0,
        "paid_calls": paid_calls,
        "total_generated_seconds": round(video_seconds + tts_seconds, 3),
        "jobs": jobs,
        "by_model": by_model,
        "currency": table.get("currency") if isinstance(table.get("currency"), str) else None,
        "estimated_cost": 0.0 if not paid_calls else (None if cost_total is None else round(cost_total, 6)),
        "unpriced_models": unpriced,
    }


def unavailable_estimate(reason: str) -> dict[str, Any]:
    """Placeholder when the inputs (scene plan, manifest, script) do not exist yet (e.g. ``--check`` from stage 1)."""
    return {"available": False, "reason": reason, "video_jobs": None, "tts_calls": None,
            "image_calls": None, "total_generated_seconds": None, "estimated_cost": None}


def estimate_for_workspace(workspace: Any, video_mode: str, stages_to_run: list[int]) -> dict[str, Any]:
    """Estimate from a workspace's saved artifacts for the given stages; ``available: false`` if not yet produced."""
    include_video, include_tts = 5 in stages_to_run, 6 in stages_to_run
    if not (include_video or include_tts):
        return {**unavailable_estimate("no paid stage (5, 6) will run"), "available": True,
                "video_jobs": 0, "tts_calls": 0, "image_calls": 0,
                "total_generated_seconds": 0.0, "estimated_cost": 0.0}
    artifacts = Path(workspace.artifacts_dir)
    missing = [n for n in ("script.json", "scene_plan.json", "asset_manifest.json") if not (artifacts / n).is_file()]
    if missing:
        return unavailable_estimate(
            f"{', '.join(missing)} not produced yet (stages 2-4); re-run --check or read the estimate printed before stage 5"
        )
    scene_plan = workspace.load_artifact("scene_plan.json", ScenePlanArtifact)
    manifest = workspace.load_artifact("asset_manifest.json", AssetManifestArtifact)
    script = workspace.load_artifact("script.json", ScriptArtifact)
    return estimate_paid_generation(
        scene_plan, manifest, script, Path(workspace.raw_clips_dir),
        video_mode=video_mode, include_video=include_video, include_tts=include_tts,
    )


def format_estimate(est: Mapping[str, Any]) -> str:
    """One-line human summary of an estimate."""
    if not est.get("available"):
        return f"Paid generation estimate unavailable: {est.get('reason')}"
    cost = est.get("estimated_cost")
    cost_txt = "unknown (no unit costs set)" if cost is None else f"{cost} {est.get('currency') or ''}".strip()
    return (
        f"Paid generation plan: {est['video_jobs']} video job(s) "
        f"({est['video_seconds']:g}s, {est['video_jobs_cached']} cached), {est['tts_calls']} TTS call(s), "
        f"{est['image_calls']} image call(s); {est['total_generated_seconds']:g} generated seconds; "
        f"estimated cost: {cost_txt}"
    )
