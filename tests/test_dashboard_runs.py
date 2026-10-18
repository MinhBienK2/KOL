"""Run discovery, view-model building and path-safety tests for the dashboard backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard import runs as runs_module
from tests.dashboard_fixtures import build_legacy_run, build_workspace_run


def test_discover_runs_finds_workspace_and_legacy(run_tree: dict):
    discovered = runs_module.discover_runs(run_tree["base_dir"])
    by_id = {item["run_id"]: item for item in discovered}

    assert run_tree["workspace_run_id"] in by_id
    assert run_tree["legacy_run_id"] in by_id
    assert by_id[run_tree["workspace_run_id"]]["layout"] == "workspace"
    assert by_id[run_tree["legacy_run_id"]]["layout"] == "legacy"
    assert by_id[run_tree["workspace_run_id"]]["total_stages"] == 8
    assert by_id[run_tree["workspace_run_id"]]["has_telemetry"] is True
    assert by_id[run_tree["legacy_run_id"]]["has_telemetry"] is False


def test_workspace_view_reports_telemetry_status_and_meta(run_tree: dict):
    run_ref = runs_module.resolve_run(run_tree["workspace_run_id"], run_tree["base_dir"])
    view = runs_module.build_view(run_ref)

    assert view["schema_version"] == 1
    run = view["run"]
    assert run["source"] == "telemetry"
    assert run["status"] == "completed"
    assert run["project_id"] == "campaign_demo"
    assert run["topic"] == "fashion_apparel"
    assert run["product_name"] == "Đầm xòe cherry"
    assert run["video_mode"] == "api"
    assert run["elapsed_seconds"] == 42.0
    assert run["completed_stages"] == 8
    assert len(view["stages"]) == 8
    assert [stage["stage"] for stage in view["stages"]] == list(range(1, 9))
    assert all(stage["status"] == "completed" for stage in view["stages"])
    assert view["stages"][6]["artifacts"], "stage 7 must list the master video artifact"


def test_legacy_run_derives_stage_status_from_artifacts(run_tree: dict):
    run_ref = runs_module.resolve_run(run_tree["legacy_run_id"], run_tree["base_dir"])
    view = runs_module.build_view(run_ref)

    assert view["run"]["source"] == "artifacts"
    statuses = {stage["stage"]: stage["status"] for stage in view["stages"]}
    assert statuses[1] == "completed"
    assert statuses[2] == "completed"
    assert statuses[3] == "completed"
    assert statuses[4] == "pending"
    assert statuses[8] == "pending"
    assert view["run"]["status"] in {"running", "unknown"}


def test_workspace_prompts_carry_api_parameters(run_tree: dict):
    view = runs_module.build_view(runs_module.resolve_run(run_tree["workspace_run_id"], run_tree["base_dir"]))
    prompts = {prompt["shot_id"]: prompt for prompt in view["prompts"]}

    assert "shot_01" in prompts
    prompt = prompts["shot_01"]
    assert prompt["prompt"].startswith("Framing: [WIDE_SHOT]")
    assert prompt["mode"] == "I2V"
    assert prompt["model"] == "MiniMax-Hailuo-2.3"
    assert prompt["task_id"] == "task-123"
    assert prompt["duration_requested"] == 6
    assert prompt["output_url"]
    assert prompt["segments"] and prompt["segments"][0]["text"]
    assert "Framing" in " ".join(segment["label"] for segment in prompt["segments"])


def test_legacy_prompts_fall_back_to_scene_plan(run_tree: dict):
    view = runs_module.build_view(runs_module.resolve_run(run_tree["legacy_run_id"], run_tree["base_dir"]))

    assert view["prompts"], "legacy runs must still expose scene_plan prompts"
    prompt = view["prompts"][0]
    assert prompt["shot_id"] == "shot_01"
    assert "Generate a [9:16] aspect ratio" in prompt["prompt"]
    assert prompt["task_id"] is None


def test_shots_join_storyboard_beats_and_media(run_tree: dict):
    view = runs_module.build_view(runs_module.resolve_run(run_tree["workspace_run_id"], run_tree["base_dir"]))
    shot = view["shots"][0]

    assert shot["shot_id"] == "shot_01"
    assert shot["beat_type"] == "hook"
    assert shot["spoken_text"].startswith("Đây là chiếc đầm")
    assert shot["on_screen_text"] == "ĐẦM XÒE CHERRY"
    assert shot["color_temp_kelvin"] == 5600
    assert shot["prompt"].startswith("Framing: [WIDE_SHOT]")

    assert shot["keyframe"]["exists"] is True
    assert shot["keyframe"]["url"].startswith("/api/runs/fashion_apparel/campaign_demo/file?path=")
    assert shot["clip"]["exists"] is True
    assert shot["synced"]["exists"] is True
    assert shot["voice"]["exists"] is True
    assert shot["render"]["task_id"] == "task-123"


def test_media_inventory_contains_master_and_thumbnail(run_tree: dict):
    view = runs_module.build_view(runs_module.resolve_run(run_tree["workspace_run_id"], run_tree["base_dir"]))
    kinds = {(item["label"], item["kind"], item["exists"]) for item in view["media"]}

    assert any(kind == "video" and exists for _, kind, exists in kinds)
    assert any(kind == "image" and exists for _, kind, exists in kinds)
    assert any(kind == "audio" for _, kind, _ in kinds)
    assert view["run"]["master_video_path"]
    assert view["render_report"]["overall_status"] == "PASSED"
    assert view["publish_log"]["hashtags"] == ["#DamXoeCherry"]
    assert view["gates"][0]["gate_name"] == "technical_integrity_gate"


def test_artifacts_are_reported_with_urls_and_sizes(run_tree: dict):
    view = runs_module.build_view(runs_module.resolve_run(run_tree["workspace_run_id"], run_tree["base_dir"]))
    by_name = {artifact["name"]: artifact for artifact in view["artifacts"]}

    assert by_name["scene_plan.json"]["exists"] is True
    assert by_name["scene_plan.json"]["size_bytes"] > 0
    assert "/file?path=" in by_name["scene_plan.json"]["url"]
    assert by_name["render_report.json"]["kind"] == "json"


def test_safe_resolve_allows_run_files_and_rejects_escapes(run_tree: dict):
    run_ref = runs_module.resolve_run(run_tree["workspace_run_id"], run_tree["base_dir"])

    resolved = runs_module.safe_resolve(run_ref, "artifacts/brief.json")
    assert resolved.name == "brief.json"
    assert resolved.exists()

    for escape in ("../../../../etc/passwd", "artifacts/../../../etc/passwd", "/etc/passwd"):
        with pytest.raises(runs_module.PathEscape):
            runs_module.safe_resolve(run_ref, escape)


def test_resolve_run_unknown_raises(run_tree: dict):
    with pytest.raises(runs_module.RunNotFound):
        runs_module.resolve_run("does_not_exist", run_tree["base_dir"])


def test_build_view_is_json_serializable(run_tree: dict):
    view = runs_module.build_view(runs_module.resolve_run(run_tree["workspace_run_id"], run_tree["base_dir"]))
    assert json.loads(json.dumps(view))


def test_missing_artifact_files_are_tolerated(tmp_path: Path):
    """A run whose artifacts reference deleted media must not crash the view builder."""
    base_dir = tmp_path / "output"
    base_dir.mkdir(parents=True, exist_ok=True)
    root = build_workspace_run(base_dir, project_id="campaign_broken")
    for stale in (root / "media" / "synced_clips").glob("*.mp4"):
        stale.unlink()
    (root / "artifacts" / "render_report.json").write_text("{not json", encoding="utf-8")

    view = runs_module.build_view(runs_module.resolve_run("fashion_apparel/campaign_broken", base_dir))
    assert view["render_report"] is None
    shot = view["shots"][0]
    assert shot["synced"]["exists"] is False
    assert shot["synced"]["url"] is None


def test_legacy_run_without_any_canonical_artifact_is_ignored(tmp_path: Path):
    base_dir = tmp_path / "output"
    (base_dir / "artifacts" / "not_a_run").mkdir(parents=True, exist_ok=True)
    (base_dir / "projects").mkdir(parents=True, exist_ok=True)
    build_legacy_run(base_dir, project_id="campaign_real")

    run_ids = [item["run_id"] for item in runs_module.discover_runs(base_dir)]
    assert run_ids == ["campaign_real"]
