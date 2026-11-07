#!/usr/bin/env python3
"""Standalone clip renderer for the Comfy Colab Kit gateway (Pika H3 Flex on MiniMax H3).

The pipeline renders Stage 5 through ``pipeline.video_engine``; this tool renders a single
clip from the command line, which is handy to try a prompt or a first frame without running
the whole director.

    python3 tools/generate_video.py --prompt "A slow push-in on a serum bottle"
    python3 tools/generate_video.py --image assets/characters/kol_main/portrait.png \
        --prompt "She turns to camera and smiles" --flow fl2va
    python3 tools/generate_video.py --ref face_anchor.png --prompt "..." --flow ref2va
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Allow standalone execution (`python tools/generate_video.py`) to import the pipeline.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline.comfy_video import (  # noqa: E402  (import after the sys.path bootstrap)
    FLOW_FL2VA,
    FLOW_REF2VA,
    FLOW_T2V,
    render_clip,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="ComfyUI gateway video clip renderer")
    parser.add_argument("--prompt", required=True, help="Motion / action prompt")
    parser.add_argument("--flow", default=FLOW_T2V, choices=[FLOW_T2V, FLOW_FL2VA, FLOW_REF2VA])
    parser.add_argument("--image", help="First frame image (fl2va)")
    parser.add_argument("--last-image", help="Last frame image (fl2va)")
    parser.add_argument("--ref", action="append", default=[], help="Reference image (ref2va), repeatable")
    parser.add_argument("--aspect-ratio", default="9:16", help="Aspect ratio when no first frame is given")
    parser.add_argument("--duration", type=float, default=6.0, help="Requested duration in seconds")
    parser.add_argument("--seed", type=int, help="Seed (default: the template's own seed)")
    parser.add_argument("--output", default="output/kol_video_clip.mp4", help="Output MP4 file path")
    parser.add_argument("--json", action="store_true", help="Print the run info as JSON")

    args = parser.parse_args()

    print("=" * 70)
    print("COMFYUI GATEWAY VIDEO CLIP (Pika H3 Flex / MiniMax H3)")
    print("=" * 70)
    print(f"Flow:        {args.flow}")
    print(f"First frame: {args.image or '-'}")
    print(f"Last frame:  {args.last_image or '-'}")
    print(f"References:  {args.ref or '-'}")
    print(f"Duration:    {args.duration}s")
    print(f"Output:      {args.output}")
    print("=" * 70)

    prompt_id, info = render_clip(
        args.flow,
        args.prompt,
        args.output,
        first_frame=args.image,
        last_frame=args.last_image,
        references=args.ref,
        duration=args.duration,
        aspect_ratio=args.aspect_ratio,
        seed=args.seed,
        filename_prefix="kol/manual_clip",
    )

    print(f"[VideoGen] DONE! prompt_id={prompt_id}")
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"[VideoGen] {info['width']}x{info['height']} · {info['length']} frames "
              f"({info['duration_seconds']}s) → {args.output}")


if __name__ == "__main__":
    main()
