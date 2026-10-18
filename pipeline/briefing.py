"""Step 1: Product Briefing & USP Analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from pipeline.config import ARTIFACTS_DIR
from pipeline.schemas import BriefArtifact, PresenterInfo
from pipeline.archetypes import (
    AudioStrategy,
    CharacterRole,
    ProductArchetype,
    DynamicPromptBuilder,
    get_archetype_config,
)
def create_product_brief(
    campaign_id: str = "campaign_lumina_mug_01",
    product_name: str = "Ly Giữ Nhiệt Thông Minh Lumina Pro",
    target_persona: str = "Dân văn phòng, freelancer, người trẻ hiện đại 22–35 tuổi yêu thích công nghệ và lối sống tinh tế",
    pain_points: list[str] | None = None,
    usps: list[str] | None = None,
    visual_tone: str = "Sang trọng, hiện đại, tối giản công sở, chuẩn ánh sáng studio cao cấp",
    aspect_ratio: str = "9:16",
    archetype: ProductArchetype | str = ProductArchetype.GENERAL_COMMERCIAL,
    category: str | None = None,
    character_role: CharacterRole | str | None = None,
    target_audio_strategy: AudioStrategy | str | None = None,
    presenter: PresenterInfo | None = None,
    output_dir: Path | None = None,
) -> BriefArtifact:
    """Generates and persists the canonical brief.json artifact."""
    if isinstance(archetype, str):
        try:
            archetype = ProductArchetype(archetype)
        except ValueError:
            archetype = ProductArchetype.GENERAL_COMMERCIAL

    arch_config = get_archetype_config(archetype)

    if character_role is not None and isinstance(character_role, str):
        try:
            character_role = CharacterRole(character_role)
        except ValueError:
            character_role = arch_config.default_character_role
    elif character_role is None:
        character_role = arch_config.default_character_role

    if target_audio_strategy is not None and isinstance(target_audio_strategy, str):
        try:
            target_audio_strategy = AudioStrategy(target_audio_strategy)
        except ValueError:
            target_audio_strategy = arch_config.default_audio_strategy
    elif target_audio_strategy is None:
        target_audio_strategy = arch_config.default_audio_strategy

    if presenter is None:
        persona = DynamicPromptBuilder.resolve_persona(archetype)
        presenter = PresenterInfo(
            name=persona.name,
            character_tag=persona.character_tag,
            role=f"Lead {character_role.value.capitalize()}",
            character_file=persona.character_file,
        )

    if pain_points is None:
        pain_points = [
            "Cà phê/trà nguội ngắt chỉ sau 15 phút làm mất đi hương vị tươi ngon",
            "Nước đọng hơi lạnh chảy ướt bàn phím, hồ sơ và tài liệu văn phòng quan trọng",
            "Bình giữ nhiệt truyền thống cồng kềnh, dễ rò rỉ nước khi để trong túi xách",
        ]
    if usps is None:
        usps = [
            "Công nghệ giữ nhiệt chân không đa lớp: Nóng 12h, Lạnh 24h kết hợp lõi sứ nano kháng khuẩn",
            "Màn hình LED cảm ứng thông minh trên nắp hiển thị nhiệt độ thực tế chính xác",
            "Thiết kế công sở thanh lịch tối giản với nắp chống tràn 360° và đế silicone chống trượt",
        ]

    brief = BriefArtifact(
        campaign_id=campaign_id,
        product_name=product_name,
        target_persona=target_persona,
        pain_points=pain_points,
        usps=usps,
        visual_tone=visual_tone,
        aspect_ratio=aspect_ratio,
        presenter=presenter,
        archetype=archetype,
        category=category or archetype.value,
        character_role=character_role,
        target_audio_strategy=target_audio_strategy,
    )

    target_dir = output_dir or ARTIFACTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    out_file = target_dir / "brief.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(brief.model_dump(), f, ensure_ascii=False, indent=2)

    return brief


def create_product_brief_from_concept(
    creative_concept: Any,
    research: Any,
    output_dir: Path | None = None,
) -> BriefArtifact:
    """Bridges winning CreativeConceptArtifact & CompetitorResearchArtifact into canonical BriefArtifact."""
    winning_id = creative_concept.winning_concept.selected_angle_id
    winning_angle = next(
        (opt for opt in creative_concept.concept_options if opt.angle_id == winning_id),
        creative_concept.concept_options[0],
    )
    product = research.product_intel

    pain_points = [o.objection for o in product.objection_matrix] if product.objection_matrix else [
        "Sản phẩm truyền thống kém bền, dễ hỏng",
        "Chi phí sử dụng cao và gây phiền toái",
    ]
    usps = product.dramatic_benefits if product.dramatic_benefits else product.features

    return create_product_brief(
        campaign_id=creative_concept.campaign_id,
        product_name=creative_concept.product_name,
        target_persona=winning_angle.target_audience_segment or research.primary_persona,
        pain_points=pain_points,
        usps=usps,
        visual_tone=winning_angle.winning_concept.directorial_directives.lighting_mood if hasattr(winning_angle, "winning_concept") else "Commercial Studio High-End",
        archetype=product.product_archetype,
        category=product.category,
        character_role=winning_angle.character_role,
        target_audio_strategy=winning_angle.audio_strategy,
        output_dir=output_dir,
    )
