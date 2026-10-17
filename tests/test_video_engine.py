from pathlib import Path
import json
import subprocess

from pipeline.video_engine import generate_motion_clip_ffmpeg


def test_generate_motion_clip_ffmpeg(tmp_path: Path):
    src = Path("assets/characters/kol_main/portrait.png")
    dst = tmp_path / "test_clip.mp4"
    res = generate_motion_clip_ffmpeg(
        image_path=src,
        output_path=dst,
        duration=1.5,
        width=540,
        height=960,
        fps=15,
    )

    assert dst.exists()
    assert res == str(dst)

    # Check ffprobe
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration",
        "-of",
        "json",
        str(dst),
    ]
    probe = json.loads(subprocess.check_output(cmd).decode("utf-8"))
    st = probe["streams"][0]
    assert st["width"] == 540
    assert st["height"] == 960
    assert float(st["duration"]) >= 1.4
