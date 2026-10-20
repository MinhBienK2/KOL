#!/usr/bin/env python3
"""DramaClaw / Hailuo AI Image-to-Video Generator.

Generates 100% character-consistent video clips by using the canonical character
images as First Frame (I2V) via MiniMax-Hailuo-2.3 API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent

# Allow standalone execution (`python tools/generate_video.py`) to import the pipeline.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import telemetry  # noqa: E402  (import after the sys.path bootstrap)

API_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://aiapi.2tocom.space")
API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cu-hr7Y6QZPkzksXlfn74J4yeF_xmL9Rlubf_tAhD4Sgfw")

#: MiniMax ``base_resp.status_code`` values that retrying can never fix (and that would
#: burn paid submissions): auth, balance, sensitive prompt/output, invalid parameters.
NON_RETRYABLE_CODES = frozenset({1004, 1008, 1026, 1027, 2013, 2049})
RATE_LIMIT_CODE = 1002


class VideoAPIError(RuntimeError):
    """A MiniMax-reported failure carrying its ``base_resp`` code and retry classification.

    ``task_failed`` is True when the remote *task* itself reached ``Fail`` (so its task id
    is dead and the next attempt must submit a fresh job rather than resume it).
    """

    def __init__(
        self,
        message: str,
        code: Optional[int] = None,
        *,
        retryable: Optional[bool] = None,
        task_failed: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = (code not in NON_RETRYABLE_CODES) if retryable is None else retryable
        self.task_failed = task_failed

    @property
    def rate_limited(self) -> bool:
        return self.code == RATE_LIMIT_CODE


def is_retryable_error(exc: BaseException) -> bool:
    """True when ``exc`` is worth another (paid) attempt: transient network/server/rate-limit faults."""
    if isinstance(exc, VideoAPIError):
        return exc.retryable
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 425, 429) or exc.code >= 500
    if isinstance(exc, (FileNotFoundError, PermissionError, ValueError)):
        return False
    return True


def normalize_duration(duration: float, resolution: Optional[str] = None) -> int:
    """Map a requested duration onto Hailuo-2.3's contract: 6s, or 10s (768P only; 1080P is 6s only)."""
    if str(resolution or "").upper() == "1080P":
        return 6
    return 10 if duration >= 8.5 else 6


def _raise_for_base_resp(res: dict, *, task_failed: bool = False) -> None:
    """Raise :class:`VideoAPIError` when the response carries a non-zero ``base_resp.status_code``."""
    base = res.get("base_resp") if isinstance(res, dict) else None
    code = (base or {}).get("status_code")
    if code not in (None, 0):
        raise VideoAPIError(
            f"MiniMax error {code}: {(base or {}).get('status_msg') or res}",
            int(code),
            task_failed=task_failed,
        )


def _download_atomic(video_url: str, output_path: Path) -> None:
    """Download to ``<name>.part`` then rename, so a partial file never masquerades as a clip."""
    part = output_path.with_name(output_path.name + ".part")
    try:
        urllib.request.urlretrieve(video_url, part)
        os.replace(part, output_path)
    finally:
        if part.exists():
            part.unlink()


def upload_first_frame(image_path: str | Path) -> str:
    path = Path(image_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")

    boundary = "----WebKitFormBoundaryVideoGen7MA4YWxk"
    with open(path, "rb") as f:
        file_bytes = f.read()

    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode("utf-8"))
    mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"{API_BASE_URL.rstrip('/')}/v1/media/storage/upload"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )

    started = time.monotonic()
    file_url: Optional[str] = None
    status_code: Optional[int] = None
    error: Optional[str] = None
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status_code = getattr(resp, "status", None)
            res = json.loads(resp.read().decode("utf-8"))
            file_url = res["data"]["file_url"]
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        telemetry.record_api_call(
            "minimax.upload_first_frame",
            endpoint=url,
            request={"file": path.name, "size_bytes": len(file_bytes)},
            response={"file_url": file_url} if error is None else None,
            status=status_code if error is None else "error",
            ok=error is None,
            duration_seconds=time.monotonic() - started,
        )
    return str(file_url)


def submit_video_job(
    prompt: str,
    image_url: str | None = None,
    aspect_ratio: str = "9:16",
    duration: int = 6,
    model: str = "MiniMax-Hailuo-2.3",
    subject_reference: list[str] | None = None,
    resolution: str | None = None,
) -> str:
    """Submit one video job (I2V via ``image_url``, R2V via ``subject_reference`` face images)."""
    valid_duration = normalize_duration(duration, resolution)
    url = f"{API_BASE_URL.rstrip('/')}/v1/media/video"
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": valid_duration,
    }
    if image_url:
        payload["input_image"] = image_url
    if resolution:
        payload["resolution"] = resolution
    if subject_reference:
        payload["subject_reference"] = [{"type": "character", "image": [ref]} for ref in subject_reference]
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )

    started = time.monotonic()
    status_code: Optional[int] = None
    error: Optional[str] = None
    task_id: Optional[str] = None
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status_code = getattr(resp, "status", None)
            res = json.loads(resp.read().decode("utf-8"))
            _raise_for_base_resp(res)
            task_id = res["task_id"]
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        telemetry.record_api_call(
            "minimax.submit_video",
            endpoint=url,
            # Prompt text itself is the prompt ledger's job; only its size is echoed here.
            request={
                "model": payload["model"],
                "aspect_ratio": payload["aspect_ratio"],
                "duration": payload["duration"],
                "input_image": payload.get("input_image"),
                "resolution": payload.get("resolution"),
                "subject_reference": payload.get("subject_reference"),
                "prompt_chars": len(payload["prompt"]),
            },
            response={"task_id": task_id} if error is None else None,
            status=status_code if error is None else "error",
            ok=error is None,
            duration_seconds=time.monotonic() - started,
        )
    return str(task_id)


def poll_and_download_video(
    task_id: str,
    output_path: str | Path,
    timeout_seconds: int = 300,
    poll_interval: float = 10.0,
    max_transient_errors: int = 3,
) -> str:
    """Poll a video task to completion and download it atomically.

    Transient poll faults (network blips, 5xx, 429) are absorbed up to ``max_transient_errors``
    consecutive failures so one dropped request does not orphan a paid, still-rendering task.
    A remote ``Fail`` raises :class:`VideoAPIError` (``task_failed=True``).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    poll_url = f"{API_BASE_URL.rstrip('/')}/v1/media/video/{task_id}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Bearer {API_KEY}",
    }

    start = time.time()
    print(f"[VideoGen] Polling video task {task_id} (timeout {timeout_seconds}s)...")
    polls = 0
    transient_errors = 0
    last_status: Optional[str] = None
    poll_request = {"task_id": task_id, "timeout_seconds": timeout_seconds}
    while time.time() - start < timeout_seconds:
        status_code: Optional[int] = None
        try:
            req = urllib.request.Request(poll_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                status_code = getattr(resp, "status", None)
                res = json.loads(resp.read().decode("utf-8"))
            transient_errors = 0
        except Exception as exc:
            transient_errors += 1
            telemetry.record_api_call(
                "minimax.poll_video",
                endpoint=poll_url,
                method="GET",
                request=poll_request,
                response={"error": str(exc), "consecutive_errors": transient_errors},
                status="error",
                ok=False,
                duration_seconds=time.monotonic() - start,
            )
            if not is_retryable_error(exc) or transient_errors >= max_transient_errors:
                raise
            time.sleep(poll_interval)
            continue

        status = res.get("status")
        elapsed = int(time.time() - start)
        polls += 1
        last_status = status
        telemetry.log(f"[{task_id}] poll {elapsed}s status={status}")
        print(f"[{elapsed:3d}s] Task status: {status}")

        if status == "Success":
            video_url = res.get("video_url") or res.get("url")
            if not video_url:
                raise RuntimeError(f"Success status received but no video URL found in: {res}")
            print(f"[VideoGen] Video rendered! Downloading to {output_path}...")
            download_started = time.monotonic()
            download_error: Optional[str] = None
            try:
                _download_atomic(video_url, output_path)
            except Exception as exc:
                download_error = str(exc)
                raise
            finally:
                telemetry.record_api_call(
                    "minimax.download_video",
                    endpoint=video_url,
                    method="GET",
                    request={"task_id": task_id},
                    response={
                        "output_path": str(output_path),
                        "size_bytes": output_path.stat().st_size if output_path.exists() else None,
                    },
                    status="error" if download_error else "ok",
                    ok=download_error is None,
                    duration_seconds=time.monotonic() - download_started,
                )
            print(f"[VideoGen] DONE! Video saved: {output_path} ({output_path.stat().st_size // 1024} KB)")
            telemetry.record_api_call(
                "minimax.poll_video",
                endpoint=poll_url,
                method="GET",
                request=poll_request,
                response={"status": status, "polls": polls},
                status=status_code,
                ok=True,
                duration_seconds=time.monotonic() - start,
            )
            return str(output_path)

        if status in ("Fail", "Failed"):
            telemetry.record_api_call(
                "minimax.poll_video",
                endpoint=poll_url,
                method="GET",
                request=poll_request,
                response={"status": status, "polls": polls},
                status=status_code,
                ok=False,
                duration_seconds=time.monotonic() - start,
            )
            _raise_for_base_resp(res, task_failed=True)
            raise VideoAPIError(f"Video generation failed: {res}", None, task_failed=True)

        time.sleep(poll_interval)

    telemetry.record_api_call(
        "minimax.poll_video",
        endpoint=poll_url,
        method="GET",
        request=poll_request,
        response={"status": last_status, "polls": polls},
        status="timeout",
        ok=False,
        duration_seconds=time.monotonic() - start,
    )
    raise TimeoutError(f"Video generation timed out after {timeout_seconds} seconds.")


def main() -> None:
    parser = argparse.ArgumentParser(description="DramaClaw Image-to-Video Generator")
    parser.add_argument(
        "--image",
        default="assets/characters/kol_main/expressions/02_smiling.jpg",
        help="First Frame image path (e.g. assets/characters/kol_main/expressions/02_smiling.jpg)",
    )
    parser.add_argument(
        "--prompt",
        default="The young woman looks at the camera, smiling warmly, natural blinking, subtle head movement, cinematic photorealistic lighting",
        help="Action and camera motion prompt",
    )
    parser.add_argument("--aspect-ratio", default="9:16", choices=["9:16", "16:9", "1:1"], help="Video aspect ratio")
    parser.add_argument("--duration", type=int, default=6, help="Duration in seconds (default 6)")
    parser.add_argument("--output", default="output/kol_video_clip.mp4", help="Output MP4 file path")

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("DRAMACLAW IMAGE-TO-VIDEO PRODUCTION PIPELINE")
    print("=" * 70)
    print(f"Input Image (First Frame): {args.image}")
    print(f"Motion Prompt:             {args.prompt}")
    print(f"Aspect Ratio:              {args.aspect_ratio}")
    print(f"Duration:                  {args.duration}s")
    print(f"Target Output:             {args.output}")
    print("=" * 70 + "\n")

    print("[VideoGen] 1/3 Uploading First Frame image to cloud storage...")
    image_url = upload_first_frame(args.image)
    print("[VideoGen] Uploaded successfully!")

    print("[VideoGen] 2/3 Submitting task to MiniMax-Hailuo-2.3 video model...")
    task_id = submit_video_job(
        image_url=image_url,
        prompt=args.prompt,
        aspect_ratio=args.aspect_ratio,
        duration=args.duration,
    )
    print(f"[VideoGen] Task created: {task_id}")

    print("[VideoGen] 3/3 Waiting for video generation...")
    poll_and_download_video(task_id, args.output)


if __name__ == "__main__":
    main()
