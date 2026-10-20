from pathlib import Path
import json
import subprocess

import pytest

from pipeline import audio_lip_sync
from pipeline.composer import (
    DUCKING_FILTER,
    TARGET_LUFS,
    TARGET_TRUE_PEAK_DB,
    caption_layout,
    compose_master_commercial,
    compute_timecodes,
    measure_loudness,
    normalize_transitions,
    wrap_caption,
)
from pipeline.schemas import (
    AssetManifestArtifact,
    ScriptArtifact,
    ScriptBeat,
)
from tests.test_helpers import create_test_clip
from pipeline.audio_lip_sync import align_lip_sync_clip, synthesize_tts_stem

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


@pytest.fixture(autouse=True)
def offline_tts(monkeypatch):
    """Composition tests must never reach the paid neural TTS endpoint."""

    def _refuse(*args, **kwargs):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(audio_lip_sync.urllib.request, "urlopen", _refuse)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _voiced_clip(path: Path, duration: float, hz: int = 300, size: str = "540x960") -> str:
    """A synced-clip stand-in with audible 'speech' (noise bursts) so the mix has a real voice key."""
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={duration}",
        "-f", "lavfi",
        "-i", f"anoisesrc=d={duration}:c=brown:a=0.4:r=48000,aformat=channel_layouts=stereo",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-shortest", str(path),
    )
    return str(path)


def _script(n: int, texts: list[str] | None = None) -> ScriptArtifact:
    texts = texts or [f"CAPTION {i + 1}" for i in range(n)]
    return ScriptArtifact(
        campaign_id="test_comp",
        product_name="Test Product",
        target_duration=2.0 * n,
        beats=[
            ScriptBeat(
                scene_id=f"shot_{i + 1:02d}",
                beat_type="hook" if i == 0 else "cta",
                spoken_text=f"Beat {i + 1} test voice",
                on_screen_text=texts[i],
                visual_cue=f"cue {i + 1}",
                estimated_duration=2.0,
            )
            for i in range(n)
        ],
    )


def _duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    )
    return float(json.loads(out)["format"]["duration"])


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

    script = _script(2, ["HOOK TEXT", "CTA TEXT"])
    manifest = AssetManifestArtifact(
        campaign_id="test_comp",
        keyframes=[],
        synced_video_clips=synced_clips,
    )

    master_path = tmp_path / "test_master.mp4"
    compose_master_commercial(
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


# -- Captions ---------------------------------------------------------------------------------


def test_caption_layout_respects_9x16_platform_safe_zones():
    layout = caption_layout(1080, 1920)
    # TikTok/Reels UI covers ~320-480px at the bottom and ~120px at the sides.
    assert layout.bottom_margin >= 0.22 * 1920
    assert layout.margin_x >= 0.08 * 1080
    assert layout.max_text_width <= 1080 - 2 * layout.margin_x


def test_wrap_caption_never_exceeds_safe_width_and_keeps_every_word():
    text = "Đầm xòe cherry mềm mại, thoải mái cả ngày dài, giảm ngay 50% hôm nay!"
    layout = caption_layout(1080, 1920)
    lines = wrap_caption(text, layout.max_text_width, layout.font_size, FONT)
    assert 1 < len(lines) <= 3
    assert " ".join(lines).split() == text.split()

    from PIL import ImageFont

    font = ImageFont.truetype(FONT, layout.font_size)
    assert all(font.getlength(line) <= layout.max_text_width for line in lines)


def test_wrap_caption_empty_text_has_no_lines():
    assert wrap_caption("   ", 800, 48, FONT) == []


# -- Transitions / timeline -------------------------------------------------------------------


def test_normalize_transitions_defaults_to_hard_cuts():
    assert normalize_transitions(None, [2.0, 2.0, 2.0]) == [
        {"from": 0, "to": 1, "type": "cut", "duration": 0.0},
        {"from": 1, "to": 2, "type": "cut", "duration": 0.0},
    ]


def test_normalize_transitions_clamps_duration_and_rejects_unknown_types():
    out = normalize_transitions([{"type": "fade", "duration": 5.0}], [2.0, 1.0])
    # never more than half of the shorter adjacent clip
    assert out[0]["type"] == "fade" and out[0]["duration"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        normalize_transitions([{"type": "warpdrive", "duration": 0.3}], [2.0, 2.0])


def test_compute_timecodes_accounts_for_transition_overlap():
    trans = normalize_transitions([{"type": "fade", "duration": 0.4}, {"type": "cut"}], [2.0, 2.0, 2.0])
    tcs = compute_timecodes([2.0, 2.0, 2.0], trans)
    assert tcs[0] == (0.0, 2.0)
    assert tcs[1][0] == pytest.approx(1.6)
    assert tcs[2][0] == pytest.approx(3.6)
    assert tcs[2][1] == pytest.approx(5.6)


def test_compose_honours_requested_crossfade_and_records_it(tmp_path: Path):
    clips = [_voiced_clip(tmp_path / f"c{i}.mp4", 2.0) for i in range(3)]
    manifest = AssetManifestArtifact(campaign_id="test_comp", keyframes=[], synced_video_clips=clips)
    master = tmp_path / "master.mp4"
    edl = compose_master_commercial(
        script=_script(3),
        manifest=manifest,
        output_master_path=master,
        artifacts_dir=tmp_path,
        transitions=[{"type": "fade", "duration": 0.4}, {"type": "cut"}],
    )
    # 3 x 2.0s minus one 0.4s overlap
    assert _duration(master) == pytest.approx(5.6, abs=0.15)
    assert [t["type"] for t in edl.transitions] == ["fade", "cut"]
    saved = json.loads((tmp_path / "edit_decisions.json").read_text())
    assert saved["transitions"][0]["duration"] == pytest.approx(0.4)
    # caption windows follow the overlapped timeline
    assert edl.captions[1]["start"] == pytest.approx(1.6, abs=0.01)
    assert edl.captions[2]["start"] == pytest.approx(3.6, abs=0.01)


# -- Hard-to-escape caption text --------------------------------------------------------------


def test_compose_survives_punctuation_heavy_and_long_captions(tmp_path: Path):
    clips = [_voiced_clip(tmp_path / f"c{i}.mp4", 1.5) for i in range(2)]
    manifest = AssetManifestArtifact(campaign_id="test_comp", keyframes=[], synced_video_clips=clips)
    texts = [
        "Don't miss: 50% off, today's \"deal\" \\ now",
        "Đầm xòe cherry mềm mại thoải mái cả ngày dài giảm ngay năm mươi phần trăm hôm nay thôi nhé",
    ]
    master = tmp_path / "master.mp4"
    edl = compose_master_commercial(
        script=_script(2, texts),
        manifest=manifest,
        output_master_path=master,
        artifacts_dir=tmp_path,
    )
    assert master.exists()
    assert [c["text"] for c in edl.captions] == texts
    assert len(edl.captions[1]["lines"]) > 1  # wrapped to stay inside the safe zone


# -- Audio mix: ducking + loudness ------------------------------------------------------------


def _mean_db(path: Path, start: float, length: float) -> float:
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(length), "-i", str(path),
         "-af", "volumedetect", "-f", "null", "-"],
        stderr=subprocess.PIPE, check=True,
    )
    for line in res.stderr.decode().splitlines():
        if "mean_volume" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    raise AssertionError("no mean_volume")


def test_bgm_ducking_filter_really_attenuates_music_under_speech(tmp_path: Path):
    bgm, voice, ducked = tmp_path / "bgm.wav", tmp_path / "voice.wav", tmp_path / "ducked.wav"
    _ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=8:c=pink:a=0.5:r=48000,aformat=channel_layouts=stereo", str(bgm))
    _ffmpeg(
        "-f", "lavfi",
        "-i", "anoisesrc=d=8:c=brown:a=0.3:r=48000,volume='if(lt(mod(t,4),2),1,0)':eval=frame,aformat=channel_layouts=stereo",
        str(voice),
    )
    graph = f"[0:a][1:a]{DUCKING_FILTER}[out]"
    _ffmpeg("-i", str(bgm), "-i", str(voice), "-filter_complex", graph, "-map", "[out]", str(ducked))
    during_speech = _mean_db(ducked, 0.8, 0.8)  # speech 0-2s
    during_pause = _mean_db(ducked, 3.0, 0.8)  # silence 2-4s
    assert during_pause - during_speech >= 10.0  # ADR 0003: music must audibly dip under the voice


def test_master_hits_streaming_loudness_and_true_peak(tmp_path: Path):
    clips = [_voiced_clip(tmp_path / f"c{i}.mp4", 2.0) for i in range(2)]
    manifest = AssetManifestArtifact(campaign_id="test_comp", keyframes=[], synced_video_clips=clips)
    master = tmp_path / "master.mp4"
    compose_master_commercial(
        script=_script(2), manifest=manifest, output_master_path=master, artifacts_dir=tmp_path
    )
    m = measure_loudness(master)
    assert m["integrated_lufs"] == pytest.approx(TARGET_LUFS, abs=0.6)
    assert m["true_peak_db"] <= TARGET_TRUE_PEAK_DB + 0.2

    report = json.loads((tmp_path / "audio_mix_report.json").read_text())
    assert report["target_lufs"] == TARGET_LUFS
    assert report["two_pass"] is True
    assert abs(report["output_lufs"] - m["integrated_lufs"]) < 0.5
