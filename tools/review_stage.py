#!/usr/bin/env python3
"""CLI for Independent Subagent Stage Review & Rubric Evaluation.

Runs multi-dimensional review on pipeline artifacts (script, storyboard, keyframes),
computes 0-10 score against explicit rubrics, enforces maximum 3 review iterations,
and outputs actionable feedback for the producing agent.

Usage:
    python3 tools/review_stage.py --stage script --workspace <workspace_dir> --json
    python3 tools/review_stage.py --stage storyboard --workspace <workspace_dir> --json
    python3 tools/review_stage.py --stage keyframe --workspace <workspace_dir> --json
    python3 tools/review_stage.py --stage all --workspace <workspace_dir> --json

Exit codes:
    0: Approved (Score >= 8.0, ready for next stage)
    1: Fatal error / unhandled exception
    2: Missing prerequisite artifact
    3: Needs Revision (Score < 8.0, action items returned for refinement)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add repo root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.schemas import (
    AssetManifestArtifact,
    BriefArtifact,
    ScenePlanArtifact,
    ScriptArtifact,
)
from pipeline.stage_reviewer import (
    MAX_REVIEW_ITERATIONS,
    StageReviewResult,
    record_stage_review,
    review_keyframes,
    review_script,
    review_storyboard,
)

EXIT_APPROVED = 0
EXIT_FATAL = 1
EXIT_MISSING = 2
EXIT_NEEDS_REVISION = 3


def load_json_file(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent Stage Reviewer CLI")
    parser.add_argument(
        "--stage",
        required=True,
        choices=["script", "storyboard", "keyframe", "all"],
        help="Stage artifact to independently review",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Path to run workspace root (e.g. projects/<topic>/<campaign>/runs/v1)",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=None,
        help="Explicit path to artifacts directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print single JSON object to stdout",
    )

    args = parser.parse_args()

    # Determine artifacts directory
    if args.artifacts_dir:
        art_dir = Path(args.artifacts_dir)
    elif args.workspace:
        art_dir = Path(args.workspace) / "artifacts"
    else:
        art_dir = Path.cwd() / "artifacts"

    if not art_dir.exists():
        err_msg = f"Artifacts directory does not exist: {art_dir}"
        if args.json:
            print(json.dumps({"ok": False, "error": err_msg, "exit_code": EXIT_MISSING}, ensure_ascii=False))
        else:
            print(f"[REVIEW ERROR] {err_msg}", file=sys.stderr)
        return EXIT_MISSING

    results: list[StageReviewResult] = []

    try:
        # 1. Review Script
        if args.stage in ("script", "all"):
            script_file = art_dir / "script.json"
            brief_file = art_dir / "brief.json"
            if not script_file.is_file():
                if args.json:
                    print(json.dumps({"ok": False, "error": f"script.json missing in {art_dir}", "exit_code": EXIT_MISSING}))
                else:
                    print(f"[REVIEW ERROR] script.json missing in {art_dir}", file=sys.stderr)
                return EXIT_MISSING

            script_data = load_json_file(script_file)
            brief_data = load_json_file(brief_file) if brief_file.is_file() else {}
            res_script = review_script(script_data, brief=brief_data)
            record_stage_review(art_dir, res_script)
            results.append(res_script)

        # 2. Review Storyboard
        if args.stage in ("storyboard", "all"):
            scene_file = art_dir / "scene_plan.json"
            script_file = art_dir / "script.json"
            brief_file = art_dir / "brief.json"
            if not scene_file.is_file():
                if args.json:
                    print(json.dumps({"ok": False, "error": f"scene_plan.json missing in {art_dir}", "exit_code": EXIT_MISSING}))
                else:
                    print(f"[REVIEW ERROR] scene_plan.json missing in {art_dir}", file=sys.stderr)
                return EXIT_MISSING

            scene_data = load_json_file(scene_file)
            script_data = load_json_file(script_file) if script_file.is_file() else None
            brief_data = load_json_file(brief_file) if brief_file.is_file() else None
            res_sb = review_storyboard(scene_data, script=script_data, brief=brief_data)
            record_stage_review(art_dir, res_sb)
            results.append(res_sb)

        # 3. Review Keyframe
        if args.stage in ("keyframe", "all"):
            manifest_file = art_dir / "asset_manifest.json"
            scene_file = art_dir / "scene_plan.json"
            if not manifest_file.is_file():
                if args.json:
                    print(json.dumps({"ok": False, "error": f"asset_manifest.json missing in {art_dir}", "exit_code": EXIT_MISSING}))
                else:
                    print(f"[REVIEW ERROR] asset_manifest.json missing in {art_dir}", file=sys.stderr)
                return EXIT_MISSING

            manifest_data = load_json_file(manifest_file)
            scene_data = load_json_file(scene_file) if scene_file.is_file() else None
            res_kf = review_keyframes(manifest_data, scene_plan=scene_data)
            record_stage_review(art_dir, res_kf)
            results.append(res_kf)

    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc), "exit_code": EXIT_FATAL}, ensure_ascii=False))
        else:
            print(f"[REVIEW FATAL] {exc}", file=sys.stderr)
        return EXIT_FATAL

    # Aggregate outcome
    all_passed = all(r.passed for r in results)
    min_score = min((r.score for r in results), default=0.0)
    avg_score = round(sum(r.score for r in results) / len(results), 2) if results else 0.0

    payload = {
        "ok": all_passed,
        "status": "approved" if all_passed else "needs_revision",
        "exit_code": EXIT_APPROVED if all_passed else EXIT_NEEDS_REVISION,
        "average_score": avg_score,
        "min_score": min_score,
        "max_iterations": MAX_REVIEW_ITERATIONS,
        "stages_reviewed": [r.model_dump() for r in results],
        "all_problems": [p for r in results for p in r.problems],
        "all_actionable_feedback": [f for r in results for f in r.actionable_feedback],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print(f"INDEPENDENT STAGE REVIEW: {payload['status'].upper()} (Score: {avg_score}/10)")
        print("=" * 60)
        for r in results:
            print(f"[{r.stage.upper()}] Iteration {r.iteration} | Score: {r.score}/10 | Status: {r.status}")
            if r.problems:
                print("  Problems:")
                for p in r.problems:
                    print(f"    - {p}")
            if r.actionable_feedback:
                print("  Actionable Feedback:")
                for f in r.actionable_feedback:
                    print(f"    -> {f}")
        print("=" * 60)

    return EXIT_APPROVED if all_passed else EXIT_NEEDS_REVISION


if __name__ == "__main__":
    sys.exit(main())
