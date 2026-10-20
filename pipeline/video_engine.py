"""Step 5: Video Generation Engine (MiniMax Hailuo-2.3 I2V & T2V, plus local placeholders).

``mode="api"`` (alias ``"diffusion"``): ZERO TOLERANCE for static images or ffmpeg zoompan
fallbacks. Every shot is rendered through genuine video diffusion with exponential backoff
retries and rigorous validation. It never degrades to a placeholder on failure.

``mode="ffmpeg"``: an explicit, network-free LOCAL_FFMPEG run. Each shot becomes a short
ffmpeg motion clip (zoompan on its keyframe, or a testsrc2 pattern) at 9:16 for the beat's
duration, burned-in "LOCAL PLACEHOLDER" banner, tagged in the Prompt Ledger and in a
``.placeholder.json`` sidecar. These are test fixtures, never diffusion output.

``mode="auto"``: ``api`` unless offline (``KOL_OFFLINE=1``), then ``ffmpeg``.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import json
import logging
import os
import random
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline import telemetry
from pipeline.offline import OfflineNetworkError, guard_network, is_offline, offline_mode
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
from tools.generate_video import (
    VideoAPIError,
    is_retryable_error,
    normalize_duration,
    poll_and_download_video,
    submit_video_job,
    upload_first_frame,
)

logger = logging.getLogger(__name__)

#: R2V (Reference-to-Video) model: MiniMax's subject-reference model takes the Face Anchor as a
#: single character image (Hailuo-2.3 itself has no ``subject_reference``). Override via env.
DEFAULT_R2V_MODEL = os.environ.get("KOL_R2V_MODEL", "S2V-01")
#: ``subject_reference`` (default) or ``face_anchor_i2v`` (degraded: Face Anchor as I2V First Frame,
#: recorded in the Prompt Ledger as ``degraded_from=R2V``) for gateways without subject-reference support.
DEFAULT_R2V_STRATEGY = os.environ.get("KOL_R2V_STRATEGY", "subject_reference")
#: Optional output resolution (``768P``/``1080P``); unset keeps the API default (768P). 1080P forces 6s clips.
DEFAULT_RESOLUTION: Optional[str] = os.environ.get("KOL_VIDEO_RESOLUTION") or None

#: Stage-5 batch progress, shared with the threaded per-shot renderer.
_progress_lock = threading.Lock()
_progress_state: Dict[str, int] = {"total": 0, "done": 0}


def _ensure_stage5_started(total: int) -> None:
    """Open stage 5 with its shot total, unless the director already opened it."""
    recorder = telemetry.current()
    if recorder is not None and recorder.snapshot().get("current_stage") == 5:
        return
    telemetry.start_stage(5, total=total)


def _rel_path(path: Optional[str | Path]) -> Optional[str]:
    """Telemetry-friendly path: relative to the run root, else the repo root."""
    if path is None:
        return None
    resolved = Path(path)
    recorder = telemetry.current()
    bases = [recorder.base_dir] if recorder is not None else []
    bases.append(BASE_DIR)
    for base in bases:
        try:
            return str(resolved.resolve().relative_to(base))
        except (ValueError, OSError):
            continue
    return str(resolved)


def _file_size(path: Optional[str | Path]) -> Optional[int]:
    """Size in bytes of ``path``, or ``None`` when it cannot be stat-ed."""
    try:
        return Path(path).stat().st_size if path else None
    except OSError:
        return None


def _stage5_progress(item: Dict[str, Any], label: str, *, advance: bool = False) -> None:
    """Emit one stage-5 progress event for a shot, optionally advancing the batch counter."""
    with _progress_lock:
        if advance:
            _progress_state["done"] += 1
        done, total = _progress_state["done"], _progress_state["total"]
    telemetry.stage_progress(5, done, total or None, unit="clips", label=label, item=item)



class VideoGenerationError(RuntimeError):
    """Raised when genuine video diffusion generation fails after all retry attempts."""
    pass


# --------------------------------------------------------------------------- local placeholders

LOCAL_FFMPEG_MODE = "LOCAL_FFMPEG"
LOCAL_FFMPEG_MODEL = "local-ffmpeg-placeholder"
PLACEHOLDER_SIDECAR_SUFFIX = ".placeholder.json"
LOCAL_WIDTH, LOCAL_HEIGHT, LOCAL_FPS = 1080, 1920, 30
_VALID_VIDEO_MODES = ("api", "diffusion", "ffmpeg", "auto")


def resolve_video_mode(mode: str) -> str:
    """Normalize a requested video mode to ``"api"`` or ``"ffmpeg"``.

    ``auto`` is ``api`` unless offline. ``diffusion`` is the legacy alias of ``api``.
    """
    normalized = (mode or "api").strip().lower()
    if normalized not in _VALID_VIDEO_MODES:
        raise ValueError(f"Unknown video mode {mode!r}; expected one of {', '.join(_VALID_VIDEO_MODES)}")
    if normalized == "auto":
        return "ffmpeg" if is_offline() else "api"
    return "api" if normalized == "diffusion" else normalized


def _sidecar_path(clip_path: Path) -> Path:
    return clip_path.with_name(clip_path.name + PLACEHOLDER_SIDECAR_SUFFIX)


def is_placeholder_clip(clip_path: str | Path) -> bool:
    """True when ``clip_path`` is a LOCAL_FFMPEG placeholder (has the marker sidecar)."""
    return _sidecar_path(Path(clip_path)).exists()


def render_local_placeholder_clip(
    shot_id: str,
    output_path: str | Path,
    image_path: Optional[str | Path] = None,
    duration: float = 5.0,
    prompt: str = "",
    width: int = LOCAL_WIDTH,
    height: int = LOCAL_HEIGHT,
    fps: int = LOCAL_FPS,
) -> str:
    """Render a network-free motion placeholder for one shot with ffmpeg.

    Uses a slow push-in (zoompan) on the shot's keyframe when it exists, otherwise a
    ``testsrc2`` pattern. The clip is exactly ``duration`` seconds at ``width``x``height``
    (9:16 by default), carries a burned-in banner and container metadata, and gets a
    ``.placeholder.json`` sidecar. It is NEVER diffusion output.
    """
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.5, float(duration))
    frames = max(1, round(duration * fps))

    resolved_img: Optional[Path] = None
    if image_path:
        cand = Path(image_path)
        if not cand.is_absolute():
            cand = BASE_DIR / cand
        if cand.exists() and cand.is_file():
            resolved_img = cand

    box = "drawbox=x=0:y=0:w=iw:h=ih*0.045:color=red@0.85:t=fill"
    text = (
        "drawtext=text='LOCAL PLACEHOLDER - NOT DIFFUSION':fontcolor=white:fontsize=h*0.022:"
        "x=(w-text_w)/2:y=h*0.011"
    )
    banners = [f"{box},{text}", box]  # second form: ffmpeg builds without libfreetype
    if resolved_img is not None:
        zoom_expr = f"min(1+0.0008*on,1.25)"
        motion = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
            f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}"
        )
        inputs = ["-i", str(resolved_img)]
        source = "zoompan_keyframe"
    else:
        motion = ""
        inputs = ["-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate={fps}"]
        source = "testsrc2"

    # Render beside the target then atomically replace it. Never write through the existing
    # inode: versioned workspaces hardlink clips from parent versions (ADR 0007).
    tmp_p = out_p.with_name(f".{out_p.stem}.placeholder.tmp.mp4")
    res = None
    for banner in banners:
        vf = ",".join(part for part in (motion, banner, "format=yuv420p") if part)
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            *inputs,
            "-vf", vf,
            "-frames:v", str(frames),
            "-r", str(fps),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an",
            "-metadata", f"comment=KOL_PLACEHOLDER mode={LOCAL_FFMPEG_MODE} shot={shot_id}",
            str(tmp_p),
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode == 0:
            break
    if res is None or res.returncode != 0:
        tmp_p.unlink(missing_ok=True)
        raise VideoGenerationError(
            f"Local ffmpeg placeholder for '{shot_id}' failed: "
            f"{(res.stderr if res else b'').decode('utf-8', 'replace')[-400:]}"
        )
    os.replace(tmp_p, out_p)

    sidecar = _sidecar_path(out_p)
    sidecar.unlink(missing_ok=True)
    sidecar.write_text(
        json.dumps(
            {
                "placeholder": True,
                "mode": LOCAL_FFMPEG_MODE,
                "model": LOCAL_FFMPEG_MODEL,
                "shot_id": shot_id,
                "source": source,
                "first_frame": _rel_path(resolved_img),
                "duration_seconds": round(frames / fps, 3),
                "width": width,
                "height": height,
                "diffusion": False,
                "note": "Local ffmpeg motion placeholder. NOT genuine video diffusion output.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    telemetry.record_prompt(
        shot_id,
        prompt,
        stage=5,
        mode=LOCAL_FFMPEG_MODE,
        model=LOCAL_FFMPEG_MODEL,
        placeholder=True,
        aspect_ratio=f"{width}:{height}" if (width, height) != (LOCAL_WIDTH, LOCAL_HEIGHT) else "9:16",
        duration_requested=round(frames / fps, 3),
        first_frame=_rel_path(resolved_img),
        first_frame_rel=_rel_path(resolved_img),
        output_rel_path=_rel_path(out_p),
        attempt=1,
        attempt_increment=1,
    )
    return str(out_p)


class _BatchAborted(Exception):
    """Internal: a shot was skipped because an earlier shot in the batch already failed."""


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


@dataclass(frozen=True)
class ClipRequest:
    """Everything that determines one shot's rendered clip, resolved and validated locally.

    Built (and failing loudly) *before* any paid API call. ``fingerprint`` identifies the
    request so cached clips and in-flight tasks are only reused when nothing changed.
    """

    shot_id: str
    prompt: str
    mode: str  # "I2V" | "R2V" | "T2V" (the mode actually sent to the API)
    model: str
    duration: int
    aspect_ratio: str
    resolution: Optional[str]
    first_frame: Optional[Path] = None
    subject_refs: tuple[Path, ...] = ()
    degraded_from: Optional[str] = None

    @property
    def fingerprint(self) -> str:
        spec = {
            "prompt": self.prompt,
            "mode": self.mode,
            "model": self.model,
            "duration": self.duration,
            "aspect_ratio": self.aspect_ratio,
            "resolution": self.resolution,
            "first_frame": _sha256_file(self.first_frame),
            "subject_refs": [_sha256_file(p) for p in self.subject_refs],
        }
        return hashlib.sha256(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()


def _sha256_file(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _resolve_existing(path: str | Path) -> Optional[Path]:
    p = Path(path)
    if not p.is_absolute():
        p = BASE_DIR / p
    return p if p.is_file() else None


def _pick_face_anchor(reference_assets: Optional[List[str]]) -> Optional[Path]:
    """The face anchor among a shot's reference assets (name contains ``face``, else the last one)."""
    refs = list(reference_assets or [])
    if not refs:
        return None
    named = [r for r in refs if "face" in Path(r).name.lower()]
    return _resolve_existing((named or refs[-1:])[0])


def build_clip_request(
    shot_id: str,
    prompt: str,
    image_path: Optional[str | Path] = None,
    duration: float = 5.0,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    model: str = DEFAULT_VIDEO_MODEL,
    generation_mode: Optional[str] = None,
    reference_assets: Optional[List[str]] = None,
    resolution: Optional[str] = None,
    r2v_model: str = DEFAULT_R2V_MODEL,
    r2v_strategy: str = DEFAULT_R2V_STRATEGY,
) -> ClipRequest:
    """Resolve a shot into a validated :class:`ClipRequest` or raise :class:`VideoGenerationError`.

    - A requested First Frame that is missing is an error (never silently degraded to T2V,
      which would drop the Identity Lock).
    - R2V sends the Face Anchor as ``subject_reference`` (MiniMax's reference-to-video contract
      takes a single character face; a multi-panel Character Sheet cannot be one).
    """
    gen_duration = normalize_duration(duration, resolution)
    wants_r2v = generation_mode == "r2v" or bool(reference_assets and len(reference_assets) > 1)

    if wants_r2v:
        face = _pick_face_anchor(reference_assets)
        if face is None:
            raise VideoGenerationError(
                f"Shot '{shot_id}' requires R2V but its face anchor is missing "
                f"(reference_assets={reference_assets}). Run Stage 4 / restore the Character Sheet "
                f"Integrity Gate assets; refusing to degrade the Identity Lock."
            )
        if r2v_strategy == "face_anchor_i2v":
            return ClipRequest(
                shot_id, prompt, "I2V", model, gen_duration, aspect_ratio, resolution,
                first_frame=face, degraded_from="R2V",
            )
        return ClipRequest(
            shot_id, prompt, "R2V", r2v_model, gen_duration, aspect_ratio, resolution, subject_refs=(face,)
        )

    if image_path:
        frame = _resolve_existing(image_path)
        if frame is None:
            raise VideoGenerationError(
                f"Shot '{shot_id}' First Frame not found: {image_path}. Refusing to degrade to T2V "
                f"(would lose the locked identity/keyframe)."
            )
        return ClipRequest(shot_id, prompt, "I2V", model, gen_duration, aspect_ratio, resolution, first_frame=frame)

    return ClipRequest(shot_id, prompt, "T2V", model, gen_duration, aspect_ratio, resolution)


def _meta_path(clip_path: Path) -> Path:
    return clip_path.with_suffix(".meta.json")


def _task_path(clip_path: Path) -> Path:
    return clip_path.with_suffix(".task.json")


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def clip_cache_status(clip_path: str | Path, fingerprint: str) -> str:
    """``miss`` (no valid clip), ``hit`` (fingerprint matches), ``stale`` (inputs changed) or
    ``legacy`` (valid clip rendered before fingerprints existed; reused as-is)."""
    clip = Path(clip_path)
    if not clip.exists() or not verify_generated_clip(clip):
        return "miss"
    meta = _read_json(_meta_path(clip))
    if not meta.get("fingerprint"):
        return "legacy"
    return "hit" if meta["fingerprint"] == fingerprint else "stale"


def _retry_delay(attempt: int, initial_retry_delay: float, exc: BaseException) -> float:
    """Exponential backoff with jitter; rate-limit (1002) errors back off 4x longer."""
    delay = (initial_retry_delay * (2 ** (attempt - 1))) + random.uniform(1.0, 3.0)
    if isinstance(exc, VideoAPIError) and exc.rate_limited:
        delay *= 4
    return delay


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
    generation_mode: Optional[str] = None,
    reference_assets: Optional[List[str]] = None,
    resolution: Optional[str] = DEFAULT_RESOLUTION,
    r2v_model: str = DEFAULT_R2V_MODEL,
    r2v_strategy: str = DEFAULT_R2V_STRATEGY,
) -> str:
    """Renders a single shot clip using genuine MiniMax Hailuo-2.3 video diffusion.

    Supports:
    - I2V (Image-to-Video): ``image_path`` is the authoritative First Frame (must exist).
    - R2V (Reference-to-Video): the shot's Face Anchor is sent as ``subject_reference``.
    - T2V (Text-to-Video): no image; generates purely from the spatial prompt.

    Robustness:
    - Exponential backoff with jitter; non-retryable API errors (auth, balance, sensitive
      content, invalid parameters) fail immediately instead of burning paid retries.
    - The submitted task id is persisted next to the clip (``<shot>.task.json``) so a poll
      timeout, retry or process restart resumes the *same* paid task instead of re-submitting.
    - On success a ``<shot>.meta.json`` fingerprint records exactly what produced the clip.

    NEVER falls back to static image slideshows or ffmpeg pan-zoom.
    """
    guard_network("minimax.video_generation", f"shot {shot_id}")
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    req = build_clip_request(
        shot_id, prompt, image_path, duration, aspect_ratio, model,
        generation_mode, reference_assets, resolution, r2v_model, r2v_strategy,
    )
    fingerprint = req.fingerprint
    task_file = _task_path(out_p)

    task_id: Optional[str] = None
    saved = _read_json(task_file)
    if saved.get("task_id") and saved.get("fingerprint") == fingerprint:
        task_id = str(saved["task_id"])
    elif task_file.exists():
        task_file.unlink()  # in-flight task belongs to a different request

    def _drop_task() -> None:
        nonlocal task_id
        task_id = None
        task_file.unlink(missing_ok=True)

    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            print(
                f"[VideoEngine] [{shot_id}] Generating genuine diffusion clip (Attempt {attempt}/{max_retries}) | "
                f"Mode: {req.mode} | Model: {req.model}..."
            )
            # Prompt ledger: the exact prompt, model and first frame per attempt.
            telemetry.record_prompt(
                shot_id,
                prompt,
                stage=5,
                mode=req.mode,
                model=req.model,
                aspect_ratio=aspect_ratio,
                duration_requested=req.duration,
                resolution=req.resolution,
                first_frame=_rel_path(req.first_frame),
                first_frame_rel=_rel_path(req.first_frame),
                subject_reference=[_rel_path(p) for p in req.subject_refs] or None,
                degraded_from=req.degraded_from,
                fingerprint=fingerprint,
                output_rel_path=_rel_path(out_p),
                attempt=attempt,
                attempt_increment=1,
            )

            if task_id is not None:
                print(f"[VideoEngine] [{shot_id}] Resuming in-flight task {task_id} (no new submission).")
            else:
                task_id = _upload_and_submit(req, out_p, fingerprint)

            polled_task_id = task_id
            poll_started = time.monotonic()
            poll_error: Optional[str] = None
            try:
                poll_and_download_video(
                    task_id=polled_task_id,
                    output_path=out_p,
                    timeout_seconds=poll_timeout_seconds,
                )
            except Exception as exc:
                poll_error = str(exc)
                if not isinstance(exc, TimeoutError):
                    _drop_task()  # dead/unknown task: the next attempt must submit a fresh one
                raise
            finally:
                telemetry.record_api_call(
                    "minimax.poll_video",
                    endpoint=f"{MINIMAX_BASE_URL}/v1/media/video/{polled_task_id}",
                    method="GET",
                    request={"task_id": polled_task_id, "timeout_seconds": poll_timeout_seconds},
                    response={"output_rel_path": _rel_path(out_p), "size_bytes": _file_size(out_p)},
                    status="error" if poll_error else "ok",
                    ok=poll_error is None,
                    duration_seconds=time.monotonic() - poll_started,
                    stage=5,
                    shot_id=shot_id,
                )

            # Validate generated video file
            if not verify_generated_clip(out_p):
                finished_task = task_id
                _drop_task()
                raise RuntimeError(
                    f"Generated video file {out_p} (task {finished_task}) is corrupt or missing valid video stream."
                )

            _write_json_atomic(
                _meta_path(out_p),
                {
                    "fingerprint": fingerprint,
                    "task_id": task_id,
                    "shot_id": shot_id,
                    "mode": req.mode,
                    "model": req.model,
                    "duration": req.duration,
                    "aspect_ratio": aspect_ratio,
                    "resolution": req.resolution,
                    "degraded_from": req.degraded_from,
                },
            )
            task_file.unlink(missing_ok=True)

            file_size_kb = out_p.stat().st_size // 1024
            print(f"[VideoEngine] [{shot_id}] SUCCESS! Genuine video generated: {out_p.name} ({file_size_kb} KB)")
            return str(out_p)

        except OfflineNetworkError:
            raise  # never retried, never converted into a generic generation failure
        except Exception as exc:
            last_error = exc
            print(f"[VideoEngine] [{shot_id}] Attempt {attempt} failed: {exc}")
            if not is_retryable_error(exc):
                print(f"[VideoEngine] [{shot_id}] Error is not retryable; stopping without further paid attempts.")
                break
            if attempt < max_retries:
                delay = _retry_delay(attempt, initial_retry_delay, exc)
                _stage5_progress(
                    {"id": shot_id, "status": "retrying", "attempt": attempt, "error": str(exc)},
                    f"{shot_id} retrying",
                )
                print(f"[VideoEngine] [{shot_id}] Retrying in {delay:.1f}s...")
                time.sleep(delay)

    _stage5_progress(
        {"id": shot_id, "status": "failed", "attempts": max_retries, "error": str(last_error)},
        f"{shot_id} failed",
    )
    raise VideoGenerationError(
        f"CRITICAL: Failed to generate genuine video diffusion clip for shot '{shot_id}' "
        f"(model {req.model}, mode {req.mode}). Zero-tolerance policy forbids static image slideshow fallback. "
        f"Last error: {last_error}"
    )


def _upload_and_submit(req: ClipRequest, out_p: Path, fingerprint: str) -> str:
    """Upload the request's images, submit the job and persist its task id. Returns the task id."""
    shot_id = req.shot_id
    uploaded: List[str] = []
    for image in ([req.first_frame] if req.first_frame else []) + list(req.subject_refs):
        print(f"[VideoEngine] [{shot_id}] Uploading {'first frame' if image == req.first_frame else 'face anchor'}: {image.name}...")
        upload_started = time.monotonic()
        file_url: Optional[str] = None
        upload_error: Optional[str] = None
        try:
            file_url = upload_first_frame(image)
            uploaded.append(file_url)
        except Exception as exc:
            upload_error = str(exc)
            raise
        finally:
            telemetry.record_api_call(
                "minimax.upload_first_frame",
                endpoint=f"{MINIMAX_BASE_URL}/v1/media/storage/upload",
                request={"input_image": _rel_path(image)},
                response={"file_url": file_url} if file_url else None,
                status="error" if upload_error else "ok",
                ok=upload_error is None,
                duration_seconds=time.monotonic() - upload_started,
                stage=5,
                shot_id=shot_id,
            )

    first_frame_url = uploaded[0] if req.first_frame else None
    subject_urls = uploaded[1:] if req.first_frame else uploaded

    submit_kwargs: Dict[str, Any] = dict(
        prompt=req.prompt,
        image_url=first_frame_url,
        aspect_ratio=req.aspect_ratio,
        duration=req.duration,
        model=req.model,
    )
    if subject_urls and req.mode == "R2V":
        submit_kwargs["subject_reference"] = subject_urls
    if req.resolution:
        submit_kwargs["resolution"] = req.resolution

    submit_started = time.monotonic()
    submit_error: Optional[str] = None
    task_id: Optional[str] = None
    try:
        task_id = submit_video_job(**submit_kwargs)
    except Exception as exc:
        submit_error = str(exc)
        raise
    finally:
        telemetry.record_api_call(
            "minimax.submit_video",
            endpoint=f"{MINIMAX_BASE_URL}/v1/media/video",
            request={
                "model": req.model,
                "prompt_chars": len(req.prompt),
                "duration": req.duration,
                "aspect_ratio": req.aspect_ratio,
                "resolution": req.resolution,
                "input_image": first_frame_url,
                "subject_reference": subject_urls or None,
            },
            response={"task_id": task_id} if task_id else None,
            status="error" if submit_error else "ok",
            ok=submit_error is None,
            duration_seconds=time.monotonic() - submit_started,
            stage=5,
            shot_id=shot_id,
        )
    print(f"[VideoEngine] [{shot_id}] Task submitted successfully: {task_id}")
    _write_json_atomic(_task_path(out_p), {"task_id": task_id, "fingerprint": fingerprint, "shot_id": shot_id})
    telemetry.record_prompt(
        shot_id,
        req.prompt,
        stage=5,
        first_frame_url=first_frame_url,
        subject_reference_urls=subject_urls or None,
        task_id=task_id,
    )
    return str(task_id)


def render_all_video_clips(
    scene_plan: ScenePlanArtifact | None = None,
    manifest: AssetManifestArtifact | None = None,
    artifacts_dir: Path | None = None,
    raw_clips_dir: Path | None = None,
    mode: str = "api",
    max_retries: int = 3,
    initial_retry_delay: float = 5.0,
    poll_timeout_seconds: int = 300,
    max_concurrency: int = 3,
    workspace: Optional[ProjectWorkspace] = None,
) -> List[str]:
    """Renders clips for all storyboard shots concurrently.

    ``mode="api"`` (or legacy ``"diffusion"``): genuine MiniMax Hailuo-2.3 diffusion with zero
    tolerance for static images; raises ``OfflineNetworkError`` up front if offline.
    Clips whose request fingerprint is unchanged are reused (no new paid jobs); the first
    failing shot cancels all not-yet-started shots so no further credits are spent.
    ``mode="ffmpeg"``: local, network-free LOCAL_FFMPEG placeholder clips (see module doc).
    ``mode="auto"``: ``api`` unless ``KOL_OFFLINE=1``, then ``ffmpeg``.
    """
    resolved_mode = resolve_video_mode(mode)
    if resolved_mode == "api":
        guard_network("minimax.video_generation", "render_all_video_clips(mode='api')")
    local = resolved_mode == "ffmpeg"
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

    n_shots = len(scene_plan.shots)
    _progress_state["total"] = n_shots
    _progress_state["done"] = 0
    _ensure_stage5_started(n_shots)

    print("=" * 80)
    if local:
        print(f"[VideoEngine] LOCAL_FFMPEG PLACEHOLDER batch ({n_shots} shots): no network, NOT diffusion output")
    else:
        print(f"[VideoEngine] Starting Genuine Video Diffusion Batch ({n_shots} shots, concurrency={max_concurrency})")
        print(f"[VideoEngine] Target Model: {DEFAULT_VIDEO_MODEL} | Aspect: {DEFAULT_ASPECT_RATIO}")
    print("=" * 80)

    rendered_map: Dict[str, str] = {}
    abort = threading.Event()

    def _render_shot(shot: StoryboardShot) -> tuple[str, str]:
        if abort.is_set():
            raise _BatchAborted(shot.shot_id)
        try:
            return _render_shot_inner(shot)
        except Exception:
            abort.set()  # fail fast: sibling workers must not start further paid shots
            raise

    def _render_shot_inner(shot: StoryboardShot) -> tuple[str, str]:
        out_clip_path = target_clips_dir / f"{shot.shot_id}.mp4"
        if is_placeholder_clip(out_clip_path):
            # Placeholders are cheap and deterministic: always regenerate, and never let a stale
            # one be passed off as a (cached) diffusion clip.
            out_clip_path.unlink(missing_ok=True)
            _sidecar_path(out_clip_path).unlink(missing_ok=True)
            _meta_path(out_clip_path).unlink(missing_ok=True)
        kf = keyframes_by_shot.get(shot.shot_id)
        kf_image_path = kf.cleaned_image_path if kf else None
        kf_mode = getattr(kf, "generation_mode", None)
        kf_refs = getattr(kf, "reference_assets", None)
        if local:
            if out_clip_path.exists() and verify_generated_clip(out_clip_path):
                # A real (non-placeholder) clip is free to reuse; never overwrite paid output.
                print(f"[VideoEngine] [{shot.shot_id}] Existing real clip kept (offline run): {out_clip_path.name}")
                _stage5_progress(
                    {
                        "id": shot.shot_id,
                        "status": "cached",
                        "mode": "CACHED",
                        "placeholder": False,
                        "output_rel_path": _rel_path(out_clip_path),
                        "size_bytes": _file_size(out_clip_path),
                    },
                    f"{shot.shot_id} cached",
                    advance=True,
                )
                return shot.shot_id, str(out_clip_path)
            clip_path = render_local_placeholder_clip(
                shot_id=shot.shot_id,
                output_path=out_clip_path,
                image_path=kf_image_path,
                duration=shot.estimated_duration,
                prompt=shot.prompt_6part,
            )
            _stage5_progress(
                {
                    "id": shot.shot_id,
                    "status": "completed",
                    "mode": LOCAL_FFMPEG_MODE,
                    "placeholder": True,
                    "output_rel_path": _rel_path(clip_path),
                    "size_bytes": _file_size(clip_path),
                },
                f"{shot.shot_id} placeholder completed",
                advance=True,
            )
            return shot.shot_id, clip_path
        request_kwargs = dict(
            image_path=kf_image_path,
            duration=shot.estimated_duration,
            aspect_ratio=DEFAULT_ASPECT_RATIO,
            model=DEFAULT_VIDEO_MODEL,
            generation_mode=kf_mode,
            reference_assets=kf_refs,
            resolution=DEFAULT_RESOLUTION,
        )
        try:
            request = build_clip_request(shot.shot_id, shot.prompt_6part, **request_kwargs)
        except VideoGenerationError:
            request = None  # render_single re-raises the same error with full retry bookkeeping
        mode_label = request.mode if request else ("I2V" if kf_image_path else "T2V")

        cache = clip_cache_status(out_clip_path, request.fingerprint) if request else "miss"
        if cache in ("hit", "legacy"):
            print(f"[VideoEngine] [{shot.shot_id}] Existing valid diffusion clip found ({cache}): {out_clip_path.name}")
            _stage5_progress(
                {
                    "id": shot.shot_id,
                    "status": "cached",
                    "mode": mode_label,
                    "output_rel_path": _rel_path(out_clip_path),
                    "size_bytes": _file_size(out_clip_path),
                },
                f"{shot.shot_id} cached",
                advance=True,
            )
            return shot.shot_id, str(out_clip_path)
        if cache == "stale":
            print(f"[VideoEngine] [{shot.shot_id}] Cached clip is stale (prompt/references changed); re-rendering.")

        clip_path = render_single_video_clip(
            shot_id=shot.shot_id,
            prompt=shot.prompt_6part,
            output_path=out_clip_path,
            max_retries=max_retries,
            initial_retry_delay=initial_retry_delay,
            poll_timeout_seconds=poll_timeout_seconds,
            **request_kwargs,
        )
        _stage5_progress(
            {
                "id": shot.shot_id,
                "status": "completed",
                "mode": mode_label,
                "output_rel_path": _rel_path(clip_path),
                "size_bytes": _file_size(clip_path),
            },
            f"{shot.shot_id} completed",
            advance=True,
        )
        return shot.shot_id, clip_path

    # Local mode also scopes the global offline guard: any accidental network call raises.
    scope = offline_mode(True) if local else contextlib.nullcontext()
    with scope, concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = {executor.submit(_render_shot, shot): shot for shot in scene_plan.shots}
        for fut in concurrent.futures.as_completed(futures):
            shot_ref = futures[fut]
            try:
                sid, clip_p = fut.result()
                rendered_map[sid] = clip_p
            except _BatchAborted:
                continue  # skipped because another shot already failed; that failure is raised
            except Exception as e:
                # Fail fast: shots not yet started are cancelled so no further credits are spent.
                # (Already-running shots finish; their clips are cached for the resume.)
                executor.shutdown(wait=False, cancel_futures=True)
                _stage5_progress(
                    {"id": shot_ref.shot_id, "status": "failed", "error": str(e)},
                    f"{shot_ref.shot_id} failed",
                )
                telemetry.fail_stage(5, f"Shot '{shot_ref.shot_id}' failed {'local placeholder' if local else 'diffusion'} generation: {e}")
                if isinstance(e, OfflineNetworkError):
                    raise
                raise VideoGenerationError(f"Shot '{shot_ref.shot_id}' failed diffusion generation: {e}")

    rendered_clips = [rendered_map[shot.shot_id] for shot in scene_plan.shots]

    # Update asset manifest with genuine diffusion clips
    manifest.raw_video_clips = rendered_clips
    with open(target_artifacts_dir / "asset_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    if local:
        print(f"[VideoEngine] {len(rendered_clips)} LOCAL_FFMPEG PLACEHOLDER CLIPS READY (not diffusion output).")
    else:
        print(f"[VideoEngine] ALL {len(rendered_clips)} VIDEO CLIPS RENDERED THROUGH GENUINE DIFFUSION ENGINE.")
    print("=" * 80)
    placeholders = [clip for clip in rendered_clips if is_placeholder_clip(clip)]
    telemetry.complete_stage(
        5,
        message=(
            f"Rendered {len(rendered_clips)} LOCAL_FFMPEG placeholder clips (no network, not diffusion)"
            if local
            else f"Rendered {len(rendered_clips)} clips via {DEFAULT_VIDEO_MODEL}"
        ),
        clips=[_rel_path(clip) for clip in rendered_clips],
        video_mode=LOCAL_FFMPEG_MODE if local else "api",
        placeholder=bool(placeholders),
        placeholder_clips=len(placeholders),
    )
    return rendered_clips
