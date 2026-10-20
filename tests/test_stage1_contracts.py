"""Stage 1 contract tests: archetype detection, grounded fallbacks, winner selection, brief bridge."""

import json
from pathlib import Path

import pytest

from pipeline.archetypes import (
    AudioStrategy,
    CharacterRole,
    ProductArchetype,
    classify_product_archetype,
    get_archetype_config,
)
from pipeline.briefing import create_product_brief, create_product_brief_from_concept
from pipeline.researcher import (
    CompetitorLandscape,
    CompetitorResearchArtifact,
    ProductIntel,
    extract_metadata_from_html,
    extract_price_from_text,
    extract_product_intel,
    generate_creative_concepts,
    run_research_pipeline,
)
from pipeline.topics import TopicCatalog


# ---------------------------------------------------------------- archetype detection

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Đầm Corset Họa Tiết Cherry Nữ Phom Ôm", ProductArchetype.FASHION_APPAREL),
        ("Áo khoác blazer nữ form rộng", ProductArchetype.FASHION_APPAREL),
        ("Bàn Phím Cơ Không Dây CyberKey RGB Bluetooth", ProductArchetype.TECH_GADGETS),
        ("Wireless earbuds with active noise cancelling", ProductArchetype.TECH_GADGETS),
        ("Serum Vitamin C dưỡng trắng da căng bóng", ProductArchetype.BEAUTY_SKINCARE),
        ("Kem chống nắng SPF50 cho da dầu", ProductArchetype.BEAUTY_SKINCARE),
        ("Nến thơm tinh dầu decor phòng khách ấm cúng", ProductArchetype.HOME_LIFESTYLE),
        ("Random thing with no clues", ProductArchetype.GENERAL_COMMERCIAL),
        ("", ProductArchetype.GENERAL_COMMERCIAL),
    ],
)
def test_classify_product_archetype(text, expected):
    assert classify_product_archetype(text) == expected


def test_classify_is_accent_and_case_insensitive():
    assert classify_product_archetype("SERUM DUONG DA") == ProductArchetype.BEAUTY_SKINCARE


def test_topic_catalog_classify_returns_definition():
    topic = TopicCatalog.classify("Bàn phím cơ gaming")
    assert topic.archetype == ProductArchetype.TECH_GADGETS


def test_pipeline_autodetects_archetype_when_unspecified(tmp_path: Path):
    research, _ = run_research_pipeline(
        product_input="Serum Vitamin C dưỡng trắng da căng bóng 30ml",
        output_dir=tmp_path,
        use_llm=False,
    )
    assert research.product_intel.product_archetype == ProductArchetype.BEAUTY_SKINCARE


def test_pipeline_respects_explicit_archetype(tmp_path: Path):
    research, _ = run_research_pipeline(
        product_input="Serum Vitamin C dưỡng trắng da",
        archetype=ProductArchetype.HOME_LIFESTYLE,
        output_dir=tmp_path,
        use_llm=False,
    )
    assert research.product_intel.product_archetype == ProductArchetype.HOME_LIFESTYLE


# ---------------------------------------------------------------- grounded fallbacks

@pytest.mark.parametrize(
    "text,price",
    [
        ("Giá chỉ 299.000đ hôm nay", 299000.0),
        ("Price: 389,000 VND", 389000.0),
        ("Chỉ 1.299.000 ₫", 1299000.0),
        ("Only $29.99", 29.99),
        ("no price here", 0.0),
    ],
)
def test_extract_price_from_text(text, price):
    got, _currency = extract_price_from_text(text)
    assert got == pytest.approx(price)


def test_fallback_intel_does_not_fabricate_price():
    intel = extract_product_intel("Lumina Pro Smart Thermos Mug\n500ml ceramic liner", use_llm=False)
    assert intel.pricing.current_price == 0.0
    assert intel.pricing.discount_percent is None
    assert intel.source == "heuristic_fallback"


def test_fallback_intel_reads_price_and_features_from_input():
    raw = "Tai nghe Bluetooth Aero X\nGiá 450.000đ\nPin 40 giờ liên tục\nChống ồn chủ động ANC"
    intel = extract_product_intel(raw, use_llm=False)
    assert intel.title == "Tai nghe Bluetooth Aero X"
    assert intel.pricing.current_price == pytest.approx(450000.0)
    assert any("Pin 40 giờ" in f for f in intel.features)


def test_fallback_intel_has_no_invented_numeric_proof():
    intel = extract_product_intel("Gối ôm nhồi bông", use_llm=False)
    blob = json.dumps(intel.model_dump(), ensure_ascii=False)
    assert "10.000" not in blob and "50%" not in blob


def test_price_anchor_not_fabricated_without_price(tmp_path: Path):
    research, _ = run_research_pipeline("Gối ôm nhồi bông", output_dir=tmp_path, use_llm=False)
    assert research.price_anchor_strategy == ""


def test_metadata_extracts_meta_with_reversed_attribute_order():
    html = '<meta content="Giá tốt" property="og:description"><meta content="T" name="description">'
    meta = extract_metadata_from_html(html)
    assert meta["og_description"] == "Giá tốt"


# ---------------------------------------------------------------- creative concepts

def _research(archetype, awareness="Problem Aware") -> CompetitorResearchArtifact:
    return CompetitorResearchArtifact(
        campaign_id="c1",
        product_intel=ProductIntel(
            title="Sản phẩm X",
            product_archetype=archetype,
            awareness_level=awareness,
            features=["a", "b", "c"],
            dramatic_benefits=["x", "y"],
        ),
        competitor_landscape=CompetitorLandscape(),
    )


@pytest.mark.parametrize("archetype", list(ProductArchetype))
def test_angles_conform_to_archetype_role_and_audio_rules(archetype):
    cfg = get_archetype_config(archetype)
    concepts = generate_creative_concepts(_research(archetype), use_llm=False)
    for angle in concepts.concept_options:
        assert angle.character_role in cfg.allowed_character_roles
        assert angle.audio_strategy in cfg.allowed_audio_strategies
        if angle.audio_strategy == AudioStrategy.ON_CAMERA_SPEECH:
            assert angle.character_role == CharacterRole.PRESENTER
        if angle.character_role == CharacterRole.PRESENTER:
            assert angle.audio_strategy == AudioStrategy.ON_CAMERA_SPEECH


def test_fashion_winner_is_sensory_angle_not_hardcoded_shock():
    concepts = generate_creative_concepts(_research(ProductArchetype.FASHION_APPAREL), use_llm=False)
    assert concepts.winning_concept.selected_angle_id == "angle_b_aesthetic_sensory"


def test_tech_problem_aware_winner_stays_shock():
    concepts = generate_creative_concepts(_research(ProductArchetype.TECH_GADGETS), use_llm=False)
    assert concepts.winning_concept.selected_angle_id == "angle_a_shock_interrupt"


def test_winner_is_first_option_for_downstream_readers():
    # scriptwriter reads concept_options[0] as the winner
    for arch in ProductArchetype:
        concepts = generate_creative_concepts(_research(arch), use_llm=False)
        assert concepts.concept_options[0].angle_id == concepts.winning_concept.selected_angle_id


def test_directives_use_archetype_lighting_vocabulary():
    concepts = generate_creative_concepts(_research(ProductArchetype.BEAUTY_SKINCARE), use_llm=False)
    cfg = get_archetype_config(ProductArchetype.BEAUTY_SKINCARE)
    d = concepts.winning_concept.directorial_directives
    assert cfg.default_lighting.value in d.lighting_mood
    assert f"{cfg.nominal_color_temp_kelvin}K" in d.lighting_mood


def test_angle_c_hook_is_not_mug_specific():
    concepts = generate_creative_concepts(_research(ProductArchetype.FASHION_APPAREL), use_llm=False)
    angle_c = next(a for a in concepts.concept_options if a.angle_id == "angle_c_problem_agitation")
    blob = json.dumps(angle_c.model_dump(), ensure_ascii=False).lower()
    assert "tài liệu" not in blob and "nước đổ" not in blob and "bàn làm việc" not in blob


def test_llm_output_is_repaired_and_linted(monkeypatch):
    from pipeline import researcher

    long_hook = " ".join(["từ"] * 30)
    payload = json.dumps({
        "concept_options": [
            {
                "angle_id": f"angle_{i}", "angle_archetype": "x", "title": "t",
                "target_audience_segment": "s", "character_role": "presenter",
                "audio_strategy": "on_camera_speech",
                "hook_strategy": {"spoken_hook": long_hook, "visual_hook": "v",
                                  "on_screen_text": "T", "retention_trigger": "r"},
                "narrative_arc": [], "conversion_thesis": "c",
                "projected_retention_score": 99, "projected_conversion_score": 8,
            } for i in range(3)
        ],
        "winning_concept": {
            "selected_angle_id": "does_not_exist", "selection_rationale": "r",
            "confidence_score": 7,
            "directorial_directives": {"camera_pacing": "p", "lighting_mood": "l", "key_visual_anchor": "k"},
        },
    })
    monkeypatch.setattr(researcher, "call_llm", lambda *a, **k: payload)
    concepts = generate_creative_concepts(_research(ProductArchetype.GENERAL_COMMERCIAL), use_llm=True)
    ids = [a.angle_id for a in concepts.concept_options]
    assert concepts.winning_concept.selected_angle_id in ids
    assert concepts.concept_options[0].angle_id == concepts.winning_concept.selected_angle_id
    assert all(1.0 <= a.projected_retention_score <= 10.0 for a in concepts.concept_options)
    assert 0.0 <= concepts.winning_concept.confidence_score <= 1.0
    assert concepts.metadata["hook_lint"]


# ---------------------------------------------------------------- brief

def test_brief_from_concept_carries_winning_directives(tmp_path: Path):
    research, concept = run_research_pipeline(
        "Bàn phím cơ không dây CyberKey", output_dir=tmp_path, use_llm=False
    )
    brief = create_product_brief_from_concept(concept, research, output_dir=tmp_path)
    d = concept.winning_concept.directorial_directives
    assert d.lighting_mood in brief.visual_tone
    assert d.camera_pacing in brief.visual_tone
    winner = concept.concept_options[0]
    assert brief.character_role == winner.character_role
    assert brief.target_audio_strategy == winner.audio_strategy


def test_default_brief_is_not_mug_specific_for_other_products(tmp_path: Path):
    brief = create_product_brief(
        product_name="Đầm Corset Cherry", archetype=ProductArchetype.FASHION_APPAREL, output_dir=tmp_path
    )
    blob = " ".join(brief.pain_points + brief.usps).lower()
    assert "cà phê" not in blob and "giữ nhiệt" not in blob and "lumina" not in blob
    assert len(brief.pain_points) == 3 and len(brief.usps) == 3


def test_brief_unknown_archetype_string_falls_back(tmp_path: Path):
    brief = create_product_brief(archetype="not_real", output_dir=tmp_path)
    assert brief.archetype == ProductArchetype.GENERAL_COMMERCIAL


# ---------------------------------------------------------------- page ingestion & archetype invariants

def test_build_page_content_includes_json_ld_price():
    from pipeline.researcher import build_page_content

    html = (
        '<title>Mug</title><meta content="Mug đẹp" property="og:description">'
        '<script type="application/ld+json">{"@type":"Product","offers":{"price":"389000","priceCurrency":"VND"}}</script>'
        "<body>Nắp chống tràn</body>"
    )
    content = build_page_content(extract_metadata_from_html(html))
    assert "Price: 389000 VND" in content
    intel = extract_product_intel(content, use_llm=False)
    assert intel.pricing.current_price == pytest.approx(389000.0)


@pytest.mark.parametrize("archetype", list(ProductArchetype))
def test_archetype_hook_beat_is_short_and_roles_allowed(archetype):
    cfg = get_archetype_config(archetype)
    hook = cfg.beat_templates[0]
    assert hook.beat_type == "hook" and hook.target_duration <= 3.5
    for beat in cfg.beat_templates:
        assert beat.recommended_role in cfg.allowed_character_roles
        assert beat.audio_strategy in cfg.allowed_audio_strategies
        if beat.audio_strategy == AudioStrategy.ON_CAMERA_SPEECH:
            assert beat.recommended_role == CharacterRole.PRESENTER
