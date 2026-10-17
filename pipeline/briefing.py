"""Step 1: Product Briefing & USP Analysis."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from pipeline.config import ARTIFACTS_DIR
from pipeline.schemas import BriefArtifact, PresenterInfo


def create_product_brief(
    campaign_id: str = "campaign_lumina_mug_01",
    product_name: str = "Ly Giữ Nhiệt Thông Minh Lumina Pro",
    target_persona: str = "Dân văn phòng, freelancer, người trẻ hiện đại 22–35 tuổi yêu thích công nghệ và lối sống tinh tế",
    pain_points: list[str] | None = None,
    usps: list[str] | None = None,
    visual_tone: str = "Sang trọng, hiện đại, tối giản công sở, chuẩn ánh sáng studio cao cấp",
    aspect_ratio: str = "9:16",
    output_dir: Path | None = None,
) -> BriefArtifact:
    """Generates and persists the canonical brief.json artifact."""
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
        presenter=PresenterInfo(
            name="Minh Anh",
            character_tag="[KOL_MA]",
            role="Lead Presenter / Protagonist",
            character_file="assets/characters/kol_main/character.json",
        ),
    )

    target_dir = output_dir or ARTIFACTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    out_file = target_dir / "brief.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(brief.model_dump(), f, ensure_ascii=False, indent=2)

    return brief
