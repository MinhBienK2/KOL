#!/usr/bin/env python3
"""DramaClaw Production Shot Builder & Keyframe Generator (v2.0).

Features:
1. True Character Identity Locking:
   - Uploads reference images to /v1/media/storage/upload
   - Calls /v1/media/image with subject reference `file_list`
2. Seamless AI Watermark Removal:
   - Uses OpenCV Telea inpainting (cv2.inpaint) on high-contrast text mask
   - Completely removes watermark without slicing or distortion
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
CHARACTER_FILE = BASE_DIR / "assets" / "characters" / "kol_main" / "character.json"
API_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://aiapi.2tocom.space")
API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cu-hr7Y6QZPkzksXlfn74J4yeF_xmL9Rlubf_tAhD4Sgfw")


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
        file_url = res["data"]["file_url"]
        return file_url


def clean_watermark_inpaint(img_path: str | Path, out_path: str | Path) -> None:
    """Seamlessly inpaint and remove the MiniMax bottom-right watermark using OpenCV."""
    img = cv2.imread(str(img_path))
    if img is None:
        raise ValueError(f"Could not open image for watermark cleaning: {img_path}")
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
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated_mask_roi = cv2.dilate(mask_roi, kernel, iterations=2)

    full_mask = np.zeros((h, w), dtype=np.uint8)
    full_mask[box_y1:box_y2, box_x1:box_x2] = dilated_mask_roi

    # Inpaint using Telea algorithm
    clean_img = cv2.inpaint(img, full_mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
    cv2.imwrite(str(out_path), clean_img)


def generate_first_frame(
    scene_desc: str,
    output_path: str | Path,
    reference_image_path: str | Path | None = None,
    aspect_ratio: str = "1:1"
) -> bool:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_raw_path = output_path.with_name(f".raw_{output_path.name}")

    char = load_character()
    if not reference_image_path:
        reference_image_path = BASE_DIR / char["portrait_image"]

    print(f"[ShotBuilder] 1/3 Uploading reference image ({reference_image_path}) to OSS...")
    try:
        ref_file_url = upload_reference_image(reference_image_path)
        print(f"[ShotBuilder] Uploaded successfully! File URL acquired.")
    except Exception as e:
        print(f"[ShotBuilder] Upload error: {e}")
        return False

    # Build prompt focused on action and scene, keeping reference as subject authority
    prompt = (
        f"A photorealistic cinematic photograph of the exact character shown in the reference image. "
        f"Preserve exact facial features, hairstyle, and identity. "
        f"{char['appearance_details']}. "
        f"The character is {scene_desc}. "
        f"Cinematic natural lighting, 35mm lens, photorealistic 8k, high detail."
    )

    payload = {
        "model": "image-01",
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "file_list": [
            {
                "type": "character",
                "image_file": ref_file_url
            }
        ]
    }

    url = f"{API_BASE_URL.rstrip('/')}/v1/media/image"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        print("[ShotBuilder] 2/3 Invoking MiniMax Image API with Character Subject Reference...")
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=180) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            img_url = res["images"][0]["url"]
            print(f"[ShotBuilder] Image rendered successfully! Downloading raw output...")
            
            req_dl = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_dl) as dl_resp, open(temp_raw_path, "wb") as f:
                f.write(dl_resp.read())

        print("[ShotBuilder] 3/3 Applying OpenCV Telea Inpainting to remove watermark...")
        clean_watermark_inpaint(temp_raw_path, output_path)
        temp_raw_path.unlink(missing_ok=True)
        print(f"[ShotBuilder] DONE! Clean identity-locked First Frame saved to: {output_path}")
        return True
    except Exception as e:
        print(f"[ShotBuilder] Error generating image: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="DramaClaw Identity-Locked Shot Builder (v2.0)")
    parser.add_argument("--scene", required=True, help="Description of the scene/action")
    parser.add_argument("--ref", default=None, help="Custom reference image path (defaults to character portrait)")
    parser.add_argument("--aspect-ratio", default="1:1", choices=["1:1", "16:9", "9:16", "4:3", "3:4"], help="Aspect ratio")
    parser.add_argument("--output", default="output/first_frame_clean.png", help="Output file path for the first frame")
    
    args = parser.parse_args()
    generate_first_frame(
        scene_desc=args.scene,
        output_path=args.output,
        reference_image_path=args.ref,
        aspect_ratio=args.aspect_ratio
    )


if __name__ == "__main__":
    main()
