"""Unit tests for pipeline.workspace.ProjectWorkspace."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from pydantic import BaseModel, Field

from pipeline.archetypes import ProductArchetype
from pipeline.workspace import ProjectWorkspace


class SampleArtifact(BaseModel):
    title: str
    views: int = 0
    tags: list[str] = Field(default_factory=list)


def test_workspace_initialization_defaults(tmp_path: Path):
    ws = ProjectWorkspace(
        topic=ProductArchetype.FASHION_APPAREL,
        project_id="camp_123",
        base_dir=tmp_path,
    )

    expected_root = tmp_path / "projects" / "fashion_apparel" / "camp_123"
    assert ws.topic == "fashion_apparel"
    assert ws.project_id == "camp_123"
    assert ws.root == expected_root
    assert ws.artifacts_dir == expected_root / "artifacts"
    assert ws.keyframes_dir == expected_root / "keyframes"
    assert ws.raw_clips_dir == expected_root / "media" / "raw_clips"
    assert ws.synced_clips_dir == expected_root / "media" / "synced_clips"
    assert ws.audio_dir == expected_root / "media" / "audio"
    assert ws.master_video_path == expected_root / "final_master_camp_123.mp4"
    assert ws.thumbnail_path == expected_root / "thumbnail_camp_123.jpg"


def test_workspace_string_topic_and_empty_id(tmp_path: Path):
    ws = ProjectWorkspace(topic="tech_gadgets", project_id="camp_999", base_dir=tmp_path)
    assert ws.topic == "tech_gadgets"
    assert ws.root == tmp_path / "projects" / "tech_gadgets" / "camp_999"

    # Empty topic falls back to general_commercial
    ws_empty_topic = ProjectWorkspace(topic="", project_id="camp_888", base_dir=tmp_path)
    assert ws_empty_topic.topic == ProductArchetype.GENERAL_COMMERCIAL.value

    # Empty project_id raises ValueError
    with pytest.raises(ValueError, match="project_id cannot be empty"):
        ProjectWorkspace(topic="tech", project_id="   ", base_dir=tmp_path)


def test_ensure_dirs_creates_all_subdirectories(tmp_path: Path):
    ws = ProjectWorkspace(topic="beauty_skincare", project_id="camp_beauty", base_dir=tmp_path)

    assert not ws.root.exists()
    ws.ensure_dirs()
    assert ws.root.is_dir()
    assert ws.artifacts_dir.is_dir()
    assert ws.keyframes_dir.is_dir()
    assert ws.media_dir.is_dir()
    assert ws.raw_clips_dir.is_dir()
    assert ws.synced_clips_dir.is_dir()
    assert ws.audio_dir.is_dir()


def test_save_and_load_artifact_pydantic(tmp_path: Path):
    ws = ProjectWorkspace(topic="home_lifestyle", project_id="camp_home", base_dir=tmp_path)
    sample = SampleArtifact(title="Cosy Blanket", views=1500, tags=["winter", "warm"])

    saved_path = ws.save_artifact("sample", sample)
    assert saved_path.exists()
    assert saved_path == ws.artifacts_dir / "sample.json"

    # Read raw to verify formatting
    content = saved_path.read_text(encoding="utf-8")
    assert '"title": "Cosy Blanket"' in content
    assert "\n  " in content  # Check indentation

    # Load back with Pydantic
    loaded = ws.load_artifact("sample.json", SampleArtifact)
    assert isinstance(loaded, SampleArtifact)
    assert loaded.title == "Cosy Blanket"
    assert loaded.views == 1500
    assert loaded.tags == ["winter", "warm"]


def test_save_artifact_dict(tmp_path: Path):
    ws = ProjectWorkspace(topic="general_commercial", project_id="camp_dict", base_dir=tmp_path)
    data = {"status": "ok", "count": 42}
    saved_path = ws.save_artifact("meta.json", data)
    assert saved_path.exists()

    with open(saved_path, "r", encoding="utf-8") as f:
        loaded_raw = json.load(f)
    assert loaded_raw == data


def test_save_artifact_invalid_type(tmp_path: Path):
    ws = ProjectWorkspace(topic="tech_gadgets", project_id="camp_invalid", base_dir=tmp_path)
    with pytest.raises(TypeError, match="data must be a BaseModel instance or dict"):
        ws.save_artifact("bad", "not a dict or model")  # type: ignore


def test_load_artifact_not_found(tmp_path: Path):
    ws = ProjectWorkspace(topic="tech_gadgets", project_id="camp_404", base_dir=tmp_path)
    ws.ensure_dirs()
    with pytest.raises(FileNotFoundError):
        ws.load_artifact("nonexistent", SampleArtifact)


def test_from_campaign_id_explicit_topic(tmp_path: Path):
    ws = ProjectWorkspace.from_campaign_id("camp_exp", topic=ProductArchetype.TECH_GADGETS, base_dir=tmp_path)
    assert ws.topic == "tech_gadgets"
    assert ws.project_id == "camp_exp"
    assert ws.root == tmp_path / "projects" / "tech_gadgets" / "camp_exp"


def test_from_campaign_id_inferred_topic(tmp_path: Path):
    # Setup directory structure on disk for existing project under fashion_apparel
    fashion_project = tmp_path / "projects" / "fashion_apparel" / "camp_discovered"
    fashion_project.mkdir(parents=True, exist_ok=True)

    ws = ProjectWorkspace.from_campaign_id("camp_discovered", base_dir=tmp_path)
    assert ws.topic == "fashion_apparel"
    assert ws.project_id == "camp_discovered"


def test_from_campaign_id_fallback_to_general(tmp_path: Path):
    ws = ProjectWorkspace.from_campaign_id("camp_not_on_disk", base_dir=tmp_path)
    assert ws.topic == ProductArchetype.GENERAL_COMMERCIAL.value
    assert ws.project_id == "camp_not_on_disk"


def test_list_projects(tmp_path: Path):
    # Empty directory returns empty list
    assert ProjectWorkspace.list_projects(base_dir=tmp_path) == []

    # Create several projects across different topics
    p1 = ProjectWorkspace(topic="fashion_apparel", project_id="proj_1", base_dir=tmp_path)
    p1.ensure_dirs()
    p2 = ProjectWorkspace(topic="fashion_apparel", project_id="proj_2", base_dir=tmp_path)
    p2.ensure_dirs()
    p3 = ProjectWorkspace(topic="tech_gadgets", project_id="proj_3", base_dir=tmp_path)
    p3.ensure_dirs()

    # List all
    all_projects = ProjectWorkspace.list_projects(base_dir=tmp_path)
    assert len(all_projects) == 3
    ids = [p.project_id for p in all_projects]
    assert sorted(ids) == ["proj_1", "proj_2", "proj_3"]

    # Filter by topic (string)
    fashion_projects = ProjectWorkspace.list_projects(topic="fashion_apparel", base_dir=tmp_path)
    assert len(fashion_projects) == 2
    assert {p.project_id for p in fashion_projects} == {"proj_1", "proj_2"}

    # Filter by topic (ProductArchetype enum)
    tech_projects = ProjectWorkspace.list_projects(topic=ProductArchetype.TECH_GADGETS, base_dir=tmp_path)
    assert len(tech_projects) == 1
    assert tech_projects[0].project_id == "proj_3"

    # Filter by non-existent topic
    empty = ProjectWorkspace.list_projects(topic="beauty_skincare", base_dir=tmp_path)
    assert empty == []
