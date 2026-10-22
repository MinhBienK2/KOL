"""Unit and integration tests for Competitor & Viral Angle Research Engine."""

import json
from pathlib import Path
import pytest

from pipeline.archetypes import AudioStrategy, CharacterRole, ProductArchetype
from pipeline.researcher import (
    CompetitorLandscape,
    CompetitorResearchArtifact,
    CreativeAngle,
    CreativeConceptArtifact,
    ObjectionProof,
    ProductIntel,
    ProductPricing,
    SelectedWinningAngle,
    ViralHookCandidate,
    extract_metadata_from_html,
    extract_product_intel,
    generate_creative_concepts,
    resolve_affiliate_url,
    run_research_pipeline,
    synthesize_competitor_and_hooks,
)


SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Lumina Pro Smart Thermos Mug 500ml - LED Temperature Display</title>
    <meta property="og:title" content="Lumina Pro Smart Thermos Mug - 500ml Stainless Steel">
    <meta property="og:description" content="Keep your drinks 12h hot and 24h cold. Smart LED touch display.">
    <script type="application/ld+json">
    {
      "@context": "https://schema.org/",
      "@type": "Product",
      "name": "Lumina Pro Smart Thermos Mug",
      "description": "Double vacuum insulated coffee mug with touch LED lid",
      "offers": {
        "@type": "Offer",
        "price": "389000",
        "priceCurrency": "VND"
      }
    }
    </script>
</head>
<body>
    <h1>Lumina Pro Smart Thermos</h1>
    <p>Lõi sứ Nano không bám mùi cà phê. Màn hình LED cảm ứng chống nước IPX7. Nắp chống tràn 360 độ an toàn bỏ túi xách.</p>
</body>
</html>
"""


def test_extract_metadata_from_html():
    meta = extract_metadata_from_html(SAMPLE_HTML)
    assert meta["title"] == "Lumina Pro Smart Thermos Mug 500ml - LED Temperature Display"
    assert meta["og_title"] == "Lumina Pro Smart Thermos Mug - 500ml Stainless Steel"
    assert "12h hot" in meta["og_description"]
    assert len(meta["json_ld"]) == 1
    assert meta["json_ld"][0]["name"] == "Lumina Pro Smart Thermos Mug"
    assert "Lõi sứ Nano" in meta["body_text"]


def test_extract_product_intel_deterministic():
    intel = extract_product_intel(
        raw_content="Lumina Pro Smart Thermos Mug\n500ml ceramic inner liner, touch LED cap, leakproof.",
        product_archetype=ProductArchetype.TECH_GADGETS,
        use_llm=False,
    )
    assert isinstance(intel, ProductIntel)
    assert intel.product_archetype == ProductArchetype.TECH_GADGETS
    assert len(intel.features) >= 3
    assert len(intel.dramatic_benefits) >= 3
    assert len(intel.objection_matrix) >= 2
    # Heuristic fallback must not invent a price when the input has none
    assert intel.pricing.current_price == 0


def test_synthesize_competitor_and_hooks_deterministic():
    intel = extract_product_intel(
        raw_content="Lumina Pro Smart Thermos Mug",
        product_archetype=ProductArchetype.HOME_LIFESTYLE,
        use_llm=False,
    )
    landscape, hooks = synthesize_competitor_and_hooks(intel, use_llm=False)
    assert isinstance(landscape, CompetitorLandscape)
    assert len(landscape.saturated_angles) >= 2
    assert len(landscape.competitor_weaknesses) >= 2
    assert len(landscape.whitespace_opportunities) >= 2

    assert len(hooks) >= 3
    hook_types = [h.hook_type for h in hooks]
    assert "shock_interrupt" in hook_types
    assert "sensory_asmr" in hook_types
    assert "problem_agitation" in hook_types


def test_generate_creative_concepts_three_distinct_angles():
    intel = ProductIntel(
        title="Lumina Pro Smart Thermos",
        category="Drinkware",
        product_archetype=ProductArchetype.TECH_GADGETS,
        pricing=ProductPricing(current_price=389000, original_price=550000, discount_percent=29),
        features=["Lõi sứ nano", "Nắp LED cảm ứng", "Chống tràn 360"],
        dramatic_benefits=["Cà phê luôn thơm nóng 12 tiếng", "Không bao giờ lo ướt hồ sơ bàn làm việc"],
        target_personas=["Dân văn phòng hiện đại", "Freelancer"],
        objection_matrix=[
            ObjectionProof(
                objection="Liệu có bị rỉ nước trong ba lô?",
                counter_evidence="Khóa gioăng silicone 360 áp suất kép",
                demonstration_technique="Dốc ngược lắc mạnh trên bề mặt laptop",
            )
        ],
    )
    research = CompetitorResearchArtifact(
        campaign_id="test_camp_01",
        product_intel=intel,
        competitor_landscape=CompetitorLandscape(
            saturated_angles=["Review unboxing nhàm chán"],
            competitor_weaknesses=["Mùi kim loại nồng"],
            whitespace_opportunities=["Thử thách dốc ngược trực tiếp"],
        ),
        viral_hook_library=[],
    )

    concepts = generate_creative_concepts(research, use_llm=False)
    assert isinstance(concepts, CreativeConceptArtifact)
    assert len(concepts.concept_options) == 3

    # Check Angle A: Shock / Pattern Interrupt
    angle_a = next(c for c in concepts.concept_options if c.angle_id == "angle_a_shock_interrupt")
    assert angle_a.character_role == CharacterRole.PRESENTER
    assert angle_a.audio_strategy == AudioStrategy.ON_CAMERA_SPEECH
    assert "THỬ THÁCH" in angle_a.hook_strategy.on_screen_text

    # Check Angle B: Aesthetic / Sensory / ASMR
    angle_b = next(c for c in concepts.concept_options if c.angle_id == "angle_b_aesthetic_sensory")
    assert angle_b.character_role == CharacterRole.MODEL
    assert angle_b.audio_strategy == AudioStrategy.ASMR_HYBRID

    # Check Angle C: Direct Problem-Agitation
    angle_c = next(c for c in concepts.concept_options if c.angle_id == "angle_c_problem_agitation")
    assert angle_c.character_role == CharacterRole.PRESENTER
    assert "THẢM CẢNH" in angle_c.hook_strategy.on_screen_text

    # Check Winning Angle Selection
    assert concepts.winning_concept.selected_angle_id == "angle_a_shock_interrupt"
    assert concepts.winning_concept.confidence_score >= 0.85
    assert concepts.winning_concept.directorial_directives.camera_pacing != ""


def test_run_research_pipeline_end_to_end(tmp_path: Path):
    research_art, concept_art = run_research_pipeline(
        product_input="Ly Giữ Nhiệt Thông Minh Lumina Pro 500ml",
        campaign_id="test_campaign_e2e",
        archetype=ProductArchetype.TECH_GADGETS,
        output_dir=tmp_path,
        use_llm=False,
    )

    # Validate returned objects
    assert research_art.campaign_id == "test_campaign_e2e"
    assert concept_art.campaign_id == "test_campaign_e2e"
    assert len(concept_art.concept_options) == 3
    assert concept_art.winning_concept.selected_angle_id in ["angle_a_shock_interrupt", "angle_b_aesthetic_sensory", "angle_c_problem_agitation"]

    # Validate persisted files
    research_file = tmp_path / "competitor_research.json"
    concept_file = tmp_path / "creative_concept.json"
    assert research_file.exists()
    assert concept_file.exists()

    with open(research_file, "r", encoding="utf-8") as f:
        loaded_res = CompetitorResearchArtifact.model_validate(json.load(f))
    assert loaded_res.campaign_id == "test_campaign_e2e"

    with open(concept_file, "r", encoding="utf-8") as f:
        loaded_concept = CreativeConceptArtifact.model_validate(json.load(f))
    assert loaded_concept.product_name == research_art.product_intel.title


def test_create_product_brief_from_concept(tmp_path: Path):
    from pipeline.briefing import create_product_brief_from_concept
    research_art, concept_art = run_research_pipeline(
        product_input="Ly Giữ Nhiệt Lumina Pro",
        campaign_id="test_camp_bridge",
        archetype=ProductArchetype.TECH_GADGETS,
        output_dir=tmp_path,
        use_llm=False,
    )
    brief = create_product_brief_from_concept(concept_art, research_art, output_dir=tmp_path)
    assert brief.campaign_id == "test_camp_bridge"
    assert brief.archetype == ProductArchetype.TECH_GADGETS
    assert brief.character_role == CharacterRole.PRESENTER
    assert (tmp_path / "brief.json").exists()


AUDIENCE = "Sinh viên năm nhất 18-20 tuổi mới lên thành phố, ở trọ, đi học và đi làm thêm bằng xe đạp"


def test_client_audience_becomes_persona_and_every_segment(tmp_path: Path):
    # QA preprod r1: the audience was in --url and the concepts still targeted "người dùng phổ thông 18-45".
    from pipeline.briefing import create_product_brief_from_concept

    research_art, concept_art = run_research_pipeline(
        product_input="Xe đạp Thống Nhất MTB 26-02, một tốc độ, phanh đĩa",
        campaign_id="aud", archetype=ProductArchetype.GENERAL_COMMERCIAL,
        output_dir=tmp_path, use_llm=False, audience=AUDIENCE,
    )
    assert research_art.primary_persona == AUDIENCE
    assert {a.target_audience_segment for a in concept_art.concept_options} == {AUDIENCE}
    brief = create_product_brief_from_concept(concept_art, research_art, output_dir=tmp_path)
    assert brief.target_persona == AUDIENCE


def test_llm_concepts_are_asked_for_the_audience_and_a_controlling_idea(tmp_path: Path, monkeypatch):
    from pipeline import researcher

    research_art, _ = run_research_pipeline(
        product_input="Xe đạp Thống Nhất MTB 26-02", campaign_id="aud_llm",
        archetype=ProductArchetype.GENERAL_COMMERCIAL, output_dir=tmp_path, use_llm=False,
    )
    seen = {}
    angle = {
        "angle_id": "angle_c_problem_agitation", "angle_archetype": "direct_problem_agitation", "title": "T",
        "target_audience_segment": "Người dùng phổ thông 18-45", "controlling_idea": "Ở thành phố lạ, chiếc xe là tự do đầu tiên.",
        "key_visual": "Chiếc xe đỏ dựng ở cửa phòng trọ lúc 6 giờ sáng", "character_role": "presenter",
        "audio_strategy": "on_camera_speech",
        "hook_strategy": {"spoken_hook": "Tuần đầu ở trọ.", "visual_hook": "v", "on_screen_text": "TUẦN ĐẦU", "retention_trigger": "r"},
        "narrative_arc": ["a"], "conversion_thesis": "c",
    }

    def fake_llm(system, user, **_):
        seen["system"], seen["user"] = system, user
        others = [dict(angle, angle_id=i, angle_archetype=i) for i in ("angle_a_shock_interrupt", "angle_b_aesthetic_sensory")]
        return json.dumps({"concept_options": [angle, *others], "winning_concept": {}})

    monkeypatch.setattr(researcher, "call_llm", fake_llm)
    monkeypatch.setattr(researcher, "is_offline", lambda: False)
    concept = generate_creative_concepts(research_art, use_llm=True, audience=AUDIENCE)
    assert AUDIENCE in seen["user"] and "controlling_idea" in seen["system"]
    assert "strawman" in seen["system"] and "comparison" in seen["system"]
    llm_angle = next(a for a in concept.concept_options if a.angle_id == "angle_c_problem_agitation")
    assert llm_angle.target_audience_segment == AUDIENCE
    assert llm_angle.controlling_idea.startswith("Ở thành phố lạ")
