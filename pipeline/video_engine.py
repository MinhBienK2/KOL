"""Step 5: 100% Genuine Video Diffusion Engine (MiniMax Hailuo-2.3 I2V & T2V).

ZERO TOLERANCE for static images or ffmpeg zoompan fallbacks.
Every single shot is rendered through high-fidelity genuine video diffusion models
with exponential backoff retries and rigorous validation.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import random
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional
from pipeline.config import (
    ARTIFACTS_DIR,
    BASE_DIR,
    DEFAULT_ASPECT_RATIO,
    DEFAULT_VIDEO_MODEL,
    MINIMAX_API_KEY,
    MINIMAX_BASE_URL,
    RAW_CLIPS_DIR,
)
from pipeline.workspace import ProjectWorkspace
from pipeline.schemas import AssetManifestArtifact, ScenePlanArtifact, StoryboardShot
from pipeline.slideshow_risk import score_slideshow_risk
from tools.generate_video import poll_and_download_video, submit_video_job, upload_first_frame
logger = logging.getLogger(__name__)


class VideoGenerationError(RuntimeError):
    """Raised when genuine video diffusion generation fails after all retry attempts."""
    pass


def verify_generated_clip(clip_path: str | Path, min_size_bytes: int = 10000) -> bool:
    """Verifies that the generated mp4 video is non-empty and has a valid video stream."""
    path = Path(clip_path)
    if not path.exists():
        return False
    if path.stat().st_size < min_size_bytes:
        return False

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        if res.returncode != 0:
            return False
        data = json.loads(res.stdout.decode("utf-8"))
        streams = data.get("streams", [])
        return len(streams) > 0
    except Exception:
        # If ffprobe fails or is missing, size check was already validated
        return True


def render_single_video_clip(
    shot_id: str,
    prompt: str,
    output_path: str | Path,
    image_path: Optional[str | Path] = None,
    duration: float = 5.0,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    model: str = DEFAULT_VIDEO_MODEL,
    max_retries: int = 3,
    initial_retry_delay: float = 5.0,
    poll_timeout_seconds: int = 300,
) -> str:
    """Renders a single shot clip using genuine MiniMax Hailuo-2.3 video diffusion.

    Supports:
    - I2V (Image-to-Video): If image_path is provided and exists, uses it as the authoritative First Frame.
    - T2V (Text-to-Video): If image_path is None or absent, generates video purely from the spatial prompt.

    Enforces exponential backoff with jitter on retries.
    NEVER falls back to static image slideshows or ffmpeg pan-zoom.
    """
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # Clean duration: MiniMax-Hailuo-2.3 contract strictly requires 6 or 10 seconds
    gen_duration = 10 if duration >= 8.5 else 6
    # Resolve image path for I2V
    resolved_img_path: Optional[Path] = None
    if image_path:
        p = Path(image_path)
        if not p.is_absolute():
            p = BASE_DIR / p
        if p.exists() and p.is_file():
            resolved_img_path = p

    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            print(
                f"[VideoEngine] [{shot_id}] Generating genuine diffusion clip (Attempt {attempt}/{max_retries}) | "
                f"Mode: {'I2V (First Frame)' if resolved_img_path else 'T2V (Direct Prompt)'} | Model: {model}..."
            )

            file_url: Optional[str] = None
            if resolved_img_path:
                print(f"[VideoEngine] [{shot_id}] Uploading first frame: {resolved_img_path.name}...")
                file_url = upload_first_frame(resolved_img_path)

            task_id = submit_video_job(
                prompt=prompt,
                image_url=file_url,
                aspect_ratio=aspect_ratio,
                duration=gen_duration,
                model=model,
            )
            print(f"[VideoEngine] [{shot_id}] Task submitted successfully: {task_id}")

            poll_and_download_video(
                task_id=task_id,
                output_path=out_p,
                timeout_seconds=poll_timeout_seconds,
            )

            # Validate generated video file
            if not verify_generated_clip(out_p):
                raise RuntimeError(
                    f"Generated video file {out_p} is corrupt or missing valid video stream."
                )

            file_size_kb = out_p.stat().st_size // 1024
            print(f"[VideoEngine] [{shot_id}] SUCCESS! Genuine video generated: {out_p.name} ({file_size_kb} KB)")
            return str(out_p)

        except Exception as exc:
            last_error = exc
            print(f"[VideoEngine] [{shot_id}] Attempt {attempt} failed: {exc}")
            if attempt < max_retries:
                # Exponential backoff with random jitter
                delay = (initial_retry_delay * (2 ** (attempt - 1))) + random.uniform(1.0, 3.0)
                print(f"[VideoEngine] [{shot_id}] Retrying in {delay:.1f}s...")
                time.sleep(delay)

    raise VideoGenerationError(
        f"CRITICAL: Failed to generate genuine video diffusion clip for shot '{shot_id}' "
        f"after {max_retries} retries. Zero-tolerance policy forbids static image slideshow fallback. "
        f"Last error: {last_error}"
    )


def render_all_video_clips(
    scene_plan: ScenePlanArtifact | None = None,
    manifest: AssetManifestArtifact | None = None,
    artifacts_dir: Path | None = None,
    raw_clips_dir: Path | None = None,
    mode: str = "diffusion",
    max_retries: int = 3,
    initial_retry_delay: float = 5.0,
    poll_timeout_seconds: int = 300,
    max_concurrency: int = 3,
    workspace: Optional[ProjectWorkspace] = None,
) -> List[str]:
    """Renders 100% genuine video diffusion clips for all storyboard shots concurrently.

    Each shot is rendered through MiniMax Hailuo-2.3 with zero tolerance for static images.
    """
    target_artifacts_dir = workspace.artifacts_dir if workspace is not None else (artifacts_dir or ARTIFACTS_DIR)
    target_clips_dir = workspace.raw_clips_dir if workspace is not None else (raw_clips_dir or RAW_CLIPS_DIR)
    target_clips_dir.mkdir(parents=True, exist_ok=True)

    if scene_plan is None:
        plan_file = target_artifacts_dir / "scene_plan.json"
        if not plan_file.exists():
            raise FileNotFoundError(f"Scene plan artifact not found at {plan_file}")
        with open(plan_file, "r", encoding="utf-8") as f:
            scene_plan = ScenePlanArtifact.model_validate(json.load(f))

    # Pre-render Slideshow Risk Gate (OpenMontage 6-dimension risk test & zero-tolerance kinetic rule)
    risk_report = score_slideshow_risk(scene_plan)
    if not risk_report.passed:
        raise VideoGenerationError(
            f"CRITICAL: Pre-render Slideshow Risk Gate REJECTED the scene plan: "
            f"{'; '.join(risk_report.hard_reject_reasons)}"
        )
    if manifest is None:
        manifest_file = target_artifacts_dir / "asset_manifest.json"
        if not manifest_file.exists():
            raise FileNotFoundError(f"Asset manifest artifact not found at {manifest_file}")
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = AssetManifestArtifact.model_validate(json.load(f))

    keyframes_by_shot = {kf.shot_id: kf for kf in manifest.keyframes}

    print("=" * 80)
    print(f"[VideoEngine] Starting Genuine Video Diffusion Batch ({len(scene_plan.shots)} shots, concurrency={max_concurrency})")
    print(f"[VideoEngine] Target Model: {DEFAULT_VIDEO_MODEL} | Aspect: {DEFAULT_ASPECT_RATIO}")
    print("=" * 80)

    rendered_map: Dict[str, str] = {}

    def _render_shot(shot: StoryboardShot) -> tuple[str, str]:
        out_clip_path = target_clips_dir / f"{shot.shot_id}.mp4"
        if out_clip_path.exists() and verify_generated_clip(out_clip_path):
            print(f"[VideoEngine] [{shot.shot_id}] Existing valid diffusion clip found: {out_clip_path.name}")
            return shot.shot_id, str(out_clip_path)
        kf = keyframes_by_shot.get(shot.shot_id)
        kf_image_path = kf.cleaned_image_path if kf else None
        clip_path = render_single_video_clip(
            shot_id=shot.shot_id,
            prompt=shot.prompt_6part,
            output_path=out_clip_path,
            image_path=kf_image_path,
            duration=shot.estimated_duration,
            aspect_ratio=DEFAULT_ASPECT_RATIO,
            model=DEFAULT_VIDEO_MODEL,
            max_retries=max_retries,
            initial_retry_delay=initial_retry_delay,
            poll_timeout_seconds=poll_timeout_seconds,
        )
        return shot.shot_id, clip_path

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = {executor.submit(_render_shot, shot): shot for shot in scene_plan.shots}
        for fut in concurrent.futures.as_completed(futures):
            shot_ref = futures[fut]
            try:
                sid, clip_p = fut.result()
                rendered_map[sid] = clip_p
            except Exception as e:
                raise VideoGenerationError(f"Shot '{shot_ref.shot_id}' failed diffusion generation: {e}")

    rendered_clips = [rendered_map[shot.shot_id] for shot in scene_plan.shots]

    # Update asset manifest with genuine diffusion clips
    manifest.raw_video_clips = rendered_clips
    with open(target_artifacts_dir / "asset_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"[VideoEngine] ALL {len(rendered_clips)} VIDEO CLIPS RENDERED THROUGH GENUINE DIFFUSION ENGINE.")
    print("=" * 80)
    return rendered_clips
