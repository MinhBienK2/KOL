"""Agent-facing contract of the director: prerequisites, artifact injection, JSON result, exit codes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.director import run_pipeline
from pipeline.workspace import ProjectWorkspace
from tools.director import (
    EXIT_INVALID_INPUT,
    EXIT_OK,
    EXIT_PIPELINE_FAILED,
    EXIT_VERIFICATION_FAILED,
    main as cli_main,
)

SCRIPT = {
    "campaign_id": "c1",
    "product_name": "Ly Lumina",
    "target_duration": 15.0,
    "beats": [
        {
            "scene_id": "s1",
            "beat_type": "hook",
            "spoken_text": "Xin chao",
            "on_screen_text": "Hi",
            "visual_cue": "close up",
            "estimated_duration": 3.0,
        }
    ],
}
BRIEF = {
    "campaign_id": "c1",
    "product_name": "Ly Lumina",
    "target_persona": "office worker",
    "pain_points": ["cold coffee"],
    "usps": ["12h heat"],
    "visual_tone": "warm",
}


def _ws(tmp_path: Path, project_id: str = "c1") -> ProjectWorkspace:
    ws = ProjectWorkspace(topic="general_commercial", project_id=project_id, base_dir=tmp_path)
    ws.ensure_dirs()
    return ws


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- prerequisites


def test_stage_one_has_no_prerequisites(tmp_path: Path):
    assert _ws(tmp_path).check_prerequisites(1) == []


def test_missing_prerequisite_is_named_with_the_inject_hint(tmp_path: Path):
    problems = _ws(tmp_path).check_prerequisites(3)
    assert len(problems) == 1
    assert "script.json" in problems[0]
    assert "--inject script=" in problems[0]


def test_invalid_prerequisite_reports_schema_error(tmp_path: Path):
    ws = _ws(tmp_path)
    _write(ws.artifacts_dir / "script.json", {"campaign_id": "c1"})
    problems = ws.check_prerequisites(3)
    assert any("script.json" in p and "invalid" in p.lower() for p in problems)


def test_valid_prerequisite_passes(tmp_path: Path):
    ws = _ws(tmp_path)
    _write(ws.artifacts_dir / "script.json", SCRIPT)
    assert ws.check_prerequisites(3) == []


def test_stage_six_requires_raw_clips_that_exist(tmp_path: Path):
    ws = _ws(tmp_path)
    _write(ws.artifacts_dir / "script.json", SCRIPT)
    clip = ws.raw_clips_dir / "shot_01.mp4"
    _write(
        ws.artifacts_dir / "asset_manifest.json",
        {"campaign_id": "c1", "keyframes": [], "raw_video_clips": [str(clip)]},
    )
    assert any("shot_01.mp4" in p for p in ws.check_prerequisites(6))
    clip.write_bytes(b"x")
    assert ws.check_prerequisites(6) == []


def test_stage_eight_requires_master_video(tmp_path: Path):
    ws = _ws(tmp_path)
    _write(ws.artifacts_dir / "script.json", SCRIPT)
    synced = ws.synced_clips_dir / "shot_01.mp4"
    synced.write_bytes(b"x")
    _write(ws.artifacts_dir / "scene_plan.json", {"campaign_id": "c1", "shots": []})
    _write(
        ws.artifacts_dir / "asset_manifest.json",
        {"campaign_id": "c1", "keyframes": [], "synced_video_clips": [str(synced)]},
    )
    assert any("master" in p.lower() for p in ws.check_prerequisites(8))
    ws.master_video_path.write_bytes(b"x")
    assert ws.check_prerequisites(8) == []


# --------------------------------------------------------------------------- inject


def test_inject_artifact_validates_and_copies(tmp_path: Path):
    ws = _ws(tmp_path)
    src = _write(tmp_path / "my_script.json", SCRIPT)
    dest = ws.inject_artifact("script", src)
    assert dest == ws.artifacts_dir / "script.json"
    assert json.loads(dest.read_text(encoding="utf-8"))["product_name"] == "Ly Lumina"


def test_inject_artifact_rejects_schema_violations_without_touching_workspace(tmp_path: Path):
    ws = _ws(tmp_path)
    src = _write(tmp_path / "bad.json", {"campaign_id": "c1"})
    with pytest.raises(ValueError, match="script"):
        ws.inject_artifact("script", src)
    assert not (ws.artifacts_dir / "script.json").exists()


def test_inject_artifact_rejects_unknown_name_and_missing_file(tmp_path: Path):
    ws = _ws(tmp_path)
    src = _write(tmp_path / "x.json", SCRIPT)
    with pytest.raises(ValueError, match="Unknown artifact"):
        ws.inject_artifact("render_report", src)
    with pytest.raises(FileNotFoundError):
        ws.inject_artifact("script", tmp_path / "missing.json")


def test_first_stage_after_injected_artifact():
    from pipeline.workspace import first_stage_after

    assert first_stage_after(["script"]) == 3
    assert first_stage_after(["brief", "scene_plan"]) == 4
    assert first_stage_after([]) == 1


# --------------------------------------------------------------------------- new version path rewrite


def test_new_version_rewrites_absolute_paths_in_inherited_artifacts(tmp_path: Path):
    ws = _ws(tmp_path)
    clip = ws.raw_clips_dir / "shot_01.mp4"
    clip.write_bytes(b"x" * 20)
    _write(
        ws.artifacts_dir / "asset_manifest.json",
        {"campaign_id": "c1", "keyframes": [], "raw_video_clips": [str(clip)]},
    )
    v2 = ws.create_next_version()
    manifest = json.loads((v2.artifacts_dir / "asset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["raw_video_clips"] == [str(v2.raw_clips_dir / "shot_01.mp4")]
    assert (v2.raw_clips_dir / "shot_01.mp4").exists()


# --------------------------------------------------------------------------- director refuses to start


def test_run_pipeline_refuses_to_resume_without_prerequisites(tmp_path: Path):
    ws = _ws(tmp_path)
    with patch("pipeline.director.generate_scene_plan") as plan:
        ok = run_pipeline(workspace=ws, resume_from_stage=3, video_mode="auto")
    assert ok is False
    plan.assert_not_called()


# --------------------------------------------------------------------------- CLI


def _run_cli(tmp_path: Path, *extra: str):
    return cli_main(["--campaign", "c1", "--topic", "general_commercial", "--out-dir", str(tmp_path), *extra])


def test_cli_json_mode_prints_only_one_json_object(tmp_path: Path, capsys: pytest.CaptureFixture):
    def fake_run(**kwargs):
        print("noisy stage output")
        return True

    with patch("tools.director.run_pipeline", side_effect=fake_run):
        code = _run_cli(tmp_path, "--json")
    out = capsys.readouterr()
    assert code == EXIT_OK
    payload = json.loads(out.out)
    assert payload["ok"] is True
    assert payload["exit_code"] == EXIT_OK
    assert payload["project_id"] == "c1"
    assert payload["version"] == "v1"
    assert payload["from_stage"] == 1
    assert payload["artifacts_dir"].endswith("runs/v1/artifacts")
    assert "noisy stage output" in out.err


def test_cli_failed_pipeline_exits_one_and_names_failed_stage(tmp_path: Path, capsys: pytest.CaptureFixture):
    ws = ProjectWorkspace.from_campaign_id("c1", topic="general_commercial", base_dir=tmp_path)
    ws.ensure_dirs()
    state = {"status": "failed", "run_meta": {"failed_stage": 5}, "stages": []}
    (ws.telemetry_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    with patch("tools.director.run_pipeline", return_value=False):
        code = _run_cli(tmp_path, "--json")
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_PIPELINE_FAILED
    assert payload["ok"] is False
    assert payload["failed_stage"] == 5


def test_cli_failed_gates_exit_three_and_list_failed_gates(tmp_path: Path, capsys: pytest.CaptureFixture):
    ws = ProjectWorkspace.from_campaign_id("c1", topic="general_commercial", base_dir=tmp_path)
    ws.ensure_dirs()
    report = {
        "overall_status": "FAILED",
        "verification_gates": [
            {"gate_name": "technical_integrity_gate", "passed": True, "details": {}, "error_message": None},
            {"gate_name": "media_quality_gate", "passed": False, "details": {}, "error_message": "Black picture"},
        ],
    }
    (ws.artifacts_dir / "render_report.json").write_text(json.dumps(report), encoding="utf-8")
    state = {"status": "failed", "run_meta": {"failed_stage": 8}, "stages": []}
    (ws.telemetry_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    with patch("tools.director.run_pipeline", return_value=False):
        code = _run_cli(tmp_path, "--json")
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_VERIFICATION_FAILED
    assert payload["failed_gates"] == [{"gate": "media_quality_gate", "error": "Black picture"}]


def test_cli_inject_validates_copies_and_infers_resume_stage(tmp_path: Path, capsys: pytest.CaptureFixture):
    src = _write(tmp_path / "my_script.json", SCRIPT)
    with patch("tools.director.run_pipeline", return_value=True) as run:
        code = _run_cli(tmp_path, "--inject", f"script={src}", "--json")
    assert code == EXIT_OK
    assert run.call_args.kwargs["resume_from_stage"] == 3
    ws = run.call_args.kwargs["workspace"]
    assert (ws.artifacts_dir / "script.json").exists()
    assert json.loads(capsys.readouterr().out)["from_stage"] == 3


def test_cli_explicit_from_stage_beats_inference(tmp_path: Path):
    """Re-generate the script from an injected brief even though a script was supplied too."""
    script = _write(tmp_path / "my_script.json", SCRIPT)
    brief = _write(tmp_path / "my_brief.json", BRIEF)
    with patch("tools.director.run_pipeline", return_value=True) as run:
        _run_cli(tmp_path, "--inject", f"script={script}", "--inject", f"brief={brief}", "--from-stage", "2")
    assert run.call_args.kwargs["resume_from_stage"] == 2


def test_cli_invalid_inject_exits_two_and_never_runs(tmp_path: Path, capsys: pytest.CaptureFixture):
    bad = _write(tmp_path / "bad.json", {"campaign_id": "c1"})
    with patch("tools.director.run_pipeline") as run:
        code = _run_cli(tmp_path, "--inject", f"script={bad}", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_INVALID_INPUT
    assert payload["ok"] is False
    assert "script" in payload["error"]
    run.assert_not_called()


def test_cli_malformed_inject_spec_exits_two(tmp_path: Path):
    with patch("tools.director.run_pipeline") as run:
        code = _run_cli(tmp_path, "--inject", "no-equals-sign")
    assert code == EXIT_INVALID_INPUT
    run.assert_not_called()


def test_cli_missing_prerequisites_exit_two_with_problem_list(tmp_path: Path, capsys: pytest.CaptureFixture):
    with patch("tools.director.run_pipeline") as run:
        code = _run_cli(tmp_path, "--from-stage", "4", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_INVALID_INPUT
    assert any("scene_plan.json" in p for p in payload["problems"])
    run.assert_not_called()


def test_cli_check_reports_plan_without_running(tmp_path: Path, capsys: pytest.CaptureFixture):
    with patch("tools.director.run_pipeline") as run:
        code = _run_cli(tmp_path, "--check", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert payload["check"] is True
    assert payload["stages_to_run"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert payload["problems"] == []
    run.assert_not_called()


def test_cli_check_fails_when_resume_is_impossible(tmp_path: Path, capsys: pytest.CaptureFixture):
    with patch("tools.director.run_pipeline") as run:
        code = _run_cli(tmp_path, "--check", "--from-stage", "5", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_INVALID_INPUT
    assert payload["stages_to_run"] == [5, 6, 7, 8]
    assert payload["problems"]
    run.assert_not_called()


def test_inject_with_matching_pause_installs_and_pauses_without_running(tmp_path: Path, capsys: pytest.CaptureFixture):
    # QA preprod r1: "--inject brief=... --pause-after-stage 1" installed the brief but exited 2, so the
    # director bypassed the CLI with a Python call to get "install my concept, then let QA review".
    src = _write(tmp_path / "brief_src.json", BRIEF)
    with patch("tools.director.run_pipeline") as run:
        code = _run_cli(tmp_path, "--inject", f"brief={src}", "--pause-after-stage", "1", "--json")
    payload = json.loads(capsys.readouterr().out)
    assert code == 4 and payload["status"] == "paused"
    assert payload["next_stage"] == 2 and payload["injected"] == ["brief"]
    run.assert_not_called()
    assert (Path(payload["artifacts_dir"]) / "brief.json").exists()


def test_inject_script_rejects_lip_sync_without_a_face_and_noon_golden_hour(tmp_path: Path):
    # QA preprod r1: a tyre close-up was on_camera_speech and an 11:45 street was golden_hour.
    ws = _ws(tmp_path)
    bad = json.loads(json.dumps(SCRIPT))
    bad["beats"][0].update({
        "audio_strategy": "on_camera_speech", "character_role": "presenter",
        "visual_cue_en": "Extreme close-up of the knobby tyre rolling over a puddle at midday",
        "lighting_contract": "golden_hour",
    })
    src = _write(tmp_path / "bad_script.json", bad)
    with pytest.raises(ValueError) as exc:
        ws.inject_artifact("script", src)
    assert "lip-sync impossible" in str(exc.value) and "golden_hour" in str(exc.value)
    assert not (ws.artifacts_dir / "script.json").exists()


def test_resume_keeps_the_brief_product_name_not_the_cli_default(tmp_path: Path, monkeypatch):
    # QA preprod r1: --from-stage 3 without --product retitled the bicycle project "Ly Giữ Nhiệt…".
    from pipeline import director as pipeline_director
    from pipeline.briefing import create_product_brief
    from pipeline.scriptwriter import generate_commercial_script

    ws = _ws(tmp_path)
    brief = create_product_brief(campaign_id="c1", product_name="Xe đạp Thống Nhất", output_dir=ws.artifacts_dir)
    generate_commercial_script(brief=brief, output_dir=ws.artifacts_dir)
    seen = {}
    monkeypatch.setattr(ws, "update_project_meta", lambda **kw: seen.update(kw))
    pipeline_director.run_pipeline(campaign_id="c1", workspace=ws, resume_from_stage=3, pause_after_stage=3)
    assert seen["title"] == "Xe đạp Thống Nhất"
