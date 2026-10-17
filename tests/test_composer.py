from pathlib import Path
import json
import subprocess

from pipeline.composer import compose_master_commercial
from pipeline.schemas import (
    AssetManifestArtifact,
    KeyframeAsset,
    ScriptArtifact,
    ScriptBeat,
)
from pipeline.video_engine import generate_motion_clip_ffmpeg
from pipeline.audio_lip_sync import align_lip_sync_clip, synthesize_tts_stem


def test_compose_master_commercial(tmp_path: Path):
    src_img = Path("assets/characters/kol_main/portrait.png")

    # Generate 2 mini synced clips
    synced_clips = []
    for i in (1, 2):
        clip_p = tmp_path / f"raw_{i}.mp4"
        generate_motion_clip_ffmpeg(src_img, clip_p, duration=1.5, width=540, height=960)
        stem_p = tmp_path / f"voice_{i}.wav"
        synthesize_tts_stem(f"Beat {i} test voice", stem_p)
        synced_p = tmp_path / f"synced_{i}.mp4"
        align_lip_sync_clip(clip_p, stem_p, synced_p)
        synced_clips.append(str(synced_p))

    script = ScriptArtifact(
        campaign_id="test_comp",
        product_name="Test Product",
        target_duration=3.0,
        beats=[
            ScriptBeat(
                scene_id="shot_01",
                beat_type="hook",
                spoken_text="Beat 1 test voice",
                on_screen_text="HOOK TEXT",
                visual_cue="cue 1",
                estimated_duration=1.5,
            ),
            ScriptBeat(
                scene_id="shot_02",
                beat_type="cta",
                spoken_text="Beat 2 test voice",
                on_screen_text="CTA TEXT",
                visual_cue="cue 2",
                estimated_duration=1.5,
            ),
        ],
    )

    manifest = AssetManifestArtifact(
        campaign_id="test_comp",
        keyframes=[],
        synced_video_clips=synced_clips,
    )

    master_path = tmp_path / "test_master.mp4"
    edl = compose_master_commercial(
        script=script,
        manifest=manifest,
        output_master_path=master_path,
        artifacts_dir=tmp_path,
    )

    assert master_path.exists()
    assert (tmp_path / "edit_decisions.json").exists()

    # Check ffprobe
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_name,width,height",
        "-of",
        "json",
        str(master_path),
    ]
    probe = json.loads(subprocess.check_output(cmd).decode("utf-8"))
    streams = probe["streams"]
    assert any(s["codec_name"] == "h264" for s in streams)
    assert any(s["codec_name"] == "aac" for s in streams)
