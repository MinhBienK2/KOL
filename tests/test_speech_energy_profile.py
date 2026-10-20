"""Speech-energy profiling must use an absolute silence floor, not only a relative threshold."""

import subprocess
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import audio_lip_sync, telemetry
from pipeline.lip_sync_engine import SILENCE_FLOOR_DBFS, analyze_speech_energy


def _ffmpeg(args: list[str]) -> None:
    subprocess.check_call(["ffmpeg", "-y", "-loglevel", "error", *args])


def _silent_wav(path: Path, duration: float = 4.5) -> Path:
    _ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(duration), "-ar", "48000", str(path)])
    return path


def _burst_wav(path: Path, *, bursts: int = 3, burst_s: float = 0.6, gap_s: float = 0.4) -> Path:
    """Sine bursts (-6 dBFS) separated by digital-silence gaps."""
    total = bursts * burst_s + (bursts - 1) * gap_s
    enable = "+".join(
        f"between(t,{i * (burst_s + gap_s):.3f},{i * (burst_s + gap_s) + burst_s:.3f})" for i in range(bursts)
    )
    _ffmpeg(
        [
            "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={total:.3f}",
            "-af", f"volume=0.5,volume=enable='not({enable})':volume=0",
            "-ac", "2", str(path),
        ]
    )
    return path


def test_digitally_silent_stem_profiles_as_zero_speech(tmp_path):
    prof = analyze_speech_energy(_silent_wav(tmp_path / "s.wav"))
    assert prof.speaking_duration_ratio == 0.0
    assert prof.speech_bursts == []
    assert prof.silence_pauses_count == 0
    assert prof.is_silent is True
    assert prof.duration_seconds == pytest.approx(4.5, abs=0.05)


def test_near_silent_noise_below_floor_is_still_silent(tmp_path):
    p = tmp_path / "hiss.wav"
    # White noise at -70 dBFS: far under the -50 dBFS floor, but nonzero so a relative threshold would pass it.
    _ffmpeg(["-f", "lavfi", "-i", "anoisesrc=r=48000:amplitude=0.0003:d=3", "-ac", "2", str(p)])
    prof = analyze_speech_energy(p)
    assert prof.is_silent is True
    assert prof.speaking_duration_ratio == 0.0
    assert prof.speech_bursts == []


def test_bursts_with_gaps_profile_sensibly(tmp_path):
    prof = analyze_speech_energy(_burst_wav(tmp_path / "b.wav", bursts=3))
    assert prof.is_silent is False
    assert len(prof.speech_bursts) == 3
    assert prof.silence_pauses_count == 2
    # 1.8s of tone in 2.6s total.
    assert 0.55 < prof.speaking_duration_ratio < 0.85
    first_start, first_end = prof.speech_bursts[0]
    assert first_start == pytest.approx(0.0, abs=0.1)
    assert first_end == pytest.approx(0.6, abs=0.1)


def test_amplitude_modulated_noise_is_not_full_ratio(tmp_path):
    p = tmp_path / "am.wav"
    # Noise gated on for 0.5s of every 1s.
    _ffmpeg(
        [
            "-f", "lavfi", "-i", "anoisesrc=r=48000:amplitude=0.3:d=4",
            "-af", "volume=enable='gte(mod(t,1),0.5)':volume=0", "-ac", "2", str(p),
        ]
    )
    prof = analyze_speech_energy(p)
    assert prof.is_silent is False
    assert len(prof.speech_bursts) == 4
    assert 0.35 < prof.speaking_duration_ratio < 0.65


def test_quiet_but_audible_speech_above_floor_is_speech(tmp_path):
    p = tmp_path / "quiet.wav"
    # ~-31 dBFS RMS tone (ffmpeg sine defaults to 0.125 amplitude): quiet yet well above the floor.
    _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=2", "-af", "volume=0.3", str(p)])
    prof = analyze_speech_energy(p)
    assert prof.is_silent is False
    assert prof.speaking_duration_ratio == 1.0


def test_floor_constant_is_minus_50_dbfs():
    assert SILENCE_FLOOR_DBFS == -50.0


def test_silent_stem_on_spoken_beat_emits_telemetry_warning(tmp_path):
    notes: list[tuple[str, dict]] = []
    logs: list[tuple[str, str]] = []
    silent = _silent_wav(tmp_path / "voice_shot_01.wav")
    with patch.object(telemetry, "note", lambda text, **kw: notes.append((text, kw))), patch.object(
        telemetry, "log", lambda text, level="info", stage=None: logs.append((level, text))
    ):
        audio_lip_sync._profile_stem_speech("shot_01", silent, has_spoken_text=True, mix_mode="sync_mouth")
    assert any(level == "warning" and "shot_01" in text and "silent" in text.lower() for level, text in logs)
    assert any(kw.get("silent_stem") is True for _, kw in notes)


def test_silent_stem_on_beat_without_text_is_not_a_warning(tmp_path):
    logs: list[tuple[str, str]] = []
    silent = _silent_wav(tmp_path / "voice_shot_02.wav")
    with patch.object(telemetry, "note", lambda *a, **k: None), patch.object(
        telemetry, "log", lambda text, level="info", stage=None: logs.append((level, text))
    ):
        audio_lip_sync._profile_stem_speech("shot_02", silent, has_spoken_text=False, mix_mode="pure_bgm")
    assert not logs


def test_audible_stem_on_spoken_beat_is_not_a_warning(tmp_path):
    logs: list[tuple[str, str]] = []
    wav = _burst_wav(tmp_path / "b.wav")
    with patch.object(telemetry, "note", lambda *a, **k: None), patch.object(
        telemetry, "log", lambda text, level="info", stage=None: logs.append((level, text))
    ):
        audio_lip_sync._profile_stem_speech("shot_03", wav, has_spoken_text=True, mix_mode="sync_mouth")
    assert not logs
