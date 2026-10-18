"""Unit tests for TopicCatalog and TopicDefinition queryable seam."""

from pathlib import Path
import pytest

from pipeline.archetypes import ProductArchetype
from pipeline.topics import (
    DEFAULT_ENVIRONMENT_MAP,
    DEFAULT_WARDROBE_MAP,
    TopicCatalog,
    TopicDefinition,
)
from pipeline.wardrobe import ENVIRONMENT_CATALOG, WARDROBE_CATALOG, EnvironmentSetting, WardrobeItem
from pipeline.workspace import ProjectWorkspace


ALL_ARCHETYPES = [
    ProductArchetype.FASHION_APPAREL,
    ProductArchetype.TECH_GADGETS,
    ProductArchetype.BEAUTY_SKINCARE,
    ProductArchetype.HOME_LIFESTYLE,
    ProductArchetype.GENERAL_COMMERCIAL,
]


def test_list_topics_covers_all_archetypes():
    """Verify list_topics returns all 5 domain archetypes."""
    topics = TopicCatalog.list_topics()
    assert len(topics) == 5

    archetypes_found = {t.archetype for t in topics}
    for arch in ALL_ARCHETYPES:
        assert arch in archetypes_found


def test_topic_definitions_have_valid_metadata():
    """Check that each TopicDefinition has non-empty display name, description, and valid defaults."""
    for arch in ALL_ARCHETYPES:
        topic_def = TopicCatalog.get_topic(arch)
        assert isinstance(topic_def, TopicDefinition)
        assert topic_def.archetype == arch
        assert topic_def.display_name.strip()
        assert topic_def.description.strip()
        assert topic_def.default_costume_id in WARDROBE_CATALOG
        assert topic_def.default_env_id in ENVIRONMENT_CATALOG


def test_get_topic_string_and_enum():
    """Verify get_topic accepts both string and ProductArchetype enum."""
    by_enum = TopicCatalog.get_topic(ProductArchetype.TECH_GADGETS)
    by_str = TopicCatalog.get_topic("tech_gadgets")
    assert by_enum.archetype == by_str.archetype
    assert by_enum.display_name == by_str.display_name
    assert by_enum.default_costume_id == "costume_techwear_minimalist"
    assert by_enum.default_env_id == "env_cyberpunk_desk"


def test_get_topic_fallback_for_unknown():
    """Verify unknown topic gracefully falls back to GENERAL_COMMERCIAL."""
    fallback = TopicCatalog.get_topic("unknown_arbitrary_topic")
    assert fallback.archetype == ProductArchetype.GENERAL_COMMERCIAL
    assert fallback.default_costume_id == "costume_executive_blazer"
    assert fallback.default_env_id == "env_studio_infinity_cyclorama"


def test_get_default_wardrobe_and_environment():
    """Verify get_default_wardrobe and get_default_environment return valid objects."""
    for arch in ALL_ARCHETYPES:
        wardrobe = TopicCatalog.get_default_wardrobe(arch)
        assert isinstance(wardrobe, WardrobeItem)
        assert wardrobe.costume_id == DEFAULT_WARDROBE_MAP[arch]

        env = TopicCatalog.get_default_environment(arch)
        assert isinstance(env, EnvironmentSetting)
        assert env.env_id == DEFAULT_ENVIRONMENT_MAP[arch]


def test_get_default_wardrobe_by_str():
    """Verify string input to get_default_wardrobe works."""
    wardrobe = TopicCatalog.get_default_wardrobe("fashion_apparel")
    assert isinstance(wardrobe, WardrobeItem)
    assert wardrobe.costume_id == "costume_french_satin_dress"


def test_list_projects_for_topic(tmp_path: Path):
    """Verify list_projects_for_topic discovers workspaces in the topic folder."""
    # Setup test projects using tmp_path as base_dir
    ws1 = ProjectWorkspace(topic=ProductArchetype.FASHION_APPAREL, project_id="proj_001", base_dir=tmp_path)
    ws1.ensure_dirs()
    ws2 = ProjectWorkspace(topic=ProductArchetype.FASHION_APPAREL, project_id="proj_002", base_dir=tmp_path)
    ws2.ensure_dirs()

    # Another topic
    ws_tech = ProjectWorkspace(topic=ProductArchetype.TECH_GADGETS, project_id="proj_tech_001", base_dir=tmp_path)
    ws_tech.ensure_dirs()

    fashion_projects = TopicCatalog.list_projects_for_topic(ProductArchetype.FASHION_APPAREL, base_dir=tmp_path)
    project_ids = {p.project_id for p in fashion_projects}
    assert "proj_001" in project_ids
    assert "proj_002" in project_ids
    assert "proj_tech_001" not in project_ids

    # Query using string
    tech_projects = TopicCatalog.list_projects_for_topic("tech_gadgets", base_dir=tmp_path)
    assert len(tech_projects) == 1
    assert tech_projects[0].project_id == "proj_tech_001"
