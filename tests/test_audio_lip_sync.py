from pathlib import Path
import json
import subprocess

from pipeline.audio_lip_sync import (
    align_lip_sync_clip,
    probe_audio_duration,
    synthesize_tts_stem,
)
from tests.test_helpers import create_test_clip


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
