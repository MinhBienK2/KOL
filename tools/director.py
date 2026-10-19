#!/usr/bin/env python3
"""Convenience CLI wrapper for Chief AI Commercial Director."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.archetypes import ProductArchetype
from pipeline.director import run_pipeline
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
