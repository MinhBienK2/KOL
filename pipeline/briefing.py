"""Step 1: Product Briefing & USP Analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from pipeline import telemetry
from pipeline.config import ARTIFACTS_DIR
from pipeline.schemas import BriefArtifact, PresenterInfo
from pipeline.workspace import ProjectWorkspace
from pipeline.archetypes import (
    AudioStrategy,
    CharacterRole,
    ProductArchetype,
    DynamicPromptBuilder,
    get_archetype_config,
)
DEFAULT_PRODUCT_NAME = "Ly Giữ Nhiệt Thông Minh Lumina Pro"
DEFAULT_VISUAL_TONE = "Sang trọng, hiện đại, tối giản công sở, chuẩn ánh sáng studio cao cấp"

LUMINA_PAIN_POINTS = [
    "Cà phê/trà nguội ngắt chỉ sau 15 phút làm mất đi hương vị tươi ngon",
    "Nước đọng hơi lạnh chảy ướt bàn phím, hồ sơ và tài liệu văn phòng quan trọng",
    "Bình giữ nhiệt truyền thống cồng kềnh, dễ rò rỉ nước khi để trong túi xách",
]
LUMINA_USPS = [
    "Công nghệ giữ nhiệt chân không đa lớp: Nóng 12h, Lạnh 24h kết hợp lõi sứ nano kháng khuẩn",
    "Màn hình LED cảm ứng thông minh trên nắp hiển thị nhiệt độ thực tế chính xác",
    "Thiết kế công sở thanh lịch tối giản với nắp chống tràn 360° và đế silicone chống trượt",
]

# Product-neutral placeholders per Directorial Archetype, used only when the caller supplies no
# pain points / USPs for a product other than the bundled Lumina demo (never mug copy on a dress).
ARCHETYPE_DEFAULT_PAIN_POINTS: dict[ProductArchetype, list[str]] = {
    ProductArchetype.FASHION_APPAREL: [
        "Mặc đồ không tôn dáng, phom dáng lỗi mốt làm mất tự tin khi ra ngoài",
        "Chất vải nhanh nhăn, xù hoặc phai màu sau vài lần giặt",
        "Khó phối đồ, tủ quần áo đầy nhưng vẫn không biết mặc gì",
    ],
    ProductArchetype.TECH_GADGETS: [
        "Thiết bị cũ chậm, ồn hoặc hay trục trặc làm gián đoạn công việc hằng ngày",
        "Pin yếu, dây nhợ lằng nhằng gây phiền toái khi di chuyển",
        "Sản phẩm giá rẻ kém bền, nhanh hỏng sau vài tuần sử dụng",
    ],
    ProductArchetype.BEAUTY_SKINCARE: [
        "Da xỉn màu, thiếu sức sống dù đã thử nhiều sản phẩm",
        "Sợ sản phẩm không hợp da, gây kích ứng hoặc không thấy hiệu quả",
        "Quy trình chăm sóc da rườm rà, tốn thời gian mỗi ngày",
    ],
    ProductArchetype.HOME_LIFESTYLE: [
        "Không gian sống bừa bộn, thiếu ấm cúng sau một ngày dài",
        "Đồ gia dụng kém tiện dụng làm việc nhà thêm mệt mỏi",
        "Khó tìm món đồ vừa đẹp vừa hữu ích cho căn nhà",
    ],
    ProductArchetype.GENERAL_COMMERCIAL: [
        "Những phiền toái nhỏ lặp đi lặp lại mỗi ngày làm mất thời gian",
        "Sản phẩm trên thị trường kém bền, khó tin tưởng chất lượng",
        "Không biết chọn giải pháp nào thực sự đáng tiền",
    ],
}
ARCHETYPE_DEFAULT_USPS: dict[ProductArchetype, list[str]] = {
    ProductArchetype.FASHION_APPAREL: [
        "Phom dáng tôn vóc dáng, chuyển động tự nhiên khi mặc",
        "Chất liệu mềm mại, giữ form tốt khi sử dụng hằng ngày",
        "Dễ phối nhiều phong cách từ công sở đến dạo phố",
    ],
    ProductArchetype.TECH_GADGETS: [
        "Thao tác mượt mà, phản hồi xúc giác chắc chắn",
        "Thiết kế gọn nhẹ, dễ mang theo mọi nơi",
        "Hoàn thiện chắc chắn, bền bỉ trong sử dụng thực tế",
    ],
    ProductArchetype.BEAUTY_SKINCARE: [
        "Kết cấu thấm nhanh, dễ tán đều trên da",
        "Cảm giác da mềm mịn, căng bóng sau khi dùng",
        "Dễ đưa vào quy trình chăm sóc da hằng ngày",
    ],
    ProductArchetype.HOME_LIFESTYLE: [
        "Thiết kế tinh tế, hòa hợp với nhiều không gian sống",
        "Tiện dụng, giúp việc nhà nhẹ nhàng hơn",
        "Vật liệu an toàn, hoàn thiện chắc chắn",
    ],
    ProductArchetype.GENERAL_COMMERCIAL: [
        "Thiết kế tinh gọn, dễ sử dụng ngay từ lần đầu",
        "Hoàn thiện chắc chắn, đáng tin cậy",
        "Giải quyết trực tiếp vấn đề thường gặp hằng ngày",
    ],
}


def _coerce_enum(enum_cls, value, default, field: str):
    """Coerce a string into an enum, recording a telemetry note when an unknown value is replaced."""
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except ValueError:
        telemetry.note(
            f"Unknown {field} '{value}' replaced with '{default.value}'",
            field=field,
            requested=str(value),
            fallback=default.value,
        )
        return default


def create_product_brief(
    campaign_id: str = "campaign_lumina_mug_01",
    product_name: str = DEFAULT_PRODUCT_NAME,
    target_persona: str = "Dân văn phòng, freelancer, người trẻ hiện đại 22–35 tuổi yêu thích công nghệ và lối sống tinh tế",
    pain_points: list[str] | None = None,
    usps: list[str] | None = None,
    visual_tone: str | None = None,
    aspect_ratio: str = "9:16",
    archetype: ProductArchetype | str = ProductArchetype.GENERAL_COMMERCIAL,
    category: str | None = None,
    character_role: CharacterRole | str | None = None,
    target_audio_strategy: AudioStrategy | str | None = None,
    presenter: PresenterInfo | None = None,
    output_dir: Path | None = None,
    workspace: Optional[ProjectWorkspace] = None,
) -> BriefArtifact:
    """Generates and persists the canonical brief.json artifact."""
    archetype = _coerce_enum(ProductArchetype, archetype, ProductArchetype.GENERAL_COMMERCIAL, "archetype")
    arch_config = get_archetype_config(archetype)

    character_role = (
        arch_config.default_character_role
        if character_role is None
        else _coerce_enum(CharacterRole, character_role, arch_config.default_character_role, "character_role")
    )
    target_audio_strategy = (
        arch_config.default_audio_strategy
        if target_audio_strategy is None
        else _coerce_enum(AudioStrategy, target_audio_strategy, arch_config.default_audio_strategy, "target_audio_strategy")
    )

    if presenter is None:
        persona = DynamicPromptBuilder.resolve_persona(archetype)
        presenter = PresenterInfo(
            name=persona.name,
            character_tag=persona.character_tag,
            role=f"Lead {character_role.value.capitalize()}",
            character_file=persona.character_file,
        )

    is_demo_product = product_name == DEFAULT_PRODUCT_NAME
    if pain_points is None:
        pain_points = list(LUMINA_PAIN_POINTS if is_demo_product else ARCHETYPE_DEFAULT_PAIN_POINTS[archetype])
    if usps is None:
        usps = list(LUMINA_USPS if is_demo_product else ARCHETYPE_DEFAULT_USPS[archetype])
    if visual_tone is None:
        visual_tone = (
            DEFAULT_VISUAL_TONE
            if is_demo_product
            else f"{arch_config.display_name}: {arch_config.default_lighting.value} {arch_config.nominal_color_temp_kelvin}K, "
            f"{arch_config.motion_intensity} motion"
        )

    effective_campaign_id = campaign_id
    if workspace is not None:
        target_dir = workspace.artifacts_dir
        if campaign_id == "campaign_lumina_mug_01" and workspace.project_id:
            effective_campaign_id = workspace.project_id
    else:
        target_dir = output_dir or ARTIFACTS_DIR

    brief = BriefArtifact(
        campaign_id=effective_campaign_id,
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

    target_dir.mkdir(parents=True, exist_ok=True)
    out_file = target_dir / "brief.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(brief.model_dump(), f, ensure_ascii=False, indent=2)

    return brief


def create_product_brief_from_concept(
    creative_concept: Any,
    research: Any,
    output_dir: Path | None = None,
    workspace: Optional[ProjectWorkspace] = None,
) -> BriefArtifact:
    """Bridges winning CreativeConceptArtifact & CompetitorResearchArtifact into canonical BriefArtifact.

    The winning angle's Character Role / Audio Strategy and its directorial directives (lighting, camera
    pacing, key visual anchor) are carried into the brief so downstream stages direct what was chosen.
    """
    winning = creative_concept.winning_concept
    winning_angle = next(
        (opt for opt in creative_concept.concept_options if opt.angle_id == winning.selected_angle_id),
        creative_concept.concept_options[0],
    )
    product = research.product_intel
    directives = winning.directorial_directives

    pain_points = [o.objection for o in product.objection_matrix] if product.objection_matrix else (
        ARCHETYPE_DEFAULT_PAIN_POINTS[product.product_archetype][:2]
    )
    usps = product.dramatic_benefits if product.dramatic_benefits else product.features

    visual_tone = " | ".join(
        part
        for part in (winning_angle.title, directives.lighting_mood, directives.camera_pacing, directives.key_visual_anchor)
        if part
    )

    return create_product_brief(
        campaign_id=creative_concept.campaign_id,
        product_name=creative_concept.product_name,
        target_persona=winning_angle.target_audience_segment or research.primary_persona,
        pain_points=pain_points,
        usps=usps,
        visual_tone=visual_tone,
        archetype=product.product_archetype,
        category=product.category,
        character_role=winning_angle.character_role,
        target_audio_strategy=winning_angle.audio_strategy,
        output_dir=output_dir,
        workspace=workspace,
    )
