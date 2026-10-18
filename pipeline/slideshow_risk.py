"""OpenMontage-Adapted 6-Dimension Slideshow Risk Scorer and Hard Quality Gate.

Predicts whether a generated commercial scene plan will feel like a static slideshow
rather than a directed cinematic commercial video.

The 6 Dimensions (0.0 to 5.0, lower is better):
1. Repetition: Visual, shot type, camera angle, and pacing monotony.
2. Decorative Visuals: Scenes that merely decorate instead of communicating USP/pain/solution.
3. Weak Motion: Camera or subject motion that is static, sluggish, or purposeless.
4. Weak Shot Intent: Scenes lacking explicit commercial, psychological, or narrative objectives.
5. Typography Overreliance: Relying on text cards / stat graphics rather than visual cinematography.
6. Unsupported Cinematic Claims: Claiming 'cinematic 8k masterpiece' without structural lighting/movement.

Hard Quality Gate:
- Rejects any plan with average risk score >= 4.0.
- ZERO-TOLERANCE KINETIC RULE: Rejects any scene plan containing a shot that has BOTH
  static camera movement AND lacks purposeful kinetic subject action.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field


# High-kinetic action verbs indicating real physical motion in a commercial shot
KINETIC_ACTION_VERBS: Set[str] = {
    "pour", "pours", "pouring",
    "drink", "drinks", "drinking", "sip", "sips", "sipping",
    "tap", "taps", "tapping", "press", "presses", "pressing",
    "touch", "touches", "touching", "wipe", "wipes", "wiping",
    "slide", "slides", "sliding", "glide", "glides", "gliding",
    "rotate", "rotates", "rotating", "turn", "turns", "turning",
    "open", "opens", "opening", "unbox", "unboxes", "unboxing",
    "hold", "holds", "holding", "lift", "lifts", "lifting",
    "shake", "shakes", "shaking", "nod", "nods", "nodding",
    "gesture", "gestures", "gesturing", "smile", "smiles", "smiling",
    "react", "reacts", "reacting", "look", "looks", "looking",
    "illuminate", "illuminates", "illuminating", "glow", "glows", "glowing",
    "drip", "drips", "dripping", "drop", "drops", "dropping",
    "walk", "walks", "walking", "step", "steps", "stepping", "strides",
    "sway", "sways", "swaying", "flow", "flows", "flowing", "ripple", "ripples",
    "show", "shows", "showing", "present", "presents", "presenting",
    # Vietnamese kinetic action terms
    "bước", "sải", "xoay", "lắc", "chạm", "ấn", "bấm", "nhỏ", "thoa", "rót",
    "uống", "nâng", "cầm", "giơ", "mở", "bóc", "gõ", "vuốt", "đung", "đưa",
    "chuyển", "động", "dáng", "sáng", "rơi", "chảy", "lướt", "bắt", "nhấp",
}

# Static camera motion keywords indicating high slideshow risk
STATIC_CAMERA_KEYWORDS: Set[str] = {
    "static", "none", "fixed", "locked-off", "stationary", "no movement",
    "still", "unspecified", "tripod locked", "zero motion",
}


class DimensionScore(BaseModel):
    """Score and diagnostic reason for a single slideshow risk dimension."""
    score: float
    reason: str
    flagged_shots: List[str] = Field(default_factory=list)


class SlideshowRiskReport(BaseModel):
    """Comprehensive slideshow risk assessment and hard-gate verdict."""
    average_score: float
    verdict: str  # "strong", "acceptable", "revise", "fail", "rejected"
    passed: bool
    dimensions: Dict[str, DimensionScore]
    hard_reject_reasons: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


def _extract_shot_dict(shot: Any) -> Dict[str, Any]:
    """Normalizes StoryboardShot pydantic model or raw dict into a standard dict."""
    if hasattr(shot, "model_dump"):
        return shot.model_dump()
    if isinstance(shot, dict):
        return shot
    return {}


def _is_static_camera(camera_motion: str) -> bool:
    """Detects if camera motion string specifies static or no movement."""
    norm = camera_motion.strip().lower()
    if not norm:
        return True
    return any(kw in norm for kw in STATIC_CAMERA_KEYWORDS)


def _has_kinetic_subject_action(description: str, explicit_kinetic: Optional[str] = None) -> bool:
    """Checks if scene action contains active physical movement verbs."""
    combined = f"{description} {explicit_kinetic or ''}".lower()
    words = set(re.findall(r"[a-z]+", combined))
    return len(words.intersection(KINETIC_ACTION_VERBS)) > 0

def _score_repetition(shots: List[Dict[str, Any]]) -> DimensionScore:
    """Scores visual and structural repetition across shots."""
    if len(shots) < 3:
        return DimensionScore(score=0.0, reason="Too few shots to assess repetition.")

    from collections import Counter
    n = len(shots)

    # 1. Shot type repetition
    shot_types = [s.get("shot_type", "unknown").strip().lower() for s in shots]
    type_counts = Counter(shot_types)
    most_common_type, most_common_type_count = type_counts.most_common(1)[0]
    type_ratio = most_common_type_count / n

    # 2. Camera motion repetition
    motions = [s.get("camera_motion", "unknown").strip().lower() for s in shots]
    motion_counts = Counter(motions)
    most_common_motion, most_common_motion_count = motion_counts.most_common(1)[0]
    motion_ratio = most_common_motion_count / n

    # 3. Duration pacing variation (lack of dynamic tempo)
    durations = [float(s.get("estimated_duration", 4.0)) for s in shots]
    duration_std = (sum((d - sum(durations)/n) ** 2 for d in durations) / n) ** 0.5

    score = 0.0
    reasons = []
    flagged = []

    if type_ratio > 0.6:
        score += 2.0
        reasons.append(f"Shot type '{most_common_type}' dominates {type_ratio:.0%} of scenes")
    elif type_ratio > 0.4:
        score += 1.0

    if motion_ratio > 0.6:
        score += 2.0
        reasons.append(f"Camera movement '{most_common_motion}' repeats in {motion_ratio:.0%} of shots")
        flagged.extend([s.get("shot_id", "") for s in shots if s.get("camera_motion", "").lower() == most_common_motion])

    if duration_std < 0.3 and n >= 4:
        score += 1.0
        reasons.append(f"Monotonous duration pacing (all shots ~{durations[0]:.1f}s)")

    final_score = min(5.0, score)
    return DimensionScore(
        score=round(final_score, 1),
        reason="; ".join(reasons) or "Healthy variety in shot types, camera choreography, and duration rhythm.",
        flagged_shots=flagged,
    )


def _score_decorative_visuals(shots: List[Dict[str, Any]]) -> DimensionScore:
    """Scores whether shots have communicative purpose (problem, solution, demo, CTA) vs mere wallpaper."""
    decorative_count = 0
    flagged = []

    for s in shots:
        shot_id = s.get("shot_id", "unknown")
        intent = s.get("shot_intent") or s.get("scene_id") or ""
        desc = s.get("scene_description") or ""
        prompt = s.get("prompt_6part") or ""

        # A shot without functional commercial intent or product interaction is decorative
        has_intent = bool(intent.strip())
        has_action = _has_kinetic_subject_action(desc) or _has_kinetic_subject_action(prompt)

        if not has_intent or not has_action:
            decorative_count += 1
            flagged.append(shot_id)

    ratio = decorative_count / len(shots) if shots else 1.0
    score = min(5.0, ratio * 5.0)

    if ratio > 0.5:
        reason = f"{decorative_count}/{len(shots)} shots lack communicative intent or active subject demonstration"
    elif ratio > 0.2:
        reason = f"{decorative_count}/{len(shots)} shots border on decorative without explicit product interaction"
    else:
        reason = "All shots possess clear communicative commercial roles"

    return DimensionScore(
        score=round(score, 1),
        reason=reason,
        flagged_shots=flagged,
    )


def _score_weak_motion(shots: List[Dict[str, Any]]) -> DimensionScore:
    """Scores whether camera movement and subject kinetics are purposeful and active."""
    static_camera_count = 0
    non_kinetic_count = 0
    flagged = []

    for s in shots:
        shot_id = s.get("shot_id", "unknown")
        cam_motion = s.get("camera_motion") or s.get("camera_choreography") or ""
        desc = s.get("scene_description") or ""
        kinetic = s.get("kinetic_action") or ""

        is_cam_static = _is_static_camera(cam_motion)
        has_action = _has_kinetic_subject_action(desc, kinetic)

        if is_cam_static:
            static_camera_count += 1
        if not has_action:
            non_kinetic_count += 1
        if is_cam_static and not has_action:
            flagged.append(shot_id)
    n = len(shots) if shots else 1
    cam_penalty = (static_camera_count / n) * 3.0
    action_penalty = (non_kinetic_count / n) * 2.0
    score = min(5.0, cam_penalty + action_penalty)

    reasons = []
    if static_camera_count > 0:
        reasons.append(f"{static_camera_count}/{n} shots have static or unspecified camera motion")
    if non_kinetic_count > 0:
        reasons.append(f"{non_kinetic_count}/{n} shots lack active kinetic subject action verbs")
    if not reasons:
        reasons.append("Strong kinetic energy: continuous camera choreography and purposeful subject action")

    return DimensionScore(
        score=round(score, 1),
        reason="; ".join(reasons),
        flagged_shots=flagged,
    )


def _score_weak_shot_intent(shots: List[Dict[str, Any]]) -> DimensionScore:
    """Scores completeness of explicit commercial shot intent (hook, pain, reveal, proof, cta)."""
    valid_intents = {
        "hook", "pain", "problem", "solution", "reveal", "demonstration", "demo",
        "proof", "gratification", "cta", "call_to_action", "urgency", "reaction",
    }
    missing_intent = 0
    flagged = []

    for s in shots:
        shot_id = s.get("shot_id", "unknown")
        intent_raw = s.get("shot_intent") or s.get("scene_id") or ""
        intent_tokens = set(re.findall(r"[a-z]+", intent_raw.lower()))
        if not intent_tokens.intersection(valid_intents):
            missing_intent += 1
            flagged.append(shot_id)

    ratio = missing_intent / len(shots) if shots else 1.0
    score = min(5.0, ratio * 5.0)

    if ratio > 0.4:
        reason = f"{missing_intent}/{len(shots)} shots lack recognized commercial intent taxonomy"
    elif ratio > 0.0:
        reason = f"{missing_intent}/{len(shots)} shots have ambiguous commercial intent"
    else:
        reason = "Comprehensive commercial intent defined across every shot"

    return DimensionScore(
        score=round(score, 1),
        reason=reason,
        flagged_shots=flagged,
    )


def _score_typography_overreliance(shots: List[Dict[str, Any]]) -> DimensionScore:
    """Scores whether video over-relies on static text cards or graphic overlays."""
    text_heavy_count = 0
    flagged = []

    for s in shots:
        shot_id = s.get("shot_id", "unknown")
        shot_type = (s.get("shot_type") or "").lower()
        desc = (s.get("scene_description") or "").lower()

        if any(kw in shot_type or kw in desc for kw in ["text card", "slide", "stat card", "bullet list", "bullet points"]):
            text_heavy_count += 1
            flagged.append(shot_id)

    ratio = text_heavy_count / len(shots) if shots else 0.0
    score = min(5.0, ratio * 5.0)

    if ratio > 0.5:
        reason = f"{text_heavy_count}/{len(shots)} shots are text cards — will feel like animated presentation slides"
    elif ratio > 0.2:
        reason = f"{text_heavy_count}/{len(shots)} shots rely on text cards"
    else:
        reason = "Visual-first video storytelling with zero static text card dependency"

    return DimensionScore(
        score=round(score, 1),
        reason=reason,
        flagged_shots=flagged,
    )


def _score_unsupported_cinematic_claims(shots: List[Dict[str, Any]]) -> DimensionScore:
    """Scores whether 'cinematic' claims are supported by concrete lighting and motion."""
    cinematic_claims = 0
    unsupported_count = 0
    flagged = []

    for s in shots:
        shot_id = s.get("shot_id", "unknown")
        prompt = (s.get("prompt_6part") or "").lower()
        style = (s.get("style_constraints") or "").lower()
        combined = f"{prompt} {style}"

        claims_cinematic = any(kw in combined for kw in ["cinematic", "commercial grade", "8k", "masterpiece", "hollywood"])
        if claims_cinematic:
            cinematic_claims += 1
            # Must have structured lighting and non-static motion
            cam = s.get("camera_motion") or s.get("camera_choreography") or ""
            light = s.get("lighting") or s.get("lighting_contract") or ""
            is_static = _is_static_camera(cam)
            has_lighting = bool(light.strip()) and light.strip().lower() != "natural"

            if is_static or not has_lighting:
                unsupported_count += 1
                flagged.append(shot_id)

    if cinematic_claims == 0:
        return DimensionScore(score=0.0, reason="No unsupported cinematic claims detected.")

    ratio = unsupported_count / cinematic_claims
    score = min(5.0, ratio * 5.0)

    if ratio > 0.5:
        reason = f"{unsupported_count}/{cinematic_claims} cinematic claims lack camera motion or explicit lighting contracts"
    elif ratio > 0.0:
        reason = f"{unsupported_count}/{cinematic_claims} shots claim cinematic style without full lighting/motion backing"
    else:
        reason = "Cinematic claims are fully backed by camera choreography and lighting contracts"

    return DimensionScore(
        score=round(score, 1),
        reason=reason,
        flagged_shots=flagged,
    )


def score_slideshow_risk(
    scene_plan: Any,
) -> SlideshowRiskReport:
    """Scores slideshow risk across the 6 canonical dimensions and enforces the hard gate.

    Args:
        scene_plan: ScenePlanArtifact instance, or dict with 'shots', or list of shot dicts.

    Returns:
        SlideshowRiskReport with dimension breakdown and hard-gate verdict.
    """
    if hasattr(scene_plan, "shots"):
        raw_shots = scene_plan.shots
    elif isinstance(scene_plan, dict):
        raw_shots = scene_plan.get("shots", [])
    elif isinstance(scene_plan, list):
        raw_shots = scene_plan
    else:
        raw_shots = []

    shots = [_extract_shot_dict(s) for s in raw_shots]

    if not shots:
        return SlideshowRiskReport(
            average_score=5.0,
            verdict="fail",
            passed=False,
            dimensions={},
            hard_reject_reasons=["Scene plan contains 0 shots."],
            recommendations=["Populate storyboard shots with purposeful camera motions."],
        )

    # 1. Evaluate 6 dimensions
    dimensions = {
        "repetition": _score_repetition(shots),
        "decorative_visuals": _score_decorative_visuals(shots),
        "weak_motion": _score_weak_motion(shots),
        "weak_shot_intent": _score_weak_shot_intent(shots),
        "typography_overreliance": _score_typography_overreliance(shots),
        "unsupported_cinematic_claims": _score_unsupported_cinematic_claims(shots),
    }

    avg_score = round(sum(d.score for d in dimensions.values()) / len(dimensions), 2)

    # 2. Hard Gate Evaluations
    hard_reject_reasons: List[str] = []
    recommendations: List[str] = []

    # HARD RULE 1: Average score threshold
    if avg_score >= 4.0:
        hard_reject_reasons.append(
            f"Slideshow risk average score ({avg_score}) exceeds failure threshold (>= 4.0)."
        )

    # HARD RULE 2: Zero-Tolerance Kinetic Rule
    # Any shot with static camera motion AND lacking kinetic subject action is rejected immediately
    for s in shots:
        shot_id = s.get("shot_id", "unnamed_shot")
        cam = s.get("camera_motion") or s.get("camera_choreography") or ""
        desc = s.get("scene_description") or ""
        kinetic = s.get("kinetic_action") or ""

        if _is_static_camera(cam) and not _has_kinetic_subject_action(desc, kinetic):
            hard_reject_reasons.append(
                f"ZERO-TOLERANCE KINETIC REJECTION: Shot '{shot_id}' has static camera ('{cam}') "
                f"and lacks active kinetic subject action verbs. This will render as a static photo slideshow."
            )
            recommendations.append(
                f"Inject dynamic camera choreography (e.g. Orbit, Truck, Pedestal) or active subject kinetics into shot '{shot_id}'."
            )

    # Determine verdict
    if hard_reject_reasons:
        verdict = "rejected"
        passed = False
    elif avg_score < 2.0:
        verdict = "strong"
        passed = True
    elif avg_score < 3.0:
        verdict = "acceptable"
        passed = True
    elif avg_score < 4.0:
        verdict = "revise"
        passed = True  # passes with warnings
        recommendations.append("Consider diversifying camera angles and reducing shot repetition.")
    else:
        verdict = "fail"
        passed = False

    return SlideshowRiskReport(
        average_score=avg_score,
        verdict=verdict,
        passed=passed,
        dimensions=dimensions,
        hard_reject_reasons=hard_reject_reasons,
        recommendations=recommendations,
    )
