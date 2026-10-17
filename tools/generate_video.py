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
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
API_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://aiapi.2tocom.space")
API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cu-hr7Y6QZPkzksXlfn74J4yeF_xmL9Rlubf_tAhD4Sgfw")


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

    with urllib.request.urlopen(req, timeout=60) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res["data"]["file_url"]


def submit_video_job(
    image_url: str,
    prompt: str,
    aspect_ratio: str = "9:16",
    duration: int = 6,
    model: str = "MiniMax-Hailuo-2.3"
) -> str:
    url = f"{API_BASE_URL.rstrip('/')}/v1/media/video"
    payload = {
        "model": model,
        "prompt": prompt,
        "input_image": image_url,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res["task_id"]


def poll_and_download_video(task_id: str, output_path: str | Path, timeout_seconds: int = 300) -> str:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    poll_url = f"{API_BASE_URL.rstrip('/')}/v1/media/video/{task_id}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Bearer {API_KEY}",
    }

    start = time.time()
    print(f"[VideoGen] Polling video task {task_id} (timeout {timeout_seconds}s)...")
    while time.time() - start < timeout_seconds:
        req = urllib.request.Request(poll_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            status = res.get("status")
            elapsed = int(time.time() - start)
            print(f"[{elapsed:3d}s] Task status: {status}")

            if status == "Success":
                video_url = res.get("video_url") or res.get("url")
                if not video_url:
                    raise RuntimeError(f"Success status received but no video URL found in: {res}")
                print(f"[VideoGen] Video rendered! Downloading to {output_path}...")
                urllib.request.urlretrieve(video_url, output_path)
                print(f"[VideoGen] DONE! Video saved: {output_path} ({output_path.stat().st_size // 1024} KB)")
                return str(output_path)
            elif status in ("Fail", "Failed"):
                raise RuntimeError(f"Video generation failed: {res}")

        time.sleep(10)

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
