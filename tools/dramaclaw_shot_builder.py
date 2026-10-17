#!/usr/bin/env python3
"""DramaClaw Production Shot Builder & Keyframe Generator.

Builds production-grade prompts and generates First Frame keyframes for Video I2V
using DramaClaw identity-locking specifications and MiniMax API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from PIL import Image, ImageFilter
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
CHARACTER_FILE = BASE_DIR / "assets" / "characters" / "kol_main" / "character.json"
API_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://aiapi.2tocom.space")
API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cu-hr7Y6QZPkzksXlfn74J4yeF_xmL9Rlubf_tAhD4Sgfw")


def load_character() -> dict:
    with open(CHARACTER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_dramaclaw_prompt(scene_desc: str, shot_type: str = "medium_shot", mood: str = "cinematic daylight") -> str:
    char = load_character()
    prompt = f"""[DRAMACLAW IDENTITY-LOCKED SCENE SPECIFICATION]

[ATTACHED ASSET REFERENCES]:
Image 1 = Primary Face Anchor: {char['portrait_image']} (1:1 neutral face, jawline, eye shape, nose, hair)
Image 2 = Multi-view Character Sheet: {char['identities'][0]['reference_sheet']} (4-panel turnaround)

[HARD CONSTRAINTS (CRITICAL - DRAMACLAW SPEC)]:
- The person in the output image MUST maintain exact identity from Image 1 and Image 2.
- Preserve facial structure: refined oval shape, collarbone-length straight black hair, soft double eyelids, almond dark-brown eyes, straight nose bridge, natural skin tone.
- Preserve costume: {char['appearance_details']}
- NEVER copy the board layout, panel dividers, collage grid, or poses from Image 2 into the generated scene.
- Produce ONE single cohesive photographic scene frame. NO multiple people, NO text, NO watermarks.

[SHOT DIRECTION]:
- Framing: {shot_type}
- Lighting & Mood: {mood}
- Action / Scene: The character {char['character_tag']} ({char['name']}) is {scene_desc}
- Photography: 35mm cinematic lens, f/2.0 aperture, natural depth of field, 8k photorealistic quality, color graded.
"""
    return prompt.strip()


def remove_corner_watermark(img_path: str | Path, out_path: str | Path, corner_w: int = 280, corner_h: int = 90) -> None:
    im = Image.open(img_path)
    w, h = im.size
    clean_im = im.copy()
    
    # Sample background right above the bottom-right watermark region
    above_patch = im.crop((w - corner_w, h - corner_h * 2, w, h - corner_h))
    # Smooth patch blend
    clean_im.paste(above_patch, (w - corner_w, h - corner_h))
    clean_im.save(out_path, quality=95)


def generate_first_frame(prompt: str, output_path: str | Path) -> bool:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".tmp_{output_path.name}")
    
    url = f"{API_BASE_URL.rstrip('/')}/v1/images/generations"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": prompt,
        "model": "image-01"
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    
    try:
        print("[ShotBuilder] Calling MiniMax Image API (image-01)...")
        with urllib.request.urlopen(req, timeout=120) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            img_url = res["data"][0]["url"]
            print(f"[ShotBuilder] Image generated successfully! Downloading from OSS...")
            urllib.request.urlretrieve(img_url, temp_path)
            
            # Auto clean watermark
            print(f"[ShotBuilder] Cleaning corner watermark...")
            remove_corner_watermark(temp_path, output_path)
            temp_path.unlink(missing_ok=True)
            print(f"[ShotBuilder] Clean First Frame saved to: {output_path}")
            return True
    except Exception as e:
        print(f"[ShotBuilder] Error generating image: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="DramaClaw Production Shot Builder")
    parser.add_argument("--scene", required=True, help="Description of the scene/action")
    parser.add_argument("--shot-type", default="medium shot", help="Shot scale: close-up, medium shot, full shot, over-the-shoulder")
    parser.add_argument("--mood", default="soft morning light in modern minimalist setting", help="Lighting and atmosphere")
    parser.add_argument("--output", default="output/first_frame_shot_01.png", help="Output file path for the first frame")
    parser.add_argument("--generate", action="store_true", help="Directly invoke MiniMax image API to render First Frame")
    
    args = parser.parse_args()
    prompt = build_dramaclaw_prompt(args.scene, args.shot_type, args.mood)
    
    print("\n" + "=" * 70)
    print("DRAMACLAW IDENTITY-LOCKED PROMPT:")
    print("=" * 70)
    print(prompt)
    print("=" * 70 + "\n")
    
    if args.generate:
        generate_first_frame(prompt, args.output)
    else:
        print(f"[Tip] Add --generate to render this First Frame with MiniMax API.")
        print(f"[Tip] Or copy the prompt into Midjourney, FLUX.2, or Gemini with Image 1 & Image 2 attached.")


if __name__ == "__main__":
    main()
