#!/usr/bin/env python3
"""Reference Selector Utility for AI Video & Image Generation.

Helper script to query and prepare reference images for character-consistent
video generation pipelines (DramaClaw / OpenMontage / Kling / Wan / Seedance).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_config() -> dict:
    config_path = Path(__file__).parent / "character_config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_references(
    shot_type: str | None = None,
    expression: str | None = None,
    view: str | None = None,
) -> list[dict]:
    config = load_config()
    results = []
    base_dir = Path(__file__).parent

    for filename, info in config.get("references", {}).items():
        score = 0
        if shot_type and any(shot_type.lower() in s.lower() for s in info.get("recommended_shots", [])):
            score += 3
        if expression and expression.lower() in info.get("expression", "").lower():
            score += 2
        if view and view.lower() in info.get("view", "").lower():
            score += 2

        if score > 0 or (not shot_type and not expression and not view):
            results.append({
                "file": filename,
                "path": str(base_dir / filename),
                "score": score,
                "info": info
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Query reference images for character consistency")
    parser.add_argument("--shot", help="Shot type (e.g. talking_head, dialogue, cafe_scene, wide_shot, hero)")
    parser.add_argument("--expression", help="Expression (e.g. smiling, speaking, surprised, calm)")
    parser.add_argument("--view", help="View/Angle (e.g. front, three_quarter, profile, back)")
    parser.add_argument("--pipeline", choices=["dramaclaw", "openmontage", "kling", "seedance"], default="openmontage")
    args = parser.parse_args()

    config = load_config()
    base_dir = Path(__file__).parent

    print(f"=== Character Consistency Reference Selection ({args.pipeline.upper()}) ===")
    print(f"Character: {config['name']} ({config['character_id']})")
    print(f"Primary Face Anchor: {base_dir / config['anchors']['face_anchor']}")
    print(f"4-Panel Turnaround Sheet: {base_dir / config['anchors']['turnaround_sheet_4panel']}\n")

    matches = find_references(args.shot, args.expression, args.view)
    if matches:
        print(f"Found {len(matches)} matching reference(s):")
        for m in matches[:5]:
            print(f" - [{m['file']}] (Score: {m['score']})")
            print(f"   View: {m['info']['view']}, Framing: {m['info']['framing']}, Expression: {m['info']['expression']}")
            print(f"   Recommended: {', '.join(m['info']['recommended_shots'])}")
    else:
        print("No specific match found, fallback to Face Anchor + Front 0 deg.")


if __name__ == "__main__":
    main()
