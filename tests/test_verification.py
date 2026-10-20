from pathlib import Path
import json

from pipeline.verification import (
    verify_technical_gate,
    verify_character_sheet_integrity_gate,
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



def test_verify_character_sheet_integrity_gate():
    gate = verify_character_sheet_integrity_gate()
    assert gate.passed is True
    assert gate.details["has_face_anchor"] is True
    assert gate.details["identities_verified"] > 0

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


# ---------------------------------------------------------------------------
# Media Quality Gate (black / frozen frames / loudness) and release packaging
# ---------------------------------------------------------------------------

import shutil
import subprocess

import pytest

from pipeline import verification
from pipeline.schemas import GateVerificationResult
from pipeline.verification import (
    VERIFICATION_GATE_COUNT,
    publish_thumbnail_timestamp,
    verify_media_quality_gate,
)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _make_clip(path: Path, video_src: str, audio_src: str | None, duration: float = 4.0, vf: str | None = None) -> Path:
    sep = ":" if "=" in video_src else "="
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{video_src}{sep}s=160x284:r=24:d={duration}"]
    if audio_src is not None:
        cmd += ["-f", "lavfi", "-i", audio_src]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio_src is not None:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd.append(str(path))
    subprocess.check_call(cmd)
    return path


# sine default amplitude is -18 dBFS (~ -21 LUFS); +7 dB lands on the -14 LUFS delivery target.
_SPEECH_LEVEL = "sine=f=440:d=4,volume=7dB"


@needs_ffmpeg
def test_media_quality_gate_passes_moving_picture_at_target_loudness(tmp_path: Path):
    clip = _make_clip(tmp_path / "good.mp4", "testsrc2", _SPEECH_LEVEL)
    gate = verify_media_quality_gate(clip)
    assert gate.gate_name == "media_quality_gate"
    assert gate.passed is True, gate.error_message
    assert gate.details["black_seconds"] == 0
    assert gate.details["frozen_seconds"] == 0
    assert -17.0 < gate.details["integrated_lufs"] < -11.0


@needs_ffmpeg
def test_media_quality_gate_rejects_black_picture(tmp_path: Path):
    clip = _make_clip(tmp_path / "black.mp4", "color=c=black", _SPEECH_LEVEL)
    gate = verify_media_quality_gate(clip)
    assert gate.passed is False
    assert "black" in (gate.error_message or "").lower()
    assert gate.details["black_seconds"] >= 3.5


@needs_ffmpeg
def test_media_quality_gate_rejects_frozen_picture_including_trailing_freeze(tmp_path: Path):
    clip = _make_clip(tmp_path / "frozen.mp4", "color=c=red", _SPEECH_LEVEL)
    gate = verify_media_quality_gate(clip)
    assert gate.passed is False
    assert "frozen" in (gate.error_message or "").lower()
    assert gate.details["frozen_seconds"] >= 3.5


@needs_ffmpeg
def test_media_quality_gate_rejects_clips_held_on_still_frames(tmp_path: Path):
    """No single hold reaches 2s, but 1.5s of a 4.5s film is a stalled still (composer pad-with-clone)."""
    clip = _make_clip(
        tmp_path / "held.mp4", "testsrc2", "sine=f=440:d=4.5,volume=7dB", duration=3.0,
        vf="tpad=stop_mode=clone:stop_duration=1.5",
    )
    gate = verify_media_quality_gate(clip)
    assert gate.passed is False
    assert gate.details["longest_frozen_seconds"] < 2.0
    assert "runtime" in (gate.error_message or "")


@needs_ffmpeg
def test_media_quality_gate_rejects_silent_master(tmp_path: Path):
    clip = _make_clip(tmp_path / "silent.mp4", "testsrc2", "anullsrc=r=48000:cl=stereo")
    gate = verify_media_quality_gate(clip)
    assert gate.passed is False
    assert "loudness" in (gate.error_message or "").lower()


@needs_ffmpeg
def test_media_quality_gate_rejects_off_target_loudness(tmp_path: Path):
    clip = _make_clip(tmp_path / "quiet.mp4", "testsrc2", "sine=f=440:d=4")  # ~ -21 LUFS
    gate = verify_media_quality_gate(clip)
    assert gate.passed is False
    assert "loudness" in (gate.error_message or "").lower()


def test_media_quality_gate_missing_file(tmp_path: Path):
    gate = verify_media_quality_gate(tmp_path / "nope.mp4")
    assert gate.passed is False
    assert "does not exist" in (gate.error_message or "")


def test_publish_thumbnail_timestamp_is_never_negative():
    assert publish_thumbnail_timestamp(0.4) == 0.0
    assert publish_thumbnail_timestamp(10.0) == 9.0
    assert publish_thumbnail_timestamp(120.0) == 18.0


def _stub_gates(monkeypatch: pytest.MonkeyPatch, *, technical_passes: bool, duration: float = 4.0) -> None:
    def ok(name: str, passed: bool = True, **details):
        return lambda *a, **k: GateVerificationResult(
            gate_name=name, passed=passed, details=details, error_message=None if passed else f"{name} broke"
        )

    monkeypatch.setattr(
        verification,
        "verify_technical_gate",
        ok(
            "technical_integrity_gate",
            technical_passes,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            duration_seconds=duration,
        ),
    )
    monkeypatch.setattr(verification, "verify_media_quality_gate", ok("media_quality_gate"))
    monkeypatch.setattr(verification, "verify_character_sheet_integrity_gate", ok("character_sheet_integrity_gate"))
    monkeypatch.setattr(verification, "verify_character_consistency_gate", ok("character_consistency_gate"))
    monkeypatch.setattr(verification, "verify_continuity_gate", ok("continuity_gate"))
    monkeypatch.setattr(verification, "verify_slideshow_risk_gate", ok("slideshow_risk_gate"))


@needs_ffmpeg
def test_run_all_gates_runs_every_gate_and_publishes_on_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = _make_clip(tmp_path / "master.mp4", "testsrc2", _SPEECH_LEVEL)
    artifacts = tmp_path / "artifacts"
    _stub_gates(monkeypatch, technical_passes=True)

    report = run_all_verification_gates(master_video_path=master, artifacts_dir=artifacts)

    assert report.overall_status == "PASSED"
    assert len(report.verification_gates) == VERIFICATION_GATE_COUNT
    assert "media_quality_gate" in [g.gate_name for g in report.verification_gates]
    assert (artifacts / "render_report.json").exists()
    assert (artifacts / "publish_log.json").exists()


@needs_ffmpeg
def test_run_all_gates_does_not_publish_a_failed_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ADR 0004: no defective master reaches the publication catalog (and stale logs are retracted)."""
    master = _make_clip(tmp_path / "master.mp4", "testsrc2", _SPEECH_LEVEL)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "publish_log.json").write_text("{}", encoding="utf-8")  # left over from an earlier PASSED run
    _stub_gates(monkeypatch, technical_passes=False)

    report = run_all_verification_gates(master_video_path=master, artifacts_dir=artifacts)

    assert report.overall_status == "FAILED"
    assert (artifacts / "render_report.json").exists()
    assert not (artifacts / "publish_log.json").exists()


@needs_ffmpeg
def test_run_all_gates_survives_sub_second_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = _make_clip(tmp_path / "tiny.mp4", "testsrc2", "sine=f=440:d=0.5", duration=0.5)
    _stub_gates(monkeypatch, technical_passes=True, duration=0.5)
    report = run_all_verification_gates(master_video_path=master, artifacts_dir=tmp_path / "artifacts")
    assert report.overall_status == "PASSED"
