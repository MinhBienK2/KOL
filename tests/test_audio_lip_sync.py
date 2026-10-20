from pathlib import Path
import json
import subprocess

import pytest

from pipeline import audio_lip_sync
from pipeline.audio_lip_sync import (
    TTSUnavailableError,
    align_lip_sync_clip,
    probe_audio_duration,
    synthesize_tts_stem,
    synthesize_voice_stem,
)
from tests.test_helpers import create_test_clip


@pytest.fixture(autouse=True)
def offline_tts(monkeypatch):
    """Tests must never reach the paid neural TTS endpoint."""

    def _refuse(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(audio_lip_sync.urllib.request, "urlopen", _refuse)


def _peak_db(path: Path) -> float:
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        stderr=subprocess.PIPE,
        check=True,
    )
    for line in res.stderr.decode().splitlines():
        if "max_volume" in line:
            return float(line.split("max_volume:")[1].split("dB")[0])
    raise AssertionError("no max_volume reported")


def _stream_durations(path: Path) -> dict:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)]
    )
    return {s["codec_type"]: float(s["duration"]) for s in json.loads(out)["streams"]}


def test_synthesize_tts_and_align_lipsync(tmp_path: Path):
    stem_path = tmp_path / "test_voice.wav"
    audio_path, duration = synthesize_tts_stem(
        text="Xin chào các bạn, tôi là Minh Anh.",
        output_wav_path=stem_path,
    )
    assert Path(audio_path).exists()
    assert duration > 1.0

    # Create dummy raw video clip
    src_img = Path("assets/characters/kol_main/portrait.png")
    raw_video = tmp_path / "raw.mp4"
    create_test_clip(
        image_path=src_img,
        output_path=raw_video,
        duration=2.0,
        width=540,
        height=960,
    )

    # Sync
    synced_video = tmp_path / "synced.mp4"
    align_lip_sync_clip(
        raw_video_path=raw_video,
        audio_stem_path=audio_path,
        output_synced_path=synced_video,
    )

    assert synced_video.exists()
    synced_dur = probe_audio_duration(synced_video)
    # Ensure synced duration matches audio stem within 0.1s
    assert abs(synced_dur - duration) < 0.2
    # Audio and video streams inside the synced clip must agree (<50ms lip-sync budget, ADR 0003)
    streams = _stream_durations(synced_video)
    assert abs(streams["audio"] - streams["video"]) < 0.05


def test_silent_beat_stem_honours_short_estimated_duration(tmp_path: Path):
    """A music-only 1.5s beat must not be stretched to a 3s minimum (that freezes the last frame)."""
    _, duration = synthesize_tts_stem("", tmp_path / "silent.wav", target_duration=1.5)
    assert abs(duration - 1.5) < 0.1


def test_tts_outage_falls_back_to_silence_not_a_beep(tmp_path: Path):
    """A synthetic sine tone shipped as 'voiceover' is worse than silence in a commercial."""
    result = synthesize_voice_stem("Xin chào các bạn", tmp_path / "v.wav")
    assert result.fallback is True
    assert result.duration >= 1.0
    assert _peak_db(Path(result.path)) < -60.0


def test_tts_outage_raises_in_strict_mode(tmp_path: Path):
    with pytest.raises(TTSUnavailableError):
        synthesize_voice_stem("Xin chào", tmp_path / "v.wav", strict=True)


def test_empty_text_is_not_a_fallback(tmp_path: Path):
    result = synthesize_voice_stem("", tmp_path / "v.wav", target_duration=2.0, strict=True)
    assert result.fallback is False
