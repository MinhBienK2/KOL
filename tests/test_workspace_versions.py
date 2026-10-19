"""Tests for ADR 0007 Versioned Project Workspaces and Hardlink Runs."""

import json
from pathlib import Path

from pipeline.archetypes import ProductArchetype
from pipeline.workspace import ProjectWorkspace


def test_project_workspace_structure(tmp_path: Path):
    ws = ProjectWorkspace(
        topic=ProductArchetype.TECH_GADGETS,
        project_id="smart_mug_pro",
        version="v1",
        base_dir=tmp_path,
    )
    ws.ensure_dirs()

    # Verify project-level directories
    assert ws.project_root.exists()
    assert ws.input_dir.exists()
    assert ws.runs_dir.exists()
    assert ws.project_json_path.exists()

    # Verify run-level directories for v1
    assert ws.root == ws.runs_dir / "v1"
    assert ws.artifacts_dir.exists()
    assert ws.keyframes_dir.exists()
    assert ws.media_dir.exists()
    assert ws.raw_clips_dir.exists()
    assert ws.synced_clips_dir.exists()
    assert ws.audio_dir.exists()
    assert ws.telemetry_dir.exists()

    # Verify project.json content
    meta = ws.get_project_meta()
    assert meta["project_id"] == "smart_mug_pro"
    assert meta["topic"] == "tech_gadgets"
    assert meta["active_version"] == "v1"
    assert "v1" in meta["versions"]


def test_prompt_ledger_persistence(tmp_path: Path):
    ws = ProjectWorkspace(
        topic=ProductArchetype.BEAUTY_SKINCARE,
        project_id="glow_serum",
        base_dir=tmp_path,
    )
    ws.ensure_dirs()

    ledger = {
        "shot_01": {
            "model": "MiniMax-Hailuo-2.3",
            "aspect_ratio": "9:16",
            "duration": 5.0,
            "prompt": "Close-up of glowing serum drops on glass pipette",
            "task_id": "task_12345",
        }
    }
    path = ws.write_prompt_ledger(ledger)
    assert path.exists()
    assert path == ws.prompt_ledger_path

    with open(path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["shot_01"]["task_id"] == "task_12345"


def test_create_next_version_hardlink_inheritance(tmp_path: Path):
    ws_v1 = ProjectWorkspace(
        topic=ProductArchetype.FASHION_APPAREL,
        project_id="cherry_dress",
        version="v1",
        base_dir=tmp_path,
    )
    ws_v1.ensure_dirs()

    # Populate dummy media and artifact in v1
    dummy_clip = ws_v1.raw_clips_dir / "shot_01.mp4"
    dummy_clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x11" * 100)

    dummy_keyframe = ws_v1.keyframes_dir / "shot_01_clean.jpg"
    dummy_keyframe.write_bytes(b"\xff\xd8\xff\xe0" + b"\x22" * 50)

    ws_v1.save_artifact("brief.json", {"product": "Cherry Dress", "version": "v1"})

    # Branch to v2 inheriting from v1
    ws_v2 = ws_v1.create_next_version(inherit_from="v1")
    assert ws_v2.version == "v2"
    assert ws_v2.root == ws_v1.runs_dir / "v2"

    # Verify hardlinked media exists in v2
    v2_clip = ws_v2.raw_clips_dir / "shot_01.mp4"
    v2_kf = ws_v2.keyframes_dir / "shot_01_clean.jpg"
    assert v2_clip.exists()
    assert v2_kf.exists()
    assert v2_clip.stat().st_size == dummy_clip.stat().st_size

    # Check same inode (hardlinked)
    assert v2_clip.stat().st_ino == dummy_clip.stat().st_ino
    assert v2_kf.stat().st_ino == dummy_keyframe.stat().st_ino

    # Verify baseline artifact copied
    assert (ws_v2.artifacts_dir / "brief.json").exists()

    # Verify project.json tracks active_version v2
    meta = ws_v2.get_project_meta()
    assert meta["active_version"] == "v2"
    assert "v1" in meta["versions"]
    assert "v2" in meta["versions"]


def test_list_projects_and_from_campaign_id(tmp_path: Path):
    ws = ProjectWorkspace(
        topic=ProductArchetype.HOME_LIFESTYLE,
        project_id="cozy_lamp",
        base_dir=tmp_path,
    )
    ws.ensure_dirs()

    projects = ProjectWorkspace.list_projects(base_dir=tmp_path)
    assert any(p.project_id == "cozy_lamp" for p in projects)

    loaded_ws = ProjectWorkspace.from_campaign_id(
        campaign_id="cozy_lamp",
        base_dir=tmp_path,
    )
    assert loaded_ws.project_id == "cozy_lamp"
    assert loaded_ws.topic == "home_lifestyle"
    assert loaded_ws.version == "v1"
