"""Topic Catalog & Queryable Seam for Domain Archetypes.

Connects ProductArchetypes with their default Directorial specifications,
wardrobe costumes, architectural environments, and workspace project listings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import BaseModel

from pipeline.archetypes import (
    ARCHETYPE_REGISTRY,
    DirectorialArchetypeConfig,
    ProductArchetype,
    classify_product_archetype,
    get_archetype_config,
)
from pipeline.wardrobe import (
    ENVIRONMENT_CATALOG,
    WARDROBE_CATALOG,
    EnvironmentSetting,
    WardrobeItem,
)
from pipeline.workspace import ProjectWorkspace


# Default mappings for wardrobe and environment per product archetype
DEFAULT_WARDROBE_MAP: Dict[ProductArchetype, str] = {
    ProductArchetype.FASHION_APPAREL: "costume_french_satin_dress",
    ProductArchetype.TECH_GADGETS: "costume_techwear_minimalist",
    ProductArchetype.BEAUTY_SKINCARE: "costume_minimalist_spa_silk",
    ProductArchetype.HOME_LIFESTYLE: "costume_cozy_nordic_knit",
    ProductArchetype.GENERAL_COMMERCIAL: "costume_executive_blazer",
}

DEFAULT_ENVIRONMENT_MAP: Dict[ProductArchetype, str] = {
    ProductArchetype.FASHION_APPAREL: "env_paris_ballroom",
    ProductArchetype.TECH_GADGETS: "env_cyberpunk_desk",
    ProductArchetype.BEAUTY_SKINCARE: "env_minimalist_marble_bath",
    ProductArchetype.HOME_LIFESTYLE: "env_nordic_kitchen",
    ProductArchetype.GENERAL_COMMERCIAL: "env_studio_infinity_cyclorama",
}


def _resolve_archetype(topic: Union[str, ProductArchetype]) -> ProductArchetype:
    """Normalize a topic string or ProductArchetype enum into a ProductArchetype."""
    if isinstance(topic, ProductArchetype):
        return topic
    try:
        return ProductArchetype(str(topic).strip())
    except ValueError:
        return ProductArchetype.GENERAL_COMMERCIAL


class TopicDefinition(BaseModel):
    """Metadata definition and directorial defaults for a domain topic / archetype."""
    archetype: ProductArchetype
    display_name: str
    description: str
    default_costume_id: str
    default_env_id: str


class TopicCatalog:
    """Queryable seam and registry for all supported domain topics."""

    @classmethod
    def list_topics(cls) -> List[TopicDefinition]:
        """List all supported topic definitions across all ProductArchetypes."""
        topics: List[TopicDefinition] = []
        for arch in ProductArchetype:
            topics.append(cls.get_topic(arch))
        return topics

    @classmethod
    def get_topic(cls, topic: Union[str, ProductArchetype]) -> TopicDefinition:
        """Retrieve topic definition metadata for a given topic or archetype."""
        arch = _resolve_archetype(topic)
        config = get_archetype_config(arch)
        costume_id = DEFAULT_WARDROBE_MAP.get(arch, "costume_executive_blazer")
        env_id = DEFAULT_ENVIRONMENT_MAP.get(arch, "env_studio_infinity_cyclorama")

        return TopicDefinition(
            archetype=arch,
            display_name=config.display_name,
            description=config.description,
            default_costume_id=costume_id,
            default_env_id=env_id,
        )

    @classmethod
    def classify(cls, product_text: str) -> TopicDefinition:
        """Detect the best matching topic for free product text (title, copy, URL slug)."""
        return cls.get_topic(classify_product_archetype(product_text))

    @classmethod
    def get_default_wardrobe(cls, topic: Union[str, ProductArchetype]) -> Optional[WardrobeItem]:
        """Resolve the default WardrobeItem for a given topic or archetype."""
        topic_def = cls.get_topic(topic)
        return WARDROBE_CATALOG.get(topic_def.default_costume_id)

    @classmethod
    def get_default_environment(cls, topic: Union[str, ProductArchetype]) -> Optional[EnvironmentSetting]:
        """Resolve the default EnvironmentSetting for a given topic or archetype."""
        topic_def = cls.get_topic(topic)
        return ENVIRONMENT_CATALOG.get(topic_def.default_env_id)

    @classmethod
    def list_projects_for_topic(
        cls,
        topic: Union[str, ProductArchetype],
        base_dir: Optional[Path] = None,
    ) -> List[ProjectWorkspace]:
        """List all discovered project workspaces under this topic."""
        arch = _resolve_archetype(topic)
        return ProjectWorkspace.list_projects(topic=arch, base_dir=base_dir)
