"""Offline tests: paid-generation estimate, --max-video-jobs cap and --check estimate (round 4)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.cost import estimate_for_workspace, estimate_paid_generation, load_unit_costs
from pipeline.schemas import AssetManifestArtifact, KeyframeAsset, ScenePlanArtifact, ScriptArtifact, StoryboardShot
from pipeline.video_engine import build_clip_request, clip_cache_status
from pipeline.workspace import ProjectWorkspace
from tests.test_helpers import create_test_clip
from tools.director import EXIT_INVALID_INPUT, EXIT_OK, main as cli_main

PORTRAIT = Path("assets/characters/kol_main/portrait.png")


def _shot(n: int, duration: float = 5.0) -> StoryboardShot:
    return StoryboardShot(
        shot_id=f"shot_{n:02d}", scene_id=f"s{n}", shot_type="Medium", angle="eye", camera_motion="push",
        lighting="soft", style_constraints="none", scene_description="d", prompt_6part=f"prompt {n}",
        estimated_duration=duration,
    )


def _beat(text: str) -> dict:
    return {"scene_id": "s", "beat_type": "hook", "spoken_text": text, "on_screen_text": "x",
            "visual_cue": "v", "estimated_duration": 4.0}


def _artifacts(ws: ProjectWorkspace, durations=(5.0, 5.0, 10.0), speech=("Xin chao", "", "Mua ngay")):
    plan = ScenePlanArtifact(campaign_id="c1", shots=[_shot(i + 1, d) for i, d in enumerate(durations)])
    manifest = AssetManifestArtifact(
        campaign_id="c1", keyframes=[KeyframeAsset(shot_id=s.shot_id) for s in plan.shots]
    )
    script = ScriptArtifact(
        campaign_id="c1", product_name="P", target_duration=15.0, beats=[_beat(t) for t in speech]
    )
    ws.save_artifact("scene_plan.json", plan)
    ws.save_artifact("asset_manifest.json", manifest)
    ws.save_artifact("script.json", script)
    return plan, manifest, script


@pytest.fixture
def ws(tmp_path: Path) -> ProjectWorkspace:
    w = ProjectWorkspace(topic="general_commercial", project_id="c1", base_dir=tmp_path)
    w.ensure_dirs()
    return w


def _cache_clip(ws: ProjectWorkspace, shot: StoryboardShot) -> None:
    """A valid cached diffusion clip whose fingerprint matches the shot's request."""
    clip = ws.raw_clips_dir / f"{shot.shot_id}.mp4"
    create_test_clip(PORTRAIT, clip, duration=3.0)
    fp = build_clip_request(shot.shot_id, shot.prompt_6part, duration=shot.estimated_duration).fingerprint
    clip.with_suffix(".meta.json").write_text(json.dumps({"fingerprint": fp}), encoding="utf-8")
    assert clip_cache_status(clip, fp) == "hit"


def test_estimate_counts_jobs_tts_and_seconds(ws: ProjectWorkspace):
    plan, manifest, script = _artifacts(ws)
    est = estimate_paid_generation(plan, manifest, script, ws.raw_clips_dir, unit_costs={})
    assert est["video_jobs"] == 3 and est["video_jobs_cached"] == 0
    assert est["video_seconds"] == 6 + 6 + 10  # normalized Hailuo durations
    assert est["tts_calls"] == 2  # the empty-text beat is silence, not a paid call
    assert est["image_calls"] == 0
    assert est["total_generated_seconds"] == est["video_seconds"] + est["tts_seconds"] == 30.0
    assert est["estimated_cost"] is None  # prices unknown by default
    assert set(est["unpriced_models"]) == {"MiniMax-Hailuo-2.3", "tts-1"}
    json.dumps(est)


def test_estimate_skips_cached_shots(ws: ProjectWorkspace):
    plan, manifest, script = _artifacts(ws)
    _cache_clip(ws, plan.shots[0])
    est = estimate_paid_generation(plan, manifest, script, ws.raw_clips_dir, unit_costs={})
    assert est["video_jobs"] == 2 and est["video_jobs_cached"] == 1
    assert [j["shot_id"] for j in est["jobs"]] == ["shot_02", "shot_03"]


def test_stale_cache_is_resubmitted(ws: ProjectWorkspace):
    plan, manifest, script = _artifacts(ws)
    _cache_clip(ws, plan.shots[0])
    ws.raw_clips_dir.joinpath("shot_01.meta.json").write_text(json.dumps({"fingerprint": "old"}), encoding="utf-8")
    est = estimate_paid_generation(plan, manifest, script, ws.raw_clips_dir, unit_costs={})
    assert est["video_jobs"] == 3


def test_ffmpeg_mode_and_offline_are_free(ws: ProjectWorkspace, monkeypatch: pytest.MonkeyPatch):
    plan, manifest, script = _artifacts(ws)
    est = estimate_paid_generation(plan, manifest, script, ws.raw_clips_dir, video_mode="ffmpeg", unit_costs={})
    assert est["video_jobs"] == 0 and est["tts_calls"] == 2  # TTS still paid unless offline
    monkeypatch.setenv("KOL_OFFLINE", "1")
    est = estimate_paid_generation(plan, manifest, script, ws.raw_clips_dir, video_mode="auto", unit_costs={})
    assert (est["video_jobs"], est["tts_calls"], est["paid_calls"], est["estimated_cost"]) == (0, 0, 0, 0.0)


def test_unit_cost_table_prices_jobs(ws: ProjectWorkspace):
    plan, manifest, script = _artifacts(ws)
    table = {"currency": "USD", "MiniMax-Hailuo-2.3": {"per_second": 0.1}, "tts-1": 0.05}
    est = estimate_paid_generation(plan, manifest, script, ws.raw_clips_dir, unit_costs=table)
    assert est["currency"] == "USD"
    assert est["estimated_cost"] == pytest.approx(22 * 0.1 + 2 * 0.05)
    assert est["unpriced_models"] == []
    assert est["by_model"]["MiniMax-Hailuo-2.3"]["calls"] == 3
    partial = estimate_paid_generation(
        plan, manifest, script, ws.raw_clips_dir, unit_costs={"MiniMax-Hailuo-2.3": {"per_job": 1}}
    )
    assert partial["estimated_cost"] is None and partial["unpriced_models"] == ["tts-1"]


def test_unit_costs_from_env_json_and_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert load_unit_costs() == {}
    monkeypatch.setenv("KOL_UNIT_COSTS", '{"tts-1": {"per_call": 0.2}}')
    assert load_unit_costs()["tts-1"]["per_call"] == 0.2
    f = tmp_path / "costs.json"
    f.write_text('{"x": 1}', encoding="utf-8")
    monkeypatch.setenv("KOL_UNIT_COSTS", str(f))
    assert load_unit_costs() == {"x": 1}


def test_estimate_for_workspace_unavailable_until_artifacts_exist(ws: ProjectWorkspace):
    est = estimate_for_workspace(ws, "api", [1, 2, 3, 4, 5, 6, 7, 8])
    assert est["available"] is False and est["video_jobs"] is None
    _artifacts(ws)
    est = estimate_for_workspace(ws, "api", [5, 6, 7, 8])
    assert est["available"] is True and est["video_jobs"] == 3
    only_compose = estimate_for_workspace(ws, "api", [7, 8])
    assert only_compose["video_jobs"] == 0 and only_compose["tts_calls"] == 0


# ------------------------------------------------------------------ CLI


def _cli(tmp_path: Path, *extra: str) -> int:
    return cli_main(["--campaign", "c1", "--topic", "general_commercial", "--out-dir", str(tmp_path), *extra])


def test_check_includes_estimate_unavailable_on_fresh_project(tmp_path: Path, capsys: pytest.CaptureFixture):
    assert _cli(tmp_path, "--check", "--json") == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["estimate"]["available"] is False
    assert payload["estimate"]["video_jobs"] is None


def test_check_includes_estimate_and_flags_cap(ws: ProjectWorkspace, tmp_path: Path, capsys: pytest.CaptureFixture):
    _artifacts(ws)
    assert _cli(tmp_path, "--check", "--from-stage", "5", "--json") == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["estimate"]["video_jobs"] == 3 and payload["estimate"]["tts_calls"] == 2

    code = _cli(tmp_path, "--check", "--from-stage", "5", "--max-video-jobs", "2", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_INVALID_INPUT
    assert payload["max_video_jobs"] == 2 and "--max-video-jobs 2" in payload["error"]


def test_negative_cap_is_rejected(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        _cli(tmp_path, "--max-video-jobs", "-1")
    assert exc.value.code == 2


def _patch_stages():
    names = ["render_all_video_clips", "produce_all_audio_and_lip_sync", "compose_master_commercial",
             "run_all_verification_gates"]
    return {n: patch(f"pipeline.director.{n}") for n in names}


def test_cap_exceeded_aborts_before_any_submit(ws: ProjectWorkspace, tmp_path: Path, capsys: pytest.CaptureFixture):
    _artifacts(ws)
    patches = _patch_stages()
    mocks = {n: p.start() for n, p in patches.items()}
    try:
        with patch("tools.generate_video.submit_video_job") as submit, \
             patch("pipeline.video_engine.upload_first_frame") as upload:
            code = _cli(tmp_path, "--from-stage", "5", "--max-video-jobs", "2", "--json")
        out = capsys.readouterr()
    finally:
        for p in patches.values():
            p.stop()
    payload = json.loads(out.out)
    assert code == EXIT_INVALID_INPUT == 2
    assert payload["status"] == "budget_exceeded"
    assert payload["error_code"] == "max_video_jobs_exceeded"
    assert payload["estimate"]["video_jobs"] == 3
    assert payload["resume_hint"] == "--from-stage 5"
    mocks["render_all_video_clips"].assert_not_called()
    submit.assert_not_called()
    upload.assert_not_called()
    saved = json.loads((ws.root / "run_result.json").read_text(encoding="utf-8"))
    assert saved["status"] == "budget_exceeded" and saved["estimate"]["video_jobs"] == 3


def test_within_cap_runs_and_records_estimate(ws: ProjectWorkspace, tmp_path: Path, capsys: pytest.CaptureFixture):
    _artifacts(ws)
    patches = _patch_stages()
    mocks = {n: p.start() for n, p in patches.items()}
    mocks["render_all_video_clips"].return_value = []
    mocks["produce_all_audio_and_lip_sync"].return_value = ([], [])
    mocks["run_all_verification_gates"].return_value.overall_status = "PASSED"
    try:
        code = _cli(tmp_path, "--from-stage", "5", "--max-video-jobs", "3", "--json")
        out = capsys.readouterr()
    finally:
        for p in patches.values():
            p.stop()
    payload = json.loads(out.out)
    assert code == EXIT_OK
    assert payload["estimate"]["video_jobs"] == 3
    mocks["render_all_video_clips"].assert_called_once()
    assert "Paid generation plan: 3 video job(s)" in out.err  # printed (stderr under --json)
    state = json.loads((ws.telemetry_dir / "state.json").read_text(encoding="utf-8"))
    assert state["run_meta"]["paid_estimate"]["video_jobs"] == 3
    saved = json.loads((ws.root / "run_result.json").read_text(encoding="utf-8"))
    assert saved["estimate"]["tts_calls"] == 2


def test_missing_api_key_for_paid_plan_is_a_config_error(
    ws: ProjectWorkspace, tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    _artifacts(ws)
    monkeypatch.delenv("MINIMAX_API_KEY")
    patches = _patch_stages()
    mocks = {n: p.start() for n, p in patches.items()}
    try:
        code = _cli(tmp_path, "--from-stage", "5", "--json")
        payload = json.loads(capsys.readouterr().out)
    finally:
        for p in patches.values():
            p.stop()
    assert code == EXIT_INVALID_INPUT
    assert payload["error_code"] == "missing_api_key" and "MINIMAX_API_KEY" in payload["error"]
    mocks["render_all_video_clips"].assert_not_called()
