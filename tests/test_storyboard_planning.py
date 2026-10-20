"""Stage 3: beat-aware framing, model-ready prompts, agent overrides, spatial contract."""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import storyboard
from pipeline.archetypes import CameraChoreography, CharacterRole, LightingContract, ProductArchetype
from pipeline.briefing import create_product_brief
from pipeline.cinematography import (
    CameraAngle,
    ShotScale,
    build_framing_directive,
    camera_phrase,
    compact_video_prompt,
    humanize_directive_tokens,
    plan_shot_scales,
)
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan

RAW_TOKENS = [c.value for c in CameraChoreography if "_" in c.value] + [
    l.value for l in LightingContract if "_" in l.value or l.value in ("studio_3point",)
]


def _plan(tmp_path: Path, arch: ProductArchetype, **kwargs):
    brief = create_product_brief(output_dir=tmp_path, archetype=arch, campaign_id=f"c_{arch.value}")
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    return script, generate_scene_plan(script=script, output_dir=tmp_path, **kwargs)


# --- cinematography helpers -------------------------------------------------------

def _beat(beat_type, role):
    return SimpleNamespace(beat_type=beat_type, character_role=role)


def test_plan_shot_scales_keeps_presenter_face_readable_and_varies():
    beats = [
        _beat("hook", CharacterRole.PRESENTER),
        _beat("pain_agitation", CharacterRole.PRESENTER),
        _beat("solution_reveal", CharacterRole.PRODUCT_ONLY),
        _beat("feature_demo", CharacterRole.PRESENTER),
        _beat("social_proof", CharacterRole.PRESENTER),
        _beat("cta", CharacterRole.PRESENTER),
    ]
    scales = plan_shot_scales(beats)
    assert len(scales) == len(beats)
    for beat, scale in zip(beats, scales):
        if beat.character_role == CharacterRole.PRESENTER:
            assert scale not in (ShotScale.WS, ShotScale.ELS, ShotScale.ECU), (beat.beat_type, scale)
    assert scales[0] == ShotScale.MCU  # scroll-stopping hook framing
    assert all(a != b for a, b in zip(scales, scales[1:])), scales


def test_plan_shot_scales_macro_for_product_texture_and_wide_for_model_hook():
    scales = plan_shot_scales(
        [_beat("hook", CharacterRole.MODEL), _beat("fabric_macro", CharacterRole.PRODUCT_ONLY), _beat("cta", CharacterRole.MODEL)]
    )
    assert scales == [ShotScale.WS, ShotScale.ECU, ShotScale.MS]


def test_humanize_replaces_enum_tokens():
    out = humanize_directive_tokens("Camera movement: top_down_flat_lay with studio_3point and zoom_in")
    for token in ("top_down_flat_lay", "studio_3point", "zoom_in"):
        assert token not in out
    assert camera_phrase("zoom_in", short=False) in out


def test_framing_natural_clause_has_no_bracketed_enums():
    clause = build_framing_directive(ShotScale.WS, focal_point="Mai Ly").to_natural_clause()
    assert "[" not in clause and "_" not in clause
    assert "wide" in clause and "24mm" in clause and "Mai Ly" in clause


def test_compact_video_prompt_dedupes_cleans_and_caps():
    messy = (
        "Wide shot. Subject: a woman, 8k.. Environment: old room. Same sentence here. Same sentence here. "
        "SET: a bright studio with a walnut desk. WEAR: black hoodie. " + "Filler detail words. " * 80
    )
    out = compact_video_prompt(messy, max_words=60)
    assert ".." not in out and "8k" not in out
    assert out.count("Same sentence here") == 1
    assert "Environment:" not in out  # superseded by SET:
    assert "SET:" in out and "WEAR:" in out


def test_compact_video_prompt_sheds_coaching_text_only_over_budget():
    text = "Wide shot. Poise: be elegant and confident at all times. SET: a studio. WEAR: a coat."
    assert "Poise:" in compact_video_prompt(text, max_words=100)
    assert "Poise:" not in compact_video_prompt(text, max_words=8)
    assert "SET:" in compact_video_prompt(text, max_words=8)


# --- storyboard --------------------------------------------------------------------

@pytest.mark.parametrize("arch", [a for a in ProductArchetype])
def test_prompts_are_model_ready(tmp_path: Path, arch):
    _, plan = _plan(tmp_path, arch)
    for shot in plan.shots:
        p = shot.prompt_6part
        for token in RAW_TOKENS:
            assert token not in p, (shot.shot_id, token)
        assert ".." not in p
        assert "8k" not in p.lower()
        assert p.count("SET:") == 1
        assert len(p.split()) <= 200, (shot.shot_id, len(p.split()))


def test_product_isolation_survives_prompt_compaction(tmp_path: Path):
    _, plan = _plan(tmp_path, ProductArchetype.FASHION_APPAREL)
    macro = [s for s in plan.shots if s.character_role == CharacterRole.PRODUCT_ONLY][0]
    assert "zero character face" in macro.prompt_6part
    assert "WEAR:" not in macro.prompt_6part
    model = [s for s in plan.shots if s.character_role == CharacterRole.MODEL][0]
    assert "Visual acting action" in model.prompt_6part and "WEAR:" in model.prompt_6part


@pytest.mark.parametrize("arch", [a for a in ProductArchetype])
def test_every_shot_declares_intent_and_fair_risk_score(tmp_path: Path, arch):
    script, plan = _plan(tmp_path, arch)
    for beat, shot in zip(script.beats, plan.shots):
        assert shot.shot_intent and beat.beat_type in shot.shot_intent
    dims = plan.slideshow_risk["dimensions"]
    assert dims["weak_shot_intent"]["score"] == 0.0
    # Vietnamese cues carry kinetic verbs, so the motion dimension must not blame every shot
    assert "6/6 shots lack active kinetic" not in dims["weak_motion"]["reason"]


def test_presenter_shots_are_never_wide(tmp_path: Path):
    script, plan = _plan(tmp_path, ProductArchetype.GENERAL_COMMERCIAL)
    for beat, shot in zip(script.beats, plan.shots):
        if beat.character_role == CharacterRole.PRESENTER:
            assert not shot.shot_type.startswith(("WIDE_SHOT", "EXTREME_LONG_SHOT")), shot.shot_type


def test_contact_sheet_receives_real_framing_metadata(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_sheet(shots, output_path, campaign_title=""):
        captured["shots"] = shots
        Path(output_path).write_bytes(b"jpg")
        return str(output_path)

    monkeypatch.setattr(storyboard, "generate_storyboard_contact_sheet", fake_sheet)
    _plan(tmp_path, ProductArchetype.TECH_GADGETS)
    shots = captured["shots"]
    assert len({s["shot_scale"] for s in shots}) > 1
    assert all(s.get("lens") and s.get("shot_intent") for s in shots)


def test_agent_can_override_framing_per_shot(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path, archetype=ProductArchetype.GENERAL_COMMERCIAL, campaign_id="c_ov")
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=ProductArchetype.GENERAL_COMMERCIAL)
    overrides = {
        script.beats[0].scene_id: {"shot_scale": "extreme_macro", "angle": CameraAngle.DUTCH.value, "extra_direction": "rain on the window"},
        "shot_02": {"shot_scale": ShotScale.WS},
    }
    plan = generate_scene_plan(script=script, output_dir=tmp_path, shot_overrides=overrides)
    first, second = plan.shots[0], plan.shots[1]
    assert first.shot_type.startswith("EXTREME_MACRO")
    assert first.angle == CameraAngle.DUTCH.value
    assert "rain on the window" in first.prompt_6part
    assert second.shot_type.startswith("WIDE_SHOT")


def test_unknown_override_scale_is_rejected(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path, archetype=ProductArchetype.GENERAL_COMMERCIAL, campaign_id="c_bad")
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=ProductArchetype.GENERAL_COMMERCIAL)
    with pytest.raises(ValueError, match="shot_scale"):
        generate_scene_plan(script=script, output_dir=tmp_path, shot_overrides={"shot_01": {"shot_scale": "banana"}})


def test_scene_plan_carries_spatial_staging_contract(tmp_path: Path):
    _, plan = _plan(tmp_path, ProductArchetype.BEAUTY_SKINCARE)
    contract = plan.spatial_staging_contract
    assert contract and contract["nominal_kelvin"] > 0
    assert contract["continuity_ok"] is True
    assert all(s.spatial_staging for s in plan.shots)
    assert all(re.search(r"\d+K", s.spatial_staging) for s in plan.shots)
