"""Speech Intelligibility: ASR client, Vietnamese-aware scoring, stage 6 report and the verification gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import asr, audio_lip_sync
from pipeline.asr import ASRError, speech_match, transcribe
from pipeline.audio_lip_sync import (
    SPEECH_REPORT_FILENAME,
    VoiceStemResult,
    _write_silence,
    produce_all_audio_and_lip_sync,
)
from pipeline.offline import OfflineNetworkError, offline_mode
from pipeline.schemas import AssetManifestArtifact, GateVerificationResult
from pipeline.verification import (
    STATUS_FAILED,
    VERIFICATION_GATE_COUNT,
    speech_intelligibility_gate,
)
from tests.test_offline import _build_workspace

LINE = "Chiếc váy satin lụa Pháp này mềm mại và sang trọng."


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _wav(tmp_path: Path, name: str = "a.wav") -> Path:
    path = tmp_path / name
    _write_silence(path, 0.5)
    return path


# ------------------------------------------------------------------ speech_match


def test_identical_text_scores_zero_and_ok():
    result = speech_match(LINE, LINE)
    assert result == {"wer": 0.0, "cer": 0.0, "cer_unaccented": 0.0, "ok": True}


def test_normalisation_ignores_case_punctuation_unicode_form_and_spacing():
    nfd = __import__("unicodedata").normalize("NFD", LINE.upper().replace(".", "!!"))
    assert speech_match(LINE, "  " + nfd + "  ")["cer"] == 0.0


def test_missing_tone_marks_hurt_cer_but_not_unaccented_cer():
    stripped = "Chiec vay satin lua Phap nay mem mai va sang trong"
    result = speech_match(LINE, stripped)
    assert result["cer"] > 0.2
    assert result["cer_unaccented"] == 0.0
    assert result["wer"] > 0.5


def test_syllable_resegmentation_is_not_penalised_by_cer():
    assert speech_match("xin chào các bạn", "xinchào cácbạn")["cer"] == 0.0


def test_garbage_and_empty_transcripts_fail():
    assert speech_match(LINE, "the quick brown fox jumps over the lazy dog")["ok"] is False
    assert speech_match(LINE, "")["ok"] is False
    assert speech_match(LINE, "")["cer"] == 1.0


def test_threshold_boundary():
    expected = "a" * 20
    assert speech_match(expected, "a" * 12 + "b" * 8)["ok"] is False  # CER 0.40
    assert speech_match(expected, "a" * 13 + "b" * 7)["ok"] is True  # CER 0.35: inclusive
    assert asr.SPEECH_CER_THRESHOLD == 0.35


# ------------------------------------------------------------------ transcribe


def test_transcribe_posts_multipart_to_whisper(tmp_path, monkeypatch):
    seen = {}

    def fake_urlopen(req, *, operation, **kwargs):
        seen.update(url=req.full_url, headers=dict(req.header_items()), body=req.data, operation=operation)
        return _Resp(json.dumps({"text": " Xin chào "}).encode())

    monkeypatch.setattr(asr, "guarded_urlopen", fake_urlopen)
    monkeypatch.setattr(asr.config, "MINIMAX_BASE_URL", "https://gateway.invalid")
    monkeypatch.setattr(asr.config, "MINIMAX_API_KEY", "test-key")

    assert transcribe(_wav(tmp_path), language="vi") == "Xin chào"
    assert seen["url"] == "https://gateway.invalid/v1/audio/transcriptions"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["headers"]["Content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="model"\r\n\r\nwhisper-1' in seen["body"]
    assert b'name="language"\r\n\r\nvi' in seen["body"]
    assert b'name="file"; filename="a.wav"' in seen["body"]
    assert seen["operation"] == "asr.transcribe"


def test_transcribe_wraps_transport_and_format_errors(tmp_path, monkeypatch):
    wav = _wav(tmp_path)
    monkeypatch.setattr(asr, "guarded_urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(ASRError):
        transcribe(wav)
    monkeypatch.setattr(asr, "guarded_urlopen", lambda *a, **k: _Resp(b"<html>"))
    with pytest.raises(ASRError):
        transcribe(wav)
    monkeypatch.setattr(asr, "guarded_urlopen", lambda *a, **k: _Resp(b'{"nope": 1}'))
    with pytest.raises(ASRError):
        transcribe(wav)
    with pytest.raises(ASRError):
        transcribe(tmp_path / "missing.wav")


def test_transcribe_refused_offline_through_the_real_guard(tmp_path, monkeypatch):
    """The real guard (not the conftest stub) must raise OfflineNetworkError before any socket opens."""
    from pipeline.offline import guarded_urlopen

    monkeypatch.setattr(asr, "guarded_urlopen", guarded_urlopen)
    with offline_mode(True), pytest.raises(OfflineNetworkError):
        transcribe(_wav(tmp_path))


# ------------------------------------------------------------------ stage 6


def _fake_api_tts(monkeypatch, placeholder: bool = False):
    def fake(text, output_wav_path, **kwargs):
        _write_silence(Path(output_wav_path), 1.0)
        return VoiceStemResult(
            path=str(output_wav_path),
            duration=1.0,
            engine="silence" if placeholder else "api",
            placeholder=placeholder,
        )

    monkeypatch.setattr(audio_lip_sync, "synthesize_voice_stem", fake)


def _run_stage6(tmp_path, **kwargs):
    ws, script, _ = _build_workspace(tmp_path)
    manifest = AssetManifestArtifact(campaign_id="c", keyframes=[])
    (ws.artifacts_dir / "asset_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    produce_all_audio_and_lip_sync(script=script, manifest=manifest, workspace=ws, tts_mode="api", **kwargs)
    return ws, script, json.loads((ws.artifacts_dir / SPEECH_REPORT_FILENAME).read_text(encoding="utf-8"))


def test_stage6_records_verified_speech_per_shot(tmp_path, monkeypatch):
    _fake_api_tts(monkeypatch)
    heard = []

    def fake_transcribe(path, language="vi"):
        heard.append((Path(path).name, language))
        return "completely unrelated english words"

    monkeypatch.setattr(asr, "transcribe", fake_transcribe)
    ws, script, report = _run_stage6(tmp_path)

    spoken = [b for b in script.beats if b.spoken_text.strip()]
    assert len(heard) == len(spoken) > 0 and all(lang == "vi" for _, lang in heard)
    assert report["threshold"] == asr.SPEECH_CER_THRESHOLD and report["metric"] == "cer"
    verified = [s for s in report["shots"] if s["status"] == "verified"]
    assert len(verified) == len(spoken)
    assert all(s["ok"] is False and s["cer"] > 0.35 and "transcript" in s for s in verified)
    gate = speech_intelligibility_gate(ws.artifacts_dir / SPEECH_REPORT_FILENAME)
    assert not gate.passed and "unintelligible" in gate.error_message


def test_stage6_matching_transcripts_pass_the_gate(tmp_path, monkeypatch):
    _fake_api_tts(monkeypatch)
    ws, script, _ = _build_workspace(tmp_path)
    texts = iter(b.spoken_text for b in script.beats if b.spoken_text.strip())
    monkeypatch.setattr(asr, "transcribe", lambda path, language="vi": next(texts).lower())
    manifest = AssetManifestArtifact(campaign_id="c", keyframes=[])
    produce_all_audio_and_lip_sync(script=script, manifest=manifest, workspace=ws, tts_mode="api")
    gate = speech_intelligibility_gate(ws.artifacts_dir / SPEECH_REPORT_FILENAME)
    assert gate.passed and gate.details["verified_shots"]


def test_stage6_asr_failure_is_unverified_not_fatal(tmp_path, monkeypatch):
    _fake_api_tts(monkeypatch)

    def boom(path, language="vi"):
        raise ASRError("gateway 502")

    monkeypatch.setattr(asr, "transcribe", boom)
    ws, _, report = _run_stage6(tmp_path)
    statuses = {s["status"] for s in report["shots"] if s["expected"].strip()}
    assert statuses == {"unverified"}
    gate = speech_intelligibility_gate(ws.artifacts_dir / SPEECH_REPORT_FILENAME)
    assert gate.passed and gate.details["warnings"]


def test_stage6_skips_placeholder_stems_and_never_calls_asr(tmp_path, monkeypatch):
    _fake_api_tts(monkeypatch, placeholder=True)
    monkeypatch.setattr(asr, "transcribe", lambda *a, **k: pytest.fail("ASR called for a placeholder stem"))
    _, _, report = _run_stage6(tmp_path)
    assert {s["status"] for s in report["shots"]} == {"skipped"}


def test_stage6_verify_speech_false_skips_asr(tmp_path, monkeypatch):
    _fake_api_tts(monkeypatch)
    monkeypatch.setattr(asr, "transcribe", lambda *a, **k: pytest.fail("ASR called although disabled"))
    _, _, report = _run_stage6(tmp_path, verify_speech=False)
    assert {s["status"] for s in report["shots"]} == {"skipped"}


def test_stage6_offline_local_default_never_verifies(tmp_path, monkeypatch):
    monkeypatch.setenv("KOL_OFFLINE", "1")
    monkeypatch.setattr(audio_lip_sync.shutil, "which", lambda name: None)
    monkeypatch.setattr(asr, "transcribe", lambda *a, **k: pytest.fail("ASR called offline"))
    ws, script, _ = _build_workspace(tmp_path)
    manifest = AssetManifestArtifact(campaign_id="c", keyframes=[])
    produce_all_audio_and_lip_sync(script=script, manifest=manifest, workspace=ws)
    report = json.loads((ws.artifacts_dir / SPEECH_REPORT_FILENAME).read_text(encoding="utf-8"))
    assert {s["status"] for s in report["shots"]} == {"skipped"}


# ------------------------------------------------------------------ gate


def _report(tmp_path: Path, shots) -> Path:
    path = tmp_path / "speech_report.json"
    path.write_text(json.dumps({"threshold": 0.35, "shots": shots}), encoding="utf-8")
    return path


def test_gate_missing_report_passes_with_warning(tmp_path):
    gate = speech_intelligibility_gate(tmp_path / "speech_report.json")
    assert isinstance(gate, GateVerificationResult) and gate.passed
    assert gate.gate_name == "speech_intelligibility_gate"
    assert gate.details["found"] is False and gate.details["warnings"]


def test_gate_fails_on_any_verified_shot_not_ok(tmp_path):
    gate = speech_intelligibility_gate(
        _report(
            tmp_path,
            [
                {"shot_id": "shot_01", "status": "verified", "ok": True, "cer": 0.05},
                {"shot_id": "shot_02", "status": "verified", "ok": False, "cer": 0.8},
            ],
        )
    )
    assert not gate.passed and "shot_02" in gate.error_message
    assert [f["shot_id"] for f in gate.details["failed_shots"]] == ["shot_02"]


def test_gate_unverified_and_skipped_pass_with_warning(tmp_path):
    gate = speech_intelligibility_gate(
        _report(
            tmp_path,
            [{"shot_id": "shot_01", "status": "unverified"}, {"shot_id": "shot_02", "status": "skipped"}],
        )
    )
    assert gate.passed and gate.details["unverified_shots"] == ["shot_01"] and gate.details["warnings"]


def test_gate_unreadable_report_fails(tmp_path):
    path = tmp_path / "speech_report.json"
    path.write_text("{not json", encoding="utf-8")
    assert not speech_intelligibility_gate(path).passed
    path.write_text('{"shots": 3}', encoding="utf-8")
    assert not speech_intelligibility_gate(path).passed


def test_failing_speech_gate_makes_master_failed_not_draft(tmp_path, monkeypatch):
    """ADR 0004: only the placeholder audit yields DRAFT; a speech failure is a hard FAILED."""
    from pipeline import verification

    def passing(name):
        return lambda *a, **k: GateVerificationResult(gate_name=name, passed=True, details={"duration_seconds": 5.0})

    for fn in (
        "verify_technical_gate",
        "verify_media_quality_gate",
        "verify_character_sheet_integrity_gate",
        "verify_character_consistency_gate",
        "verify_continuity_gate",
        "verify_slideshow_risk_gate",
        "verify_identity_preflight_gate",
        "verify_prompt_ledger_gate",
    ):
        monkeypatch.setattr(verification, fn, passing(fn))
    monkeypatch.setattr(verification, "load_run_ledger", lambda *a, **k: {})
    monkeypatch.setattr(verification, "_audio_stage_tts_fallback_shots", lambda: [])
    monkeypatch.setattr(verification, "silent_voice_stems", lambda *a, **k: [])
    monkeypatch.setattr(verification, "generate_commercial_thumbnail", lambda *a, **k: str(tmp_path / "t.jpg"))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _report(artifacts, [{"shot_id": "shot_01", "status": "verified", "ok": False, "cer": 0.9}])
    master = tmp_path / "master.mp4"
    master.write_bytes(b"\0")

    report = verification.run_all_verification_gates(master_video_path=master, artifacts_dir=artifacts)

    assert report.overall_status == STATUS_FAILED
    assert len(report.verification_gates) == VERIFICATION_GATE_COUNT
    assert report.verification_gates[-1].gate_name == "speech_intelligibility_gate"
