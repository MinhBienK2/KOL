from pathlib import Path
import json

from pipeline.verification import (
    verify_technical_gate,
    verify_character_consistency_gate,
    verify_continuity_gate,
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
