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
from tests.test_helpers import create_test_clip
from pipeline.audio_lip_sync import align_lip_sync_clip, synthesize_tts_stem


def test_compose_master_commercial(tmp_path: Path):
    src_img = Path("assets/characters/kol_main/portrait.png")

    # Generate 2 mini synced clips
    synced_clips = []
    for i in (1, 2):
        clip_p = tmp_path / f"raw_{i}.mp4"
        create_test_clip(src_img, clip_p, duration=1.5, width=540, height=960)
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


# --------------------------------------------------------------------------------------
# Timing: clips are trimmed to the beat, never padded with frozen frames
# --------------------------------------------------------------------------------------
import re

import pytest

from pipeline.composer import DUCKING_FILTER, BGM_DUCKING_ATTENUATION_DB


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _moving_clip(path: Path, seconds: float) -> str:
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=size=540x960:rate=24:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))
    return str(path)


def _voice_stem(path: Path, seconds: float) -> str:
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}:sample_rate=48000",
            "-af", "volume=0.5,aformat=channel_layouts=stereo", str(path))
    return str(path)


def _duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    )
    return float(out.decode().strip())


def _frozen_seconds(path: Path) -> float:
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "freezedetect=n=-60dB:d=0.25", "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return sum(float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", res.stderr))


def _script(estimates):
    return ScriptArtifact(
        campaign_id="timing",
        product_name="P",
        target_duration=sum(estimates),
        beats=[
            ScriptBeat(
                scene_id=f"shot_{i + 1:02d}", beat_type="hook", spoken_text="x", on_screen_text="",
                visual_cue="c", estimated_duration=e,
            )
            for i, e in enumerate(estimates)
        ],
    )


def _compose(tmp_path: Path, estimates, clip_secs, voice_secs):
    raw, stems = [], []
    for i, (c, v) in enumerate(zip(clip_secs, voice_secs), start=1):
        raw.append(_moving_clip(tmp_path / f"shot_{i:02d}.mp4", c))
        stems.append(_voice_stem(tmp_path / f"voice_shot_{i:02d}.wav", v))
    manifest = AssetManifestArtifact(
        campaign_id="timing", keyframes=[], raw_video_clips=raw, audio_stems=stems, synced_video_clips=[],
    )
    master = tmp_path / "master.mp4"
    edl = compose_master_commercial(
        script=_script(estimates), manifest=manifest, output_master_path=master,
        artifacts_dir=tmp_path, include_captions=False,
    )
    return master, edl, json.loads((tmp_path / "edit_decisions.json").read_text())


def test_six_second_clips_are_trimmed_to_beat_runtime_without_freezing(tmp_path: Path):
    master, _edl, doc = _compose(tmp_path, [2.0, 3.0], clip_secs=[6.0, 6.0], voice_secs=[1.5, 2.5])
    assert _duration(master) == pytest.approx(5.0, abs=0.25)
    assert _frozen_seconds(master) == 0.0
    shots = doc["shots"]
    assert [s["shot_id"] for s in shots] == ["shot_01", "shot_02"]
    assert shots[0]["action"] == "trim"
    assert shots[0]["target_seconds"] == pytest.approx(2.0)
    assert shots[0]["in_point"] == 0.0 and shots[0]["out_point"] == pytest.approx(2.0)
    assert shots[1]["timeline_start"] == pytest.approx(2.0)
    assert shots[1]["timeline_end"] == pytest.approx(5.0)


def test_voice_longer_than_beat_extends_shot_with_real_motion_not_frozen_frames(tmp_path: Path):
    master, _edl, doc = _compose(tmp_path, [1.5], clip_secs=[6.0], voice_secs=[4.0])
    assert _duration(master) == pytest.approx(4.0, abs=0.25)
    assert _frozen_seconds(master) == 0.0
    shot = doc["shots"][0]
    assert shot["action"] == "trim" and shot["target_seconds"] == pytest.approx(4.0)
    assert shot["held_tail_seconds"] == 0.0


def test_genuinely_short_clip_is_slowed_down_and_recorded_in_edl(tmp_path: Path):
    master, _edl, doc = _compose(tmp_path, [3.0], clip_secs=[3.0], voice_secs=[3.6])
    assert _duration(master) == pytest.approx(3.6, abs=0.25)
    assert _frozen_seconds(master) == 0.0
    shot = doc["shots"][0]
    assert shot["action"] == "slowdown"
    assert shot["slowdown_factor"] == pytest.approx(1.2, abs=0.01)


def test_unreachable_voice_length_records_held_tail_as_last_resort(tmp_path: Path):
    master, _edl, doc = _compose(tmp_path, [2.0], clip_secs=[2.0], voice_secs=[4.0])
    assert _duration(master) == pytest.approx(4.0, abs=0.25)
    shot = doc["shots"][0]
    assert shot["action"] == "slowdown_and_hold"
    assert shot["held_tail_seconds"] == pytest.approx(4.0 - 2.0 * 1.25, abs=0.01)


def test_captions_follow_planned_shot_timecodes(tmp_path: Path):
    raw = [_moving_clip(tmp_path / f"shot_0{i}.mp4", 6.0) for i in (1, 2)]
    stems = [_voice_stem(tmp_path / f"voice_shot_0{i}.wav", 1.0) for i in (1, 2)]
    script = _script([2.0, 3.0])
    for b in script.beats:
        b.on_screen_text = "HELLO"
    manifest = AssetManifestArtifact(campaign_id="t", keyframes=[], raw_video_clips=raw, audio_stems=stems)
    edl = compose_master_commercial(script=script, manifest=manifest, output_master_path=tmp_path / "m.mp4",
                                    artifacts_dir=tmp_path)
    assert [(c["start"], c["end"]) for c in edl.captions] == [(0.0, 2.0), (2.0, 5.0)]


# --------------------------------------------------------------------------------------
# Ducking and loudness
# --------------------------------------------------------------------------------------
def _mean_db(path: Path, ss: float, t: float) -> float:
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", str(ss), "-t", str(t), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", res.stderr).group(1))


@pytest.mark.parametrize("speech_gain_db", [0, 10])  # quiet (-32 dB mean) and typical (-22 dB mean) speech
def test_ducking_filter_dips_music_at_least_ten_db_during_speech(tmp_path: Path, speech_gain_db: int):
    speech, bgm, out = tmp_path / "speech.wav", tmp_path / "bgm.wav", tmp_path / "ducked.wav"
    _ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:a=0.3:r=48000", "-af",
            f"highpass=f=150,lowpass=f=3500,volume={speech_gain_db}dB,volume='if(between(t,2,4),0,1)':eval=frame,"
            "aformat=channel_layouts=stereo", str(speech))
    _ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=3:c=pink:a=0.3:r=48000", "-af", "aformat=channel_layouts=stereo", str(bgm))
    _ffmpeg("-i", str(speech), "-stream_loop", "-1", "-i", str(bgm), "-t", "6", "-filter_complex",
            f"[1:a]volume=0.25[bgm_base];[bgm_base][0:a]{DUCKING_FILTER}[d]", "-map", "[d]", str(out))
    dip = _mean_db(out, 3.4, 0.5) - _mean_db(out, 1.0, 1.0)  # pause vs. speech
    assert dip >= 10.0
    assert BGM_DUCKING_ATTENUATION_DB == -14.0


def test_compose_writes_audio_mix_report_with_loudness(tmp_path: Path):
    master, _edl, _doc = _compose(tmp_path, [3.0], clip_secs=[6.0], voice_secs=[2.0])
    report = json.loads((tmp_path / "audio_mix_report.json").read_text())
    assert report["target_lufs"] == -14.0
    assert isinstance(report["output_lufs"], float)
    assert report["compliant"] == (abs(report["output_lufs"] - (-14.0)) <= report["tolerance_lu"])
    assert report["ducking_attenuation_db"] == -14.0
