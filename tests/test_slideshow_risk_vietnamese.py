"""Slideshow Risk Gate must score Vietnamese scripts fairly (stage 2-3 review)."""

from pipeline.slideshow_risk import (
    _has_kinetic_subject_action,
    _score_weak_shot_intent,
    score_slideshow_risk,
)


def test_vietnamese_kinetic_verbs_are_detected():
    assert _has_kinetic_subject_action("Minh Anh chạm nhẹ nút cảm ứng trên nắp")
    assert _has_kinetic_subject_action("KOL bước sải chân tự tin trên phố")
    assert not _has_kinetic_subject_action("Một chiếc ly đặt trên bàn")


def test_beat_type_scene_ids_count_as_commercial_intent():
    beats = ["hook", "unboxing", "macro_detail", "texture_macro", "social_proof", "styling_versatility", "cta"]
    shots = [{"shot_id": f"shot_{i:02d}", "scene_id": f"shot_{i:02d}_{b}"} for i, b in enumerate(beats, start=1)]
    result = _score_weak_shot_intent(shots)
    assert result.score == 0.0, result.reason


def test_explicit_shot_intent_is_preferred_over_scene_id():
    shots = [{"shot_id": "shot_01", "scene_id": "shot_01_xyz", "shot_intent": "reveal: show the hero product"}]
    assert _score_weak_shot_intent(shots).score == 0.0


def test_zero_tolerance_rule_respects_vietnamese_action():
    static_but_acting = {
        "shot_id": "shot_01",
        "scene_id": "shot_01_hook",
        "shot_intent": "hook",
        "camera_motion": "static",
        "scene_description": "KOL giơ cao ly và xoay nhẹ",
        "prompt_6part": "x",
        "style_constraints": "",
        "lighting": "studio_3point",
        "estimated_duration": 3.0,
    }
    report = score_slideshow_risk([static_but_acting])
    assert not report.hard_reject_reasons


def test_static_camera_without_action_is_still_rejected():
    dead = {
        "shot_id": "shot_01",
        "scene_id": "shot_01_hook",
        "camera_motion": "static",
        "scene_description": "Một chiếc ly đặt trên bàn",
        "prompt_6part": "x",
        "estimated_duration": 3.0,
    }
    report = score_slideshow_risk([dead])
    assert report.verdict == "rejected"
