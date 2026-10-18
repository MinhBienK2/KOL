from pathlib import Path
import json

from pipeline.verification import (
    verify_technical_gate,
    verify_character_consistency_gate,
    verify_continuity_gate,
    verify_slideshow_risk_gate,
    run_all_verification_gates,
)


def test_verify_technical_gate_existing():
    master = Path("output/final_commercial_master.mp4")
    if master.exists():
        gate = verify_technical_gate(master)
        assert gate.passed is True
        assert gate.details["width"] == 1080
        assert gate.details["height"] == 1920
        assert gate.details["video_codec"] == "h264"
        assert gate.details["audio_codec"] == "aac"


def test_verify_technical_gate_missing(tmp_path: Path):
    missing = tmp_path / "non_existent.mp4"
    gate = verify_technical_gate(missing)
    assert gate.passed is False
    assert "does not exist" in (gate.error_message or "")


def test_verify_character_consistency_gate():
    manifest_p = Path("output/artifacts/asset_manifest.json")
    if manifest_p.exists():
        gate = verify_character_consistency_gate(manifest_p)
        assert gate.passed is True
        assert gate.details["watermark_cleaned"] is True


def test_verify_continuity_gate():
    script_p = Path("output/artifacts/script.json")
    manifest_p = Path("output/artifacts/asset_manifest.json")
    if script_p.exists() and manifest_p.exists():
        gate = verify_continuity_gate(script_p, manifest_p)
        assert gate.passed is True


def test_verify_slideshow_risk_gate_existing():
    plan_p = Path("output/artifacts/scene_plan.json")
    if plan_p.exists():
        gate = verify_slideshow_risk_gate(plan_p)
        assert gate.passed is True
        assert gate.details["average_score"] < 2.0
        assert gate.details["verdict"] == "strong"


def test_verify_slideshow_risk_gate_rejects_static_slideshow(tmp_path: Path):
    bad_plan = {
        "campaign_id": "bad_plan_test",
        "shots": [
            {
                "shot_id": "shot_01",
                "scene_id": "shot_01_hook",
                "shot_type": "Static Slide",
                "camera_motion": "static fixed tripod",
                "lighting": "natural",
                "scene_description": "A mug stands on table",
                "prompt_6part": "A mug stands on table",
                "estimated_duration": 4.0,
            }
        ]
    }
    plan_file = tmp_path / "bad_plan.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(bad_plan, f)

    gate = verify_slideshow_risk_gate(plan_file)
    assert gate.passed is False
    assert "ZERO-TOLERANCE KINETIC REJECTION" in (gate.error_message or "")


def test_verify_slideshow_risk_gate_missing(tmp_path: Path):
    missing = tmp_path / "non_existent.json"
    gate = verify_slideshow_risk_gate(missing)
    assert gate.passed is False
    assert "not found" in (gate.error_message or "")
