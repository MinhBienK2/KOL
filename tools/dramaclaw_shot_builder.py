#!/usr/bin/env python3
"""DramaClaw Production Shot Builder & Keyframe Generator (v3.0).

Features:
1. True Character Identity Locking with Flow2API (Gemini Image Flash / Nano Banana):
   - Supports multimodal reference image input directly via OpenAI-compatible chat completions
   - High-fidelity identity matching and photorealistic 2K rendering
2. Legacy MiniMax image-01 Fallback Support
3. Watermark Cleaning:
   - Uses OpenCV Telea inpainting on output if any watermark detected
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import base64
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import cv2
import numpy as np
from PIL import Image

from pipeline.config import (
    DEFAULT_IMAGE_MODEL,
    FLOW2API_API_KEY,
    FLOW2API_BASE_URL,
    MINIMAX_API_KEY,
    MINIMAX_BASE_URL,
)

BASE_DIR = Path(__file__).resolve().parent.parent
CHARACTER_FILE = BASE_DIR / "assets" / "characters" / "kol_main" / "character.json"

ASPECT_RATIO_MODEL_MAP = {
    "16:9": "gemini-3.1-flash-image-landscape-2k",
    "9:16": "gemini-3.1-flash-image-portrait-2k",
    "1:1": "gemini-3.1-flash-image-square-2k",
    "4:3": "gemini-3.1-flash-image-four-three-2k",
    "3:4": "gemini-3.1-flash-image-three-four-2k",
}


def load_character() -> dict:
    with open(CHARACTER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def upload_reference_image(image_path: str | Path) -> str:
    """Uploads a local image to MiniMax temporary OSS storage to obtain file_url."""
    path = Path(image_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"Reference image not found: {path}")

    boundary = "----WebKitFormBoundaryShotBuilder7MA4YWxk"
    with open(path, "rb") as f:
        file_bytes = f.read()

    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode("utf-8"))
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    url = f"{MINIMAX_BASE_URL.rstrip('/')}/v1/media/storage/upload"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        file_url = res["data"]["file_url"]
        return file_url


# A real watermark is a thin text/logo stroke. If the bright mask covers more than this
# share of the corner ROI the corner is bright *content* (white product, studio backdrop),
# and inpainting it would smear the subject, so we leave it untouched.
WATERMARK_MAX_ROI_COVERAGE = 0.25


def inpaint_watermark_array(img: np.ndarray) -> tuple[np.ndarray, int]:
    """Telea-inpaint the bottom-right watermark of a BGR image.

    Returns (image, inpainted_pixel_count). Count is 0 when no watermark-like mark is
    found or when the corner is bright content rather than a thin overlay.
    """
    h, w = img.shape[:2]

    # Watermark box in bottom-right corner (approx 950px wide, 200px high on 2048x2048)
    box_x1 = max(0, w - int(w * 0.48))
    box_x2 = w
    box_y1 = max(0, h - int(h * 0.10))
    box_y2 = h
    corner_roi = img[box_y1:box_y2, box_x1:box_x2]
    gray_roi = cv2.cvtColor(corner_roi, cv2.COLOR_BGR2GRAY)

    # White text threshold
    _, mask_roi = cv2.threshold(gray_roi, 205, 255, cv2.THRESH_BINARY)
    if mask_roi.size == 0 or not mask_roi.any():
        return img, 0
    if (mask_roi > 0).mean() > WATERMARK_MAX_ROI_COVERAGE:
        return img, 0
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated_mask_roi = cv2.dilate(mask_roi, kernel, iterations=2)

    full_mask = np.zeros((h, w), dtype=np.uint8)
    full_mask[box_y1:box_y2, box_x1:box_x2] = dilated_mask_roi

    # Inpaint using Telea algorithm
    clean_img = cv2.inpaint(img, full_mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
    return clean_img, int((full_mask > 0).sum())


def clean_watermark_inpaint(img_path: str | Path, out_path: str | Path) -> int:
    """Seamlessly inpaint and remove the bottom-right watermark using OpenCV.

    Returns the number of inpainted pixels (0 = nothing watermark-like found).
    """
    img = cv2.imread(str(img_path))
    if img is None:
        raise ValueError(f"Could not open image for watermark cleaning: {img_path}")
    clean_img, pixels = inpaint_watermark_array(img)
    cv2.imwrite(str(out_path), clean_img)
    return pixels


def generate_first_frame(
    scene_desc: str,
    output_path: str | Path,
    reference_image_path: str | Path | None = None,
    aspect_ratio: str = "9:16",
    model: str | None = None,
    provider: str = "flow2api",
) -> bool:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    char = load_character()
    if not reference_image_path:
        reference_image_path = BASE_DIR / char.get("portrait_image", "assets/characters/kol_main/portrait.png")
    else:
        reference_image_path = Path(reference_image_path)
        if not reference_image_path.is_absolute():
            reference_image_path = BASE_DIR / reference_image_path

    if not reference_image_path.exists():
        print(f"[ShotBuilder] Error: Reference image not found: {reference_image_path}")
        return False

    prompt = (
        f"A cinematic high-fidelity photorealistic photograph of the exact same character shown in the reference image. "
        f"Preserve her exact facial structure, eye shape, nose bridge, lips, skin tone, and signature hairstyle. "
        f"{char.get('appearance_details', '')}. "
        f"The character is {scene_desc}. "
        f"Professional studio lighting, 35mm lens, high detail, photorealistic 8k quality, masterclass cinematography."
    )

    if provider == "flow2api":
        selected_model = model or ASPECT_RATIO_MODEL_MAP.get(aspect_ratio, DEFAULT_IMAGE_MODEL)
        print(f"[ShotBuilder] 1/2 Invoking Flow2API with model '{selected_model}' and reference '{reference_image_path.name}'...")
        try:
            b64_img = base64.b64encode(reference_image_path.read_bytes()).decode("utf-8")
            payload = {
                "model": selected_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}},
                        ],
                    }
                ],
            }
            req = urllib.request.Request(
                f"{FLOW2API_BASE_URL}/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Authorization": f"Bearer {FLOW2API_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=240) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                content = res["choices"][0]["message"]["content"]
                m = re.search(r'\((https?://[^\)]+)\)', content)
                if not m:
                    raise ValueError(f"No image URL found in Flow2API response: {content[:200]}")
                img_url = m.group(1)
                print(f"[ShotBuilder] Image rendered successfully! Downloading to {output_path}...")
                urllib.request.urlretrieve(img_url, output_path)

            clean_watermark_inpaint(output_path, output_path)
            print(f"[ShotBuilder] DONE! Clean identity-locked Keyframe saved to: {output_path}")
            return True
        except Exception as e:
            print(f"[ShotBuilder] Flow2API generation failed: {e}. Falling back to MiniMax...")

    # Fallback: MiniMax image-01
    temp_raw_path = output_path.with_name(f".raw_{output_path.name}")
    print(f"[ShotBuilder] 1/3 Uploading reference image ({reference_image_path}) to MiniMax OSS...")
    try:
        ref_file_url = upload_reference_image(reference_image_path)
    except Exception as e:
        print(f"[ShotBuilder] MiniMax OSS Upload error: {e}")
        return False

    payload = {
        "model": "image-01",
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "file_list": [{"type": "character", "image_file": ref_file_url}],
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        print("[ShotBuilder] 2/3 Invoking MiniMax Image API (Fallback)...")
        req = urllib.request.Request(
            f"{MINIMAX_BASE_URL}/v1/media/image",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            task_id = res.get("task_id")
            img_url = None
            if task_id:
                import time
                for _ in range(60):
                    time.sleep(2)
                    q_req = urllib.request.Request(f"{MINIMAX_BASE_URL}/v1/media/image/jobs/{task_id}", headers=headers)
                    with urllib.request.urlopen(q_req, timeout=30) as q_resp:
                        q_res = json.loads(q_resp.read().decode("utf-8"))
                        if q_res.get("status") == "Success":
                            img_url = q_res["images"][0]["url"]
                            break
            elif "images" in res:
                img_url = res["images"][0]["url"]

            if not img_url:
                raise RuntimeError(f"MiniMax image URL acquisition failed: {res}")

            req_dl = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_dl) as dl_resp, open(temp_raw_path, "wb") as f:
                f.write(dl_resp.read())

        clean_watermark_inpaint(temp_raw_path, output_path)
        temp_raw_path.unlink(missing_ok=True)
        print(f"[ShotBuilder] DONE! First Frame saved to: {output_path}")
        return True
    except Exception as e:
        print(f"[ShotBuilder] MiniMax fallback error: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="DramaClaw Identity-Locked Shot Builder (v3.0 - Flow2API Default)")
    parser.add_argument("--scene", required=True, help="Description of the scene/action")
    parser.add_argument("--ref", default=None, help="Custom reference image path (defaults to character portrait)")
    parser.add_argument("--aspect-ratio", default="9:16", choices=["1:1", "16:9", "9:16", "4:3", "3:4"], help="Aspect ratio (default: 9:16)")
    parser.add_argument("--model", default=None, help="Specific model override (defaults to aspect ratio auto-selection from Flow2API)")
    parser.add_argument("--provider", default="flow2api", choices=["flow2api", "minimax"], help="Image generation provider (default: flow2api)")
    parser.add_argument("--output", default="output/first_frame_clean.png", help="Output file path for the first frame")
    
    args = parser.parse_args()
    generate_first_frame(
        scene_desc=args.scene,
        output_path=args.output,
        reference_image_path=args.ref,
        aspect_ratio=args.aspect_ratio,
        model=args.model,
        provider=args.provider,
    )

if __name__ == "__main__":
    main()
