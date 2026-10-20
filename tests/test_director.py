"""Unit tests for pipeline.director and tools.director ProjectWorkspace integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from pipeline.archetypes import ProductArchetype
from pipeline.briefing import create_product_brief
from pipeline.composer import compose_master_commercial
from pipeline.director import run_pipeline
from pipeline.identity_keyframe import generate_clean_keyframes
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from pipeline.verification import run_all_verification_gates
from pipeline.workspace import ProjectWorkspace
from tools.director import build_parser, main as tools_director_main


def test_stage_modules_accept_workspace(tmp_path: Path):
    """Verify stage modules write artifacts and outputs into ProjectWorkspace paths."""
    ws = ProjectWorkspace(
        topic=ProductArchetype.FASHION_APPAREL,
        project_id="camp_stage_test",
        base_dir=tmp_path,
    )
    ws.ensure_dirs()
    Image.new("RGB", (1200, 1200), (200, 180, 160)).save(ws.input_dir / "product_hero.jpg")

    # Step 1: Briefing
    brief = create_product_brief(
        product_name="Váy Satin Lụa Pháp",
        workspace=ws,
    )
    assert (ws.artifacts_dir / "brief.json").exists()
    assert brief.campaign_id == "camp_stage_test"

    # Step 2: Scriptwriter
    script = generate_commercial_script(
        brief=brief,
        workspace=ws,
    )
    assert (ws.artifacts_dir / "script.json").exists()
    assert script.campaign_id == "camp_stage_test"

    # Step 3: Storyboard
    plan = generate_scene_plan(
        script=script,
        workspace=ws,
    )
    assert (ws.artifacts_dir / "scene_plan.json").exists()
    assert (ws.artifacts_dir / "storyboard_contact_sheet.jpg").exists()

    # Step 4: Keyframes (clean keyframe generation)
    manifest = generate_clean_keyframes(
        scene_plan=plan,
        workspace=ws,
    )
    assert (ws.artifacts_dir / "asset_manifest.json").exists()
    assert (ws.keyframes_dir / f"{plan.shots[0].shot_id}_clean.jpg").exists()


def test_run_pipeline_auto_constructs_workspace(tmp_path: Path):
    """Verify run_pipeline automatically instantiates ProjectWorkspace when none provided."""
    target_topic = ProductArchetype.TECH_GADGETS
    camp_id = "test_camp_auto"

    mock_brief = MagicMock()
    mock_script = MagicMock()
    mock_script.beats = [MagicMock()]
    mock_plan = MagicMock()
    mock_plan.shots = [MagicMock()]
    mock_plan.slideshow_risk = {"average_score": 10.0, "verdict": "LOW_RISK"}
    mock_manifest = MagicMock()
    mock_manifest.keyframes = [MagicMock()]
    mock_report = MagicMock()
    mock_report.overall_status = "PASSED"

    with patch("pipeline.director.create_product_brief", return_value=mock_brief) as p_brief, \
         patch("pipeline.director.generate_commercial_script", return_value=mock_script) as p_script, \
         patch("pipeline.director.generate_scene_plan", return_value=mock_plan) as p_plan, \
         patch("pipeline.director.generate_clean_keyframes", return_value=mock_manifest) as p_kf, \
         patch("pipeline.director.render_all_video_clips", return_value=["clip.mp4"]) as p_vid, \
         patch("pipeline.director.produce_all_audio_and_lip_sync", return_value=(["stem.wav"], ["sync.mp4"])) as p_aud, \
         patch("pipeline.director.compose_master_commercial", return_value=MagicMock()) as p_comp, \
         patch("pipeline.director.run_all_verification_gates", return_value=mock_report) as p_ver:

        success = run_pipeline(
            campaign_id=camp_id,
            topic=target_topic,
            output_dir=tmp_path,
            video_mode="auto",
        )
        assert success is True

        # Check that workspace was passed to the stages
        assert p_brief.call_args is not None
        passed_ws = p_brief.call_args.kwargs.get("workspace")
        assert isinstance(passed_ws, ProjectWorkspace)
        assert passed_ws.topic == target_topic.value
        assert passed_ws.project_id == camp_id
        assert passed_ws.project_root == tmp_path / "projects" / target_topic.value / camp_id
        assert passed_ws.root == tmp_path / "projects" / target_topic.value / camp_id / "runs" / "v1"

        # Check other stage calls received the same workspace
        assert p_script.call_args.kwargs.get("workspace") is passed_ws
        assert p_plan.call_args.kwargs.get("workspace") is passed_ws
        assert p_kf.call_args.kwargs.get("workspace") is passed_ws
        assert p_vid.call_args.kwargs.get("workspace") is passed_ws
        assert p_aud.call_args.kwargs.get("workspace") is passed_ws
        assert p_comp.call_args.kwargs.get("workspace") is passed_ws
        assert p_ver.call_args.kwargs.get("workspace") is passed_ws


def test_run_pipeline_with_explicit_workspace(tmp_path: Path):
    """Verify run_pipeline respects a pre-instantiated ProjectWorkspace."""
    ws = ProjectWorkspace(
        topic="beauty_skincare",
        project_id="camp_custom_ws",
        base_dir=tmp_path,
    )

    mock_report = MagicMock()
    mock_report.overall_status = "PASSED"

    with patch("pipeline.director.create_product_brief"), \
         patch("pipeline.director.generate_commercial_script", return_value=MagicMock(beats=[MagicMock()])), \
         patch("pipeline.director.generate_scene_plan", return_value=MagicMock(shots=[MagicMock()], slideshow_risk={})), \
         patch("pipeline.director.generate_clean_keyframes", return_value=MagicMock(keyframes=[MagicMock()])), \
         patch("pipeline.director.render_all_video_clips", return_value=["clip.mp4"]), \
         patch("pipeline.director.produce_all_audio_and_lip_sync", return_value=([], [])), \
         patch("pipeline.director.compose_master_commercial"), \
         patch("pipeline.director.run_all_verification_gates", return_value=mock_report):

        success = run_pipeline(
            workspace=ws,
            video_mode="auto",
        )
        assert success is True
        assert ws.root.exists()
        assert ws.artifacts_dir.exists()


def test_tools_director_cli_prints_project_path(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Verify tools/director.py prints the clean projects/{topic}/{project_id}/ path."""
    with patch("tools.director.run_pipeline", return_value=True) as mock_run:
        exit_code = tools_director_main([
            "--topic", "fashion_apparel",
            "--campaign", "test_fashion_cli",
            "--out-dir", str(tmp_path),
        ])
        assert exit_code == 0
        mock_run.assert_called_once()
        called_ws = mock_run.call_args.kwargs.get("workspace")
        assert isinstance(called_ws, ProjectWorkspace)
        assert called_ws.topic == "fashion_apparel"
        assert called_ws.project_id == "test_fashion_cli"

        captured = capsys.readouterr()
        assert "projects/fashion_apparel/test_fashion_cli/" in captured.out

def test_tools_director_cli_archetype_option(tmp_path: Path, capsys: pytest.CaptureFixture):
    """Verify tools/director.py handles --archetype and --project-id options."""
    with patch("tools.director.run_pipeline", return_value=True) as mock_run:
        exit_code = tools_director_main([
            "--archetype", "tech_gadgets",
            "--project-id", "test_tech_cli",
            "--out-dir", str(tmp_path),
        ])
        assert exit_code == 0
        mock_run.assert_called_once()
        called_ws = mock_run.call_args.kwargs.get("workspace")
        assert called_ws.topic == "tech_gadgets"
        assert called_ws.project_id == "test_tech_cli"

        captured = capsys.readouterr()
        assert "projects/tech_gadgets/test_tech_cli/" in captured.out
