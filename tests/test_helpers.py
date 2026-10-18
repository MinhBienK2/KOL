"""Test helpers for generating synthetic test clips without external API calls."""

from __future__ import annotations

import subprocess
from pathlib import Path


def create_test_clip(
    image_path: str | Path,
    output_path: str | Path,
    duration: float = 2.0,
    width: int = 540,
    height: int = 960,
    fps: int = 24,
) -> str:
    """Generates a dummy test video file using ffmpeg for testing composition/sync only."""
    img_p = Path(image_path).resolve()
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(img_p),
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        str(out_p),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(f"create_test_clip failed: {res.stderr.decode('utf-8')}")

    return str(out_p)
