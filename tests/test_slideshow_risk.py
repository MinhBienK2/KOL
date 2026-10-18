import pytest

from pipeline.slideshow_risk import (
    score_slideshow_risk,
    SlideshowRiskReport,
)


def test_slideshow_risk_strong_cinematic_plan():
    plan = {
        "campaign_id": "test_strong",
        "shots": [
            {
                "shot_id": "shot_01",
                "scene_id": "shot_01_hook",
                "shot_type": "Close-up with presenter reaction",
                "camera_motion": "Slow smooth push-in",
                "lighting": "3-point studio lighting 5600K",
                "scene_description": "Presenter touching cold mug and shaking head with disappointment",
                "prompt_6part": "Presenter touching cold mug, cinematic 5600K lighting",
                "estimated_duration": 3.5,
            },
            {
                "shot_id": "shot_02",
                "scene_id": "shot_02_pain",
                "shot_type": "Over-the-shoulder POV",
                "camera_motion": "Subtle handheld tracking tilt",
                "lighting": "Contrasty office daylight",
                "scene_description": "Water droplets drip onto papers, presenter wiping droplets with tissue",
                "prompt_6part": "Droplets drip, presenter wiping droplets",
                "estimated_duration": 4.5,
            },
            {
                "shot_id": "shot_03",
                "scene_id": "shot_03_solution",
                "shot_type": "Medium Glamour Product Shot",
                "camera_motion": "Cinematic slow arc orbit with shallow DOF",
                "lighting": "Warm luxury backlight, soft beauty key light",
                "scene_description": "Presenter holding Lumina mug, tapping LED lid, drinking and smiling with satisfaction",
                "prompt_6part": "Holding mug, tapping lid, taking sip, luxury lighting",
                "estimated_duration": 5.0,
            },
            {
                "shot_id": "shot_04",
                "scene_id": "shot_04_cta",
                "shot_type": "Medium Presenter CTA Shot",
                "camera_motion": "Slow forward push-in",
                "lighting": "Bright radiant commercial key lighting",
                "scene_description": "Presenter standing upright, holding up mug to camera, gesturing to link below",
                "prompt_6part": "Presenter holding up mug and gesturing to link",
                "estimated_duration": 4.0,
            },
        ],
    }

    report = score_slideshow_risk(plan)
    assert report.passed is True
    assert report.verdict == "strong"
    assert report.average_score < 2.0
    assert len(report.hard_reject_reasons) == 0


def test_slideshow_risk_zero_tolerance_kinetic_rejection():
    # Shot 2 has static camera motion AND no kinetic verbs
    bad_plan = {
        "campaign_id": "test_kinetic_fail",
        "shots": [
            {
                "shot_id": "shot_01",
                "scene_id": "shot_01_hook",
                "shot_type": "Close-up",
                "camera_motion": "Dolly push-in",
                "lighting": "Studio lighting",
                "scene_description": "Presenter smiling and drinking coffee",
                "prompt_6part": "Presenter smiling and drinking coffee",
                "estimated_duration": 3.0,
            },
            {
                "shot_id": "shot_02",
                "scene_id": "shot_02_pain",
                "shot_type": "Static Slide",
                "camera_motion": "static fixed tripod",
                "lighting": "flat natural light",
                "scene_description": "Product still life",
                "prompt_6part": "Product still life photo",
                "estimated_duration": 4.0,
            },
        ],
    }

    report = score_slideshow_risk(bad_plan)
    assert report.passed is False
    assert report.verdict == "rejected"
    assert any("ZERO-TOLERANCE KINETIC REJECTION" in r for r in report.hard_reject_reasons)
    assert any("shot_02" in r for r in report.hard_reject_reasons)


def test_slideshow_risk_typography_overreliance():
    text_plan = {
        "campaign_id": "test_text_heavy",
        "shots": [
            {
                "shot_id": "shot_01",
                "scene_id": "shot_01_hook",
                "shot_type": "Text Card",
                "camera_motion": "Push-in",
                "lighting": "Studio",
                "scene_description": "Slide with bullet points and stat card",
                "prompt_6part": "Slide with bullet points",
                "estimated_duration": 3.0,
            },
            {
                "shot_id": "shot_02",
                "scene_id": "shot_02_pain",
                "shot_type": "Text Card",
                "camera_motion": "Pan",
                "lighting": "Studio",
                "scene_description": "Bullet list of features",
                "prompt_6part": "Bullet list of features",
                "estimated_duration": 3.0,
            },
            {
                "shot_id": "shot_03",
                "scene_id": "shot_03_cta",
                "shot_type": "Stat Card",
                "camera_motion": "Tilt",
                "lighting": "Studio",
                "scene_description": "Stat card with discount code",
                "prompt_6part": "Stat card",
                "estimated_duration": 3.0,
            },
        ],
    }

    report = score_slideshow_risk(text_plan)
    typography_dim = report.dimensions["typography_overreliance"]
    assert typography_dim.score >= 4.0
    assert "text cards" in typography_dim.reason


def test_slideshow_risk_unsupported_cinematic_claims():
    fake_cinematic_plan = {
        "campaign_id": "test_fake_cinematic",
        "shots": [
            {
                "shot_id": "shot_01",
                "scene_id": "shot_01_hook",
                "shot_type": "Masterpiece",
                "camera_motion": "static fixed",
                "lighting": "natural",
                "scene_description": "A presenter in an office",
                "prompt_6part": "Ultra cinematic 8k hollywood masterpiece luxury commercial",
                "estimated_duration": 4.0,
            }
        ],
    }

    report = score_slideshow_risk(fake_cinematic_plan)
    cinematic_dim = report.dimensions["unsupported_cinematic_claims"]
    assert cinematic_dim.score >= 4.0
    assert "lack camera motion" in cinematic_dim.reason or "without full lighting" in cinematic_dim.reason
