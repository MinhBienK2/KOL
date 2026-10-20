#!/usr/bin/env python3
"""Convenience CLI wrapper for Chief AI Commercial Director."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.archetypes import ProductArchetype
from pipeline.director import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_PAUSED,
    load_json_arg,
    resolve_character_path,
    run_pipeline,
)
from pipeline.workspace import ProjectWorkspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chief AI Commercial Director Autonomous Pipeline CLI"
    )
    parser.add_argument(
        "--campaign",
        default="campaign_lumina_mug_01",
        help="Campaign ID (defaults to campaign_lumina_mug_01)",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Project ID (alias for campaign ID)",
    )
    parser.add_argument(
        "--product",
        default="Ly Giữ Nhiệt Thông Minh Lumina Pro",
        help="Product name",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Affiliate link or raw product description",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Domain topic or product archetype (e.g. fashion_apparel, tech_gadgets, general_commercial)",
    )
    parser.add_argument(
        "--archetype",
        default=None,
        choices=[a.value for a in ProductArchetype],
        help="Directorial archetype (alias for topic)",
    )
    parser.add_argument(
        "--video-mode",
        default="api",
        choices=["ffmpeg", "api", "auto"],
        help="Video generator mode",
    )
    parser.add_argument(
        "--from-stage",
        type=int,
        default=1,
        choices=range(1, 9),
        help="Resume from stage (1-8)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Run version (e.g. v1, v2; defaults to active version or v1)",
    )
    parser.add_argument(
        "--new-version",
        action="store_true",
        help="Branch a new incremental run version (e.g. v2) inheriting assets via hardlinks",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory root",
    )

    direct = parser.add_argument_group("agent direction (all optional)")
    direct.add_argument("--beats", metavar="PATH.json", default=None,
                        help="Stage 2: directed script beats (JSON list); validated strictly")
    direct.add_argument("--shot-overrides", metavar="PATH.json", default=None,
                        help="Stage 3: per-shot overrides for the scene plan (JSON)")
    direct.add_argument("--references", metavar="PATH.json", default=None,
                        help="Stage 4: reference_overrides for keyframe generation (JSON)")
    direct.add_argument("--character", metavar="PATH_OR_ID", default=None,
                        help="Stage 3/4: character.json path, character directory, or persona id under assets/characters/")
    direct.add_argument("--strict-resolution", action="store_true",
                        help="Stage 4: fail instead of accepting low-resolution character references")
    direct.add_argument("--strict-tts", action="store_true",
                        help="Stage 6: fail instead of falling back to a degraded TTS voice")
    direct.add_argument("--transitions", metavar="PATH.json", default=None,
                        help="Stage 7: transitions list (default: per-beat 'transition' fields in script.json)")
    direct.add_argument("--pause-after-stage", type=int, default=None, choices=range(1, 8), metavar="N",
                        help="Human checkpoint: stop cleanly after stage N (1-7), status 'paused', exit code 4; "
                             "resume with --from-stage N+1")
    direct.add_argument("--offline", action="store_true",
                        help="No network: sets KOL_OFFLINE=1 and forces --video-mode ffmpeg")
    direct.add_argument("--result-json", metavar="PATH", default=None,
                        help="Also copy the machine-readable run result (run_result.json) to PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the pipeline. Exit codes: 0 completed, 1 failed, 4 paused (--pause-after-stage)."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.offline:
        os.environ["KOL_OFFLINE"] = "1"
        args.video_mode = "ffmpeg"

    try:
        beats = load_json_arg(args.beats, "--beats")
        shot_overrides = load_json_arg(args.shot_overrides, "--shot-overrides")
        reference_overrides = load_json_arg(args.references, "--references")
        transitions = load_json_arg(args.transitions, "--transitions")
        character_path = resolve_character_path(args.character)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    project_id = args.project_id or args.campaign
    topic = args.topic or args.archetype
    base_dir = Path(args.out_dir) if args.out_dir else None
    workspace = ProjectWorkspace.from_campaign_id(
        campaign_id=project_id,
        topic=topic,
        version=args.version,
        base_dir=base_dir,
    )
    if args.new_version:
        workspace = workspace.create_next_version()
    workspace.ensure_dirs()

    # Print clean project path output: projects/{topic}/{project_id}/
    print(f"projects/{workspace.topic}/{workspace.project_id}/runs/{workspace.version}/")
    print(f"projects/{workspace.topic}/{workspace.project_id}/")
    result: dict = {}
    ok = run_pipeline(
        campaign_id=project_id,
        project_id=project_id,
        product_name=args.product,
        product_url_or_query=args.url,
        archetype=topic,
        topic=topic,
        video_mode=args.video_mode,
        resume_from_stage=args.from_stage,
        output_dir=base_dir,
        workspace=workspace,
        beats=beats,
        shot_overrides=shot_overrides,
        reference_overrides=reference_overrides,
        character_path=character_path,
        strict_resolution=args.strict_resolution,
        transitions=transitions,
        strict_tts=args.strict_tts,
        pause_after_stage=args.pause_after_stage,
        result=result,
    )
    if args.result_json and result:
        Path(args.result_json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if result.get("status") == "paused":
        return EXIT_PAUSED
    return EXIT_OK if ok else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
