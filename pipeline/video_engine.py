"""Step 5: Video Clip Generation (MiniMax Hailuo I2V & Cinematic Motion)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from pipeline.config import (
    ARTIFACTS_DIR,
    BASE_DIR,
    DEFAULT_VIDEO_MODEL,
    MINIMAX_API_KEY,
    MINIMAX_BASE_URL,
    RAW_CLIPS_DIR,
)
from pipeline.schemas import AssetManifestArtifact, ScenePlanArtifact
from tools.generate_video import poll_and_download_video, submit_video_job, upload_first_frame


def generate_motion_clip_ffmpeg(
    image_path: str | Path,
    output_path: str | Path,
    duration: float = 4.0,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> str:
    """Creates a smooth cinematic push-in video clip from a keyframe image using FFmpeg."""
    img_p = Path(image_path)
    if not img_p.is_absolute():
        img_p = BASE_DIR / img_p
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    total_frames = int(duration * fps)
    # Smooth gentle zoom-in filter
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"zoompan=z='min(zoom+0.0008,1.08)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        str(img_p),
        "-vf",
        vf,
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
        raise RuntimeError(f"FFmpeg motion clip generation failed: {res.stderr.decode('utf-8')}")

    return str(out_p)


def render_all_video_clips(
    scene_plan: ScenePlanArtifact | None = None,
    manifest: AssetManifestArtifact | None = None,
    artifacts_dir: Path | None = None,
    raw_clips_dir: Path | None = None,
    mode: str = "auto",  # "api", "ffmpeg", "auto"
) -> List[str]:
    """Renders raw video clips for all storyboard shots."""
    target_artifacts_dir = artifacts_dir or ARTIFACTS_DIR
    target_clips_dir = raw_clips_dir or RAW_CLIPS_DIR
    target_clips_dir.mkdir(parents=True, exist_ok=True)

    if scene_plan is None:
        with open(target_artifacts_dir / "scene_plan.json", "r", encoding="utf-8") as f:
            scene_plan = ScenePlanArtifact.model_validate(json.load(f))

    if manifest is None:
        with open(target_artifacts_dir / "asset_manifest.json", "r", encoding="utf-8") as f:
            manifest = AssetManifestArtifact.model_validate(json.load(f))

    keyframes_by_shot = {kf.shot_id: kf for kf in manifest.keyframes}
    rendered_clips: List[str] = []

    for shot in scene_plan.shots:
        kf = keyframes_by_shot.get(shot.shot_id)
        if not kf:
            continue

        out_clip_path = target_clips_dir / f"{shot.shot_id}.mp4"

        rendered = False
        if mode in ("api", "auto"):
            try:
                print(f"[VideoEngine] Attempting MiniMax Hailuo I2V for {shot.shot_id}...")
                file_url = upload_first_frame(kf.cleaned_image_path)
                task_id = submit_video_job(
                    image_url=file_url,
                    prompt=shot.prompt_6part,
                    aspect_ratio="9:16",
                    duration=max(4, min(6, int(round(shot.estimated_duration)))),
                    model=DEFAULT_VIDEO_MODEL,
                )
                poll_and_download_video(task_id, out_clip_path, timeout_seconds=180)
                rendered = True
            except Exception as exc:
                print(f"[VideoEngine] API generation unavailable or failed: {exc}. Falling back to cinematic motion engine...")

        if not rendered:
            generate_motion_clip_ffmpeg(
                image_path=kf.cleaned_image_path,
                output_path=out_clip_path,
                duration=shot.estimated_duration,
                width=1080,
                height=1920,
            )

        rendered_clips.append(str(out_clip_path))

    # Update manifest
    manifest.raw_video_clips = rendered_clips
    with open(target_artifacts_dir / "asset_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)

    return rendered_clips
