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


# --------------------------------------------------------------------------------------
# Round 2: audio_mix_report loudness authority, identity pre-flight audit, placeholder audit
# --------------------------------------------------------------------------------------
import os

from pipeline.verification import (
    STATUS_DRAFT,
    load_run_ledger,
    silent_voice_stems,
    verify_identity_preflight_gate,
    verify_prompt_ledger_gate,
)


def _write_report(path: Path, newer_than: Path, *, output_lufs: float, compliant: bool, age: float = 5.0) -> Path:
    path.write_text(json.dumps({"output_lufs": output_lufs, "compliant": compliant, "target_lufs": -14.0}))
    stamp = newer_than.stat().st_mtime + age
    os.utime(path, (stamp, stamp))
    return path


@needs_ffmpeg
def test_media_quality_gate_uses_fresh_mix_report_verdict(tmp_path: Path):
    clip = _make_clip(tmp_path / "good.mp4", "testsrc2", _SPEECH_LEVEL)
    measured = verify_media_quality_gate(clip).details["integrated_lufs"]

    ok = _write_report(tmp_path / "ok.json", clip, output_lufs=measured, compliant=True)
    gate = verify_media_quality_gate(clip, ok)
    assert gate.passed is True, gate.error_message
    assert gate.details["loudness_source"] == "audio_mix_report"

    bad = _write_report(tmp_path / "bad.json", clip, output_lufs=measured, compliant=False)
    gate = verify_media_quality_gate(clip, bad)
    assert gate.passed is False
    assert "audio_mix_report" in gate.error_message and "not compliant" in gate.error_message


@needs_ffmpeg
def test_media_quality_gate_rejects_mix_report_that_does_not_describe_the_master(tmp_path: Path):
    clip = _make_clip(tmp_path / "good.mp4", "testsrc2", _SPEECH_LEVEL)
    measured = verify_media_quality_gate(clip).details["integrated_lufs"]
    liar = _write_report(tmp_path / "liar.json", clip, output_lufs=measured - 4.0, compliant=True)
    gate = verify_media_quality_gate(clip, liar)
    assert gate.passed is False
    assert "does not describe this master" in gate.error_message


@needs_ffmpeg
def test_media_quality_gate_ignores_stale_or_malformed_mix_report(tmp_path: Path):
    clip = _make_clip(tmp_path / "good.mp4", "testsrc2", _SPEECH_LEVEL)
    stale = _write_report(tmp_path / "stale.json", clip, output_lufs=-30.0, compliant=False, age=-60.0)
    gate = verify_media_quality_gate(clip, stale)
    assert gate.details["loudness_source"] == "measured" and gate.passed is True

    junk = tmp_path / "junk.json"
    junk.write_text("{not json")
    assert verify_media_quality_gate(clip, junk).details["loudness_source"] == "measured"


def test_identity_preflight_gate_missing_report_warns_but_passes(tmp_path: Path):
    gate = verify_identity_preflight_gate(tmp_path / "identity_preflight.json")
    assert gate.passed is True
    assert gate.details["found"] is False and gate.details["warnings"]


def test_identity_preflight_gate_surfaces_warnings_without_failing(tmp_path: Path):
    path = tmp_path / "identity_preflight.json"
    path.write_text(json.dumps({
        "ok": True, "assets": {"face_anchor": {}}, "errors": [],
        "warnings": [{"asset": "character_sheet", "issue": "long edge 900px below minimum resolution 1024px"}],
    }))
    gate = verify_identity_preflight_gate(path)
    assert gate.passed is True
    assert gate.details["warnings"] == ["character_sheet: long edge 900px below minimum resolution 1024px"]


def test_identity_preflight_gate_fails_on_errors_or_unreadable_report(tmp_path: Path):
    path = tmp_path / "identity_preflight.json"
    path.write_text(json.dumps({"ok": False, "errors": [{"asset": "face_anchor", "issue": "missing"}], "warnings": []}))
    gate = verify_identity_preflight_gate(path)
    assert gate.passed is False and "face_anchor: missing" in gate.error_message

    path.write_text("[[")
    assert verify_identity_preflight_gate(path).passed is False


def test_prompt_ledger_gate_passes_clean_ledger():
    ledger = {"shot_01": {"mode": "I2V"}, "shot_02": {"mode": "R2V", "degraded_from": None}}
    gate = verify_prompt_ledger_gate(ledger)
    assert gate.passed is True and gate.details["placeholder_count"] == 0


def test_prompt_ledger_gate_flags_degraded_placeholder_and_tts_fallback_shots():
    ledger = {
        "shot_01": {"mode": "I2V", "degraded_from": "R2V"},
        "shot_02": {"mode": "local_ffmpeg"},
        "shot_03": {"mode": "I2V", "tts_fallback": True},
        "shot_04": {"mode": "T2V"},
    }
    gate = verify_prompt_ledger_gate(ledger, tts_fallback_shots=["shot_04"])
    assert gate.passed is False
    flagged = gate.details["flagged_shots"]
    assert set(flagged) == {"shot_01", "shot_02", "shot_03", "shot_04"}
    assert flagged["shot_01"] == ["degraded_from=R2V"]
    assert flagged["shot_02"] == ["mode=local_ffmpeg"]


def test_load_run_ledger_reads_file_and_prefers_live_telemetry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run = tmp_path / "run"
    (run / "artifacts").mkdir(parents=True)
    (run / "prompt_ledger.json").write_text(json.dumps({"shot_01": {"mode": "I2V"}, "shot_02": {"mode": "I2V"}}))
    assert load_run_ledger(run / "artifacts")["shot_02"]["mode"] == "I2V"

    class FakeRecorder:
        def snapshot(self):
            return {"prompts": {"shot_02": {"mode": "I2V", "degraded_from": "R2V"}}}

    monkeypatch.setattr(verification.telemetry, "current", lambda: FakeRecorder())
    assert load_run_ledger(run / "artifacts")["shot_02"]["degraded_from"] == "R2V"


@needs_ffmpeg
def test_silent_voice_stems_flags_only_spoken_beats_with_digital_silence(tmp_path: Path):
    def stem(name: str, src: str) -> str:
        out = tmp_path / name
        subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, str(out)])
        return str(out)

    stems = [
        stem("a.wav", "sine=f=300:d=1"),
        stem("b.wav", "anullsrc=r=48000:cl=stereo:d=1"),
        stem("c.wav", "anullsrc=r=48000:cl=stereo:d=1"),
    ]
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"beats": [{"spoken_text": "hi"}, {"spoken_text": "hello"}, {"spoken_text": ""}]}))
    manifest = tmp_path / "asset_manifest.json"
    manifest.write_text(json.dumps({"audio_stems": stems}))
    assert silent_voice_stems(script, manifest) == ["shot_02"]


@needs_ffmpeg
def test_run_all_gates_marks_master_with_placeholders_as_draft_and_withholds_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    master = _make_clip(tmp_path / "master.mp4", "testsrc2", _SPEECH_LEVEL)
    artifacts = tmp_path / "run" / "artifacts"
    artifacts.mkdir(parents=True)
    (tmp_path / "run" / "prompt_ledger.json").write_text(
        json.dumps({"shot_01": {"mode": "I2V", "degraded_from": "R2V"}})
    )
    (artifacts / "publish_log.json").write_text("{}")  # stale log from an earlier PASSED run
    _stub_gates(monkeypatch, technical_passes=True)

    report = run_all_verification_gates(master_video_path=master, artifacts_dir=artifacts)

    assert report.overall_status == STATUS_DRAFT == "DRAFT"
    names = [g.gate_name for g in report.verification_gates]
    assert "identity_preflight_gate" in names and "prompt_ledger_audit_gate" in names
    assert (artifacts / "render_report.json").exists()
    assert not (artifacts / "publish_log.json").exists()


@needs_ffmpeg
def test_run_all_gates_hard_failure_outranks_draft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = _make_clip(tmp_path / "master.mp4", "testsrc2", _SPEECH_LEVEL)
    artifacts = tmp_path / "run" / "artifacts"
    artifacts.mkdir(parents=True)
    (tmp_path / "run" / "prompt_ledger.json").write_text(json.dumps({"shot_01": {"mode": "LOCAL_FFMPEG"}}))
    _stub_gates(monkeypatch, technical_passes=False)
    assert run_all_verification_gates(master_video_path=master, artifacts_dir=artifacts).overall_status == "FAILED"
