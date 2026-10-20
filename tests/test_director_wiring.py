"""Offline tests: the director passes agent direction through to each stage (round 2 wiring)."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline import director as pdirector
from pipeline.director import StageCapabilityError, run_pipeline
from tools.director import build_parser, main as cli_main

STAGE_NAMES = [
    "create_product_brief",
    "create_product_brief_from_concept",
    "run_research_pipeline",
    "generate_commercial_script",
    "generate_scene_plan",
    "generate_clean_keyframes",
    "render_all_video_clips",
    "produce_all_audio_and_lip_sync",
    "compose_master_commercial",
    "run_all_verification_gates",
]


@pytest.fixture
def stages():
    """Patch every stage function on pipeline.director with an offline mock; yield the mocks."""
    report = MagicMock(overall_status="PASSED")
    returns = {
        "generate_commercial_script": MagicMock(beats=[MagicMock()]),
        "generate_scene_plan": MagicMock(shots=[MagicMock()], slideshow_risk={}),
        "generate_clean_keyframes": MagicMock(keyframes=[MagicMock()]),
        "render_all_video_clips": ["clip.mp4"],
        "produce_all_audio_and_lip_sync": (["stem.wav"], ["sync.mp4"]),
        "run_all_verification_gates": report,
    }
    mocks = {}
    with ExitStack() as stack:
        for name in STAGE_NAMES:
            mocks[name] = stack.enter_context(
                patch(f"pipeline.director.{name}", return_value=returns.get(name, MagicMock()))
            )
        yield mocks


def _run(tmp_path: Path, **kwargs):
    kwargs.setdefault("campaign_id", "wiring_camp")
    kwargs.setdefault("topic", "tech_gadgets")
    kwargs.setdefault("video_mode", "ffmpeg")
    return run_pipeline(output_dir=tmp_path, **kwargs)


def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------- stage 1


def test_stage1_with_url_uses_brief_from_concept(tmp_path, stages):
    research, concept = MagicMock(), MagicMock()
    stages["run_research_pipeline"].return_value = (research, concept)
    assert _run(tmp_path, product_url_or_query="https://shop.example/p/1", resume_from_stage=1) is True

    stages["create_product_brief_from_concept"].assert_called_once()
    call = stages["create_product_brief_from_concept"].call_args
    assert call.args[:2] == (concept, research)
    assert isinstance(call.kwargs["workspace"], pdirector.ProjectWorkspace)
    stages["create_product_brief"].assert_not_called()


def test_stage1_without_url_uses_plain_brief(tmp_path, stages):
    assert _run(tmp_path) is True
    stages["create_product_brief"].assert_called_once()
    stages["create_product_brief_from_concept"].assert_not_called()


# ---------------------------------------------------------------- stages 2/3


def test_default_run_passes_no_extra_direction(tmp_path, stages):
    assert _run(tmp_path) is True
    for name, forbidden in {
        "generate_commercial_script": {"beats", "strict"},
        "generate_scene_plan": {"shot_overrides", "character_path"},
        "generate_clean_keyframes": {"reference_overrides", "character_path", "strict_resolution"},
        "produce_all_audio_and_lip_sync": {"strict_tts"},
        "compose_master_commercial": {"transitions"},
    }.items():
        assert not (forbidden & set(stages[name].call_args.kwargs)), name


def test_beats_list_passed_strict(tmp_path, stages):
    beats = [{"scene_id": "s1", "beat_type": "hook"}]
    _run(tmp_path, beats=beats)
    kwargs = stages["generate_commercial_script"].call_args.kwargs
    assert kwargs["beats"] == beats
    assert kwargs["strict"] is True


def test_beats_from_json_file_and_wrapper_object(tmp_path, stages):
    beats = [{"scene_id": "s1"}]
    _run(tmp_path, beats=_write(tmp_path / "b.json", {"beats": beats}))
    assert stages["generate_commercial_script"].call_args.kwargs["beats"] == beats


def test_shot_overrides_passed_to_scene_plan(tmp_path, stages):
    overrides = {"shot_02": {"camera": "dolly_in"}}
    _run(tmp_path, shot_overrides=_write(tmp_path / "o.json", overrides))
    assert stages["generate_scene_plan"].call_args.kwargs["shot_overrides"] == overrides


# ---------------------------------------------------------------- stage 4


def test_keyframe_direction_passed(tmp_path, stages):
    char = _write(tmp_path / "character.json", {"character_tag": "[X]"})
    refs = {"shot_01": ["a.png"]}
    _run(tmp_path, reference_overrides=refs, character_path=char, strict_resolution=True)
    kwargs = stages["generate_clean_keyframes"].call_args.kwargs
    assert kwargs["reference_overrides"] == refs
    assert kwargs["character_path"] == char
    assert kwargs["strict_resolution"] is True


def test_character_persona_id_resolves_under_assets():
    resolved = pdirector.resolve_character_path("kol_minhanh")
    assert resolved == pdirector.BASE_DIR / "assets" / "characters" / "kol_minhanh" / "character.json"
    with pytest.raises(FileNotFoundError):
        pdirector.resolve_character_path("no_such_persona_xyz")


# ---------------------------------------------------------------- stages 6/7


def test_strict_tts_passed(tmp_path, stages):
    _run(tmp_path, strict_tts=True)
    assert stages["produce_all_audio_and_lip_sync"].call_args.kwargs["strict_tts"] is True


def test_transitions_from_file(tmp_path, stages):
    _run(tmp_path, transitions=_write(tmp_path / "t.json", ["cut", "dissolve"]))
    assert stages["compose_master_commercial"].call_args.kwargs["transitions"] == ["cut", "dissolve"]


def test_transitions_read_from_script_beats(tmp_path, stages):
    ws = pdirector.ProjectWorkspace(topic="tech_gadgets", project_id="wiring_camp", base_dir=tmp_path)
    ws.ensure_dirs()
    _write(ws.artifacts_dir / "script.json", {"beats": [{"transition": "whip_pan"}, {"scene_id": "x"}]})
    _run(tmp_path, resume_from_stage=7)
    assert stages["compose_master_commercial"].call_args.kwargs["transitions"] == ["whip_pan", None]


def test_script_without_transition_fields_passes_nothing(tmp_path, stages):
    ws = pdirector.ProjectWorkspace(topic="tech_gadgets", project_id="wiring_camp", base_dir=tmp_path)
    ws.ensure_dirs()
    _write(ws.artifacts_dir / "script.json", {"beats": [{"scene_id": "x"}]})
    _run(tmp_path, resume_from_stage=7)
    assert "transitions" not in stages["compose_master_commercial"].call_args.kwargs


def test_explicit_transitions_beat_script_fields(tmp_path, stages):
    ws = pdirector.ProjectWorkspace(topic="tech_gadgets", project_id="wiring_camp", base_dir=tmp_path)
    ws.ensure_dirs()
    _write(ws.artifacts_dir / "script.json", {"beats": [{"transition": "whip_pan"}]})
    _run(tmp_path, resume_from_stage=7, transitions=["cut"])
    assert stages["compose_master_commercial"].call_args.kwargs["transitions"] == ["cut"]


# ---------------------------------------------------------------- capability guard


def test_unsupported_instruction_fails_loudly(tmp_path):
    def old_scene_plan(script=None, output_dir=None, workspace=None):  # no shot_overrides
        raise AssertionError("must not be called")

    with pytest.raises(StageCapabilityError):
        pdirector._call_stage(old_scene_plan, {"workspace": None}, {"shot_overrides": {"a": 1}})
    # ...but untouched defaults never trip the guard
    seen = {}
    pdirector._call_stage(lambda workspace=None: seen.update(ok=True), {"workspace": None}, {"shot_overrides": None})
    assert seen == {"ok": True}


def test_capability_failure_marks_run_failed(tmp_path, stages):
    def old_script(output_dir=None, archetype=None, workspace=None):
        return MagicMock(beats=[])

    stages["generate_commercial_script"].side_effect = None
    with patch("pipeline.director.generate_commercial_script", old_script):
        assert _run(tmp_path, beats=[{"scene_id": "s1"}]) is False


# ---------------------------------------------------------------- pause / resume


def test_pause_after_stage_stops_and_writes_result(tmp_path, stages):
    result: dict = {}
    assert _run(tmp_path, pause_after_stage=3, result=result) is False

    stages["generate_scene_plan"].assert_called_once()
    stages["generate_clean_keyframes"].assert_not_called()
    stages["render_all_video_clips"].assert_not_called()
    assert result["status"] == "paused"
    assert result["paused_after_stage"] == 3
    assert result["next_stage"] == 4

    ws = pdirector.ProjectWorkspace(topic="tech_gadgets", project_id="wiring_camp", base_dir=tmp_path)
    on_disk = json.loads((ws.root / pdirector.RUN_RESULT_FILENAME).read_text(encoding="utf-8"))
    assert on_disk["status"] == "paused" and on_disk["ok"] is False
    state = json.loads((ws.root / "telemetry" / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "paused"


def test_resume_after_pause_continues(tmp_path, stages):
    _run(tmp_path, pause_after_stage=3)
    for m in stages.values():
        m.reset_mock()
    result: dict = {}
    assert _run(tmp_path, resume_from_stage=4, result=result) is True
    stages["create_product_brief"].assert_not_called()
    stages["generate_scene_plan"].assert_not_called()
    stages["generate_clean_keyframes"].assert_called_once()
    stages["run_all_verification_gates"].assert_called_once()
    assert result["status"] == "completed" and result["ok"] is True


def test_completed_and_failed_results(tmp_path, stages):
    result: dict = {}
    assert _run(tmp_path, result=result) is True
    assert result["status"] == "completed"

    stages["render_all_video_clips"].side_effect = RuntimeError("boom")
    result2: dict = {}
    assert _run(tmp_path, result=result2) is False
    assert result2["status"] == "failed" and result2["failed_stage"] == 5


def test_pause_after_stage_validation(tmp_path, stages):
    with pytest.raises(ValueError):
        _run(tmp_path, pause_after_stage=8)


# ---------------------------------------------------------------- CLI


def test_cli_new_flags_forwarded(tmp_path):
    beats = _write(tmp_path / "beats.json", [{"scene_id": "s1"}])
    so = _write(tmp_path / "so.json", {"shot_01": {"x": 1}})
    refs = _write(tmp_path / "refs.json", {"shot_01": ["a.png"]})
    trans = _write(tmp_path / "tr.json", ["cut"])
    char = _write(tmp_path / "char.json", {"character_tag": "[C]"})
    with patch("tools.director.run_pipeline", return_value=True) as run:
        code = cli_main([
            "--campaign", "c1", "--topic", "tech_gadgets", "--out-dir", str(tmp_path),
            "--beats", str(beats), "--shot-overrides", str(so), "--references", str(refs),
            "--transitions", str(trans), "--character", str(char),
            "--strict-resolution", "--strict-tts",
        ])
    assert code == 0
    kw = run.call_args.kwargs
    assert kw["beats"] == [{"scene_id": "s1"}]
    assert kw["shot_overrides"] == {"shot_01": {"x": 1}}
    assert kw["reference_overrides"] == {"shot_01": ["a.png"]}
    assert kw["transitions"] == ["cut"]
    assert kw["character_path"] == char
    assert kw["strict_resolution"] is True and kw["strict_tts"] is True
    assert kw["pause_after_stage"] is None


def test_cli_missing_json_is_usage_error(tmp_path):
    with patch("tools.director.run_pipeline") as run, pytest.raises(SystemExit) as exc:
        cli_main(["--beats", str(tmp_path / "missing.json"), "--out-dir", str(tmp_path)])
    assert exc.value.code == 2
    run.assert_not_called()


def test_cli_pause_exit_code_4(tmp_path):
    def fake_run(**kwargs):
        kwargs["result"].update(status="paused", paused_after_stage=2)
        return False

    out = tmp_path / "result.json"
    with patch("tools.director.run_pipeline", side_effect=fake_run) as run:
        code = cli_main(["--out-dir", str(tmp_path), "--pause-after-stage", "2", "--result-json", str(out)])
    assert code == 4
    assert run.call_args.kwargs["pause_after_stage"] == 2
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "paused"


def test_cli_failure_exit_code_1(tmp_path):
    with patch("tools.director.run_pipeline", return_value=False):
        assert cli_main(["--out-dir", str(tmp_path)]) == 1


def test_cli_offline_sets_env_and_forces_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.setenv("KOL_OFFLINE", "0")  # registers restoration on teardown
    with patch("tools.director.run_pipeline", return_value=True) as run:
        cli_main(["--out-dir", str(tmp_path), "--offline", "--video-mode", "api"])
    assert os.environ["KOL_OFFLINE"] == "1"
    assert run.call_args.kwargs["video_mode"] == "ffmpeg"


def test_cli_pause_flag_rejects_stage_8():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--pause-after-stage", "8"])


def test_pipeline_director_main_delegates_to_tools(tmp_path):
    with patch("tools.director.run_pipeline", return_value=True) as run:
        code = pdirector.main(["--out-dir", str(tmp_path), "--strict-tts"])
    assert code == 0
    assert run.call_args.kwargs["strict_tts"] is True
