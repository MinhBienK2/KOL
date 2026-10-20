"""Tests for Product-to-Archetype Directorial Strategy, Character Routing & Cinematography Grammar."""

from pathlib import Path
import pytest

from pipeline.archetypes import (
    ARCHETYPE_REGISTRY,
    AudioStrategy,
    CameraChoreography,
    CharacterPersona,
    CharacterRole,
    DynamicPromptBuilder,
    LightingContract,
    PERSONA_CATALOG,
    ProductArchetype,
    WARDROBE_RULES,
    get_archetype_config,
    route_character_for_beat,
)
from pipeline.briefing import create_product_brief
from pipeline.scriptwriter import generate_commercial_script
from pipeline.schemas import BriefArtifact, ScriptArtifact, ScriptBeat


def test_archetype_configs_exist_and_complete():
    """Verify all 5 archetypes have full directorial specifications."""
    expected = [
        ProductArchetype.FASHION_APPAREL,
        ProductArchetype.TECH_GADGETS,
        ProductArchetype.BEAUTY_SKINCARE,
        ProductArchetype.HOME_LIFESTYLE,
        ProductArchetype.GENERAL_COMMERCIAL,
    ]
    for arch in expected:
        cfg = get_archetype_config(arch)
        assert cfg.archetype == arch
        assert len(cfg.beat_templates) >= 6
        assert cfg.nominal_color_temp_kelvin > 0
        assert len(cfg.primary_camera_motions) > 0
        assert cfg.motion_intensity in ("high", "medium", "subtle")


def test_fashion_archetype_no_speaking_head_required():
    """Fashion apparel must default to Model visual acting with music/sfx, NOT speaking head."""
    cfg = get_archetype_config(ProductArchetype.FASHION_APPAREL)
    assert cfg.default_character_role == CharacterRole.MODEL
    assert CharacterRole.PRESENTER not in cfg.allowed_character_roles
    assert cfg.default_audio_strategy == AudioStrategy.MUSIC_AND_SFX_ONLY
    assert CameraChoreography.ORBIT in cfg.primary_camera_motions


def test_tech_gadgets_tactile_and_macro_focus():
    """Tech gadgets must emphasize tactile unboxing and macro ports."""
    cfg = get_archetype_config(ProductArchetype.TECH_GADGETS)
    assert cfg.default_character_role == CharacterRole.PRODUCT_ONLY
    assert cfg.default_audio_strategy == AudioStrategy.ASMR_HYBRID
    assert CameraChoreography.TOP_DOWN_FLAT_LAY in cfg.primary_camera_motions
    assert CameraChoreography.STATIC_MACRO in cfg.primary_camera_motions


def test_beauty_skincare_sensory_macro_and_glow():
    """Beauty skincare must feature high-key beauty lighting, macro textures, and dewy glow."""
    cfg = get_archetype_config(ProductArchetype.BEAUTY_SKINCARE)
    assert cfg.default_character_role == CharacterRole.MODEL
    assert cfg.default_lighting == LightingContract.BEAUTY_HIGH_KEY
    assert cfg.default_audio_strategy == AudioStrategy.ASMR_HYBRID


def test_home_lifestyle_cozy_sanctuary():
    """Home lifestyle must feature golden hour / warm lighting and spatial camera motions."""
    cfg = get_archetype_config(ProductArchetype.HOME_LIFESTYLE)
    assert cfg.default_lighting == LightingContract.GOLDEN_HOUR
    assert cfg.nominal_color_temp_kelvin == 3200
    assert CameraChoreography.DRONE_FLYTHROUGH in cfg.primary_camera_motions


def test_character_role_prompt_suppression():
    """Crucial directive: PRODUCT_ONLY must suppress character faces/tags completely."""
    prompt_prod = DynamicPromptBuilder.build_subject_and_action_prompt(
        character_role=CharacterRole.PRODUCT_ONLY,
        archetype=ProductArchetype.TECH_GADGETS,
        product_name="CyberDock Pro 100W",
        scene_action="Tactile unboxing, peeling protective matte film",
    )
    # Character tag and face description must be omitted
    assert "[KOL_MAIN]" not in prompt_prod
    assert "[KOL_MA]" not in prompt_prod
    assert "Vietnamese young woman" not in prompt_prod
    assert "zero character face" in prompt_prod
    assert "CyberDock Pro 100W" in prompt_prod

    # MODEL role must prompt visual acting without speech cues
    prompt_model = DynamicPromptBuilder.build_subject_and_action_prompt(
        character_role=CharacterRole.MODEL,
        archetype=ProductArchetype.FASHION_APPAREL,
        product_name="Urban Trench Coat",
        scene_action="Runway walk and dynamic 360 pivot",
    )
    assert "Visual acting action" in prompt_model
    assert "speaking with clear engaged expression" not in prompt_model

    # PRESENTER role must prompt direct speaking delivery
    prompt_pres = DynamicPromptBuilder.build_subject_and_action_prompt(
        character_role=CharacterRole.PRESENTER,
        archetype=ProductArchetype.GENERAL_COMMERCIAL,
        product_name="Lumina Pro",
        scene_action="Direct recommendation with confident smile",
    )
    assert "Direct eye contact" in prompt_pres
    assert "speaking with clear engaged expression" in prompt_pres


def test_dynamic_wardrobe_adaptation():
    """Character wardrobe and setting must adapt dynamically per product category."""
    rule_fashion = WARDROBE_RULES[ProductArchetype.FASHION_APPAREL]
    assert "Wearing the featured fashion apparel item directly" in rule_fashion.wardrobe_directive
    assert "runway" in rule_fashion.environment_directive.lower()

    rule_beauty = WARDROBE_RULES[ProductArchetype.BEAUTY_SKINCARE]
    assert "silk loungewear robe" in rule_beauty.wardrobe_directive.lower()
    assert "bare collarbones" in rule_beauty.wardrobe_directive.lower()

    rule_home = WARDROBE_RULES[ProductArchetype.HOME_LIFESTYLE]
    assert "oversized ribbed cream knit sweater" in rule_home.wardrobe_directive.lower()


def test_character_routing_rules_engine():
    """Test algorithmic routing per beat across archetypes."""
    # Fashion beat 0: Model / MUSIC_AND_SFX_ONLY
    role, audio = route_character_for_beat(ProductArchetype.FASHION_APPAREL, 0, 6, "hook")
    assert role == CharacterRole.MODEL
    assert audio == AudioStrategy.MUSIC_AND_SFX_ONLY

    # Fashion beat 2 (fabric macro): Product-Only / MUSIC_AND_SFX_ONLY
    role, audio = route_character_for_beat(ProductArchetype.FASHION_APPAREL, 2, 6, "fabric_macro")
    assert role == CharacterRole.PRODUCT_ONLY
    assert audio == AudioStrategy.MUSIC_AND_SFX_ONLY

    # Tech beat 1 (unboxing): Product-Only / ASMR_HYBRID
    role, audio = route_character_for_beat(ProductArchetype.TECH_GADGETS, 1, 6, "unboxing")
    assert role == CharacterRole.PRODUCT_ONLY
    assert audio == AudioStrategy.ASMR_HYBRID

    # Tech beat 5 (cta closer): Presenter / ON_CAMERA_SPEECH
    role, audio = route_character_for_beat(ProductArchetype.TECH_GADGETS, 5, 6, "cta")
    assert role == CharacterRole.PRESENTER
    assert audio == AudioStrategy.ON_CAMERA_SPEECH


def test_scriptwriter_generates_all_archetypes(tmp_path: Path):
    """Test that scriptwriter synthesizes valid scripts for all 4 product archetypes."""
    archetypes = [
        (ProductArchetype.FASHION_APPAREL, "Áo Khoác Dạ Dáng Dài Thu Đông", "Dân sành điệu"),
        (ProductArchetype.TECH_GADGETS, "Bàn Phím Cơ Không Dây ErgoKey", "Lập trình viên, gamer"),
        (ProductArchetype.BEAUTY_SKINCARE, "Serum B5 Phục Hồi Căng Bóng GlowDrop", "Phụ nữ 20-35 da thiếu nước"),
        (ProductArchetype.HOME_LIFESTYLE, "Máy Xông Tinh Dầu Siêu Âm NordicMist", "Người yêu thích không gian sống thư thái"),
    ]

    for arch, prod_name, persona in archetypes:
        sub_dir = tmp_path / arch.value
        brief = create_product_brief(
            campaign_id=f"campaign_{arch.value}_test",
            product_name=prod_name,
            target_persona=persona,
            archetype=arch,
            output_dir=sub_dir,
        )
        assert brief.archetype == arch

        script = generate_commercial_script(brief=brief, output_dir=sub_dir)
        assert script.campaign_id == brief.campaign_id
        assert len(script.beats) == 6
        assert script.beats[0].beat_type == "hook"
        assert script.beats[-1].beat_type == "cta"
        assert script.beats[0].archetype == arch

        # Verify on-screen text and visual cues exist
        for beat in script.beats:
            assert len(beat.on_screen_text) > 0
            assert len(beat.visual_cue) > 0
            assert beat.estimated_duration > 0
            assert beat.camera_choreography is not None
            assert beat.lighting_contract is not None

def test_scene_plan_dynamic_archetypes(tmp_path: Path):
    """Verify scene planner translates archetype script beats into typed StoryboardShots."""
    from pipeline.storyboard import generate_scene_plan

    brief = create_product_brief(
        campaign_id="campaign_fashion_test",
        product_name="Minimalist Trench Coat",
        archetype=ProductArchetype.FASHION_APPAREL,
        output_dir=tmp_path,
    )
    script = generate_commercial_script(brief=brief, output_dir=tmp_path)
    scene_plan = generate_scene_plan(script=script, output_dir=tmp_path)

    assert len(scene_plan.shots) == 6
    # Check that fabric macro shot suppresses character tag
    macro_shot = [s for s in scene_plan.shots if s.character_role == CharacterRole.PRODUCT_ONLY][0]
    assert macro_shot.character_tag is None
    assert macro_shot.identity_lock_directive is None
    assert "zero character face" in macro_shot.prompt_6part

    # Check model runway shot retains model identity
    model_shot = [s for s in scene_plan.shots if s.character_role == CharacterRole.MODEL][0]
    assert model_shot.character_tag is not None
    assert "Visual acting action" in model_shot.prompt_6part
