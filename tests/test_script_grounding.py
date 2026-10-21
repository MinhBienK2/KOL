"""Round 2 script/storyboard: grounded copy, English visual cues, persisted direction, persona."""

import json
import re
from pathlib import Path

import pytest

from pipeline.archetypes import CameraChoreography, DynamicPromptBuilder, LightingContract, ProductArchetype
from pipeline.briefing import create_product_brief
from pipeline.cinematography import CameraAngle, CameraLens, ShotScale
from pipeline.composer import SUPPORTED_TRANSITIONS
from pipeline.schemas import ScriptArtifact, ScriptBeat
from pipeline.scriptwriter import (
    BANNED_CLAIM_PHRASES,
    MAX_BEAT_SECONDS,
    NUMERIC_CLAIM_RE,
    find_unsupported_claims,
    generate_commercial_script,
    validate_script,
)
from pipeline.storyboard import generate_scene_plan

NO_OFFER_USPS = ["Thiết kế gọn nhẹ dễ mang theo", "Chất liệu mềm mại thoáng khí", "Dễ phối với nhiều phong cách"]
NO_OFFER_PAINS = ["Sản phẩm cũ khó dùng", "Mất nhiều thời gian chuẩn bị"]

# The claim lint lives in pipeline.scriptwriter so LLM drafts are held to the same standard.
BANNED_WORDS = BANNED_CLAIM_PHRASES
NUMERIC_CLAIM = NUMERIC_CLAIM_RE


def _brief(tmp_path: Path, arch: ProductArchetype, name: str = "Sản Phẩm Thử Nghiệm Aurora"):
    return create_product_brief(
        campaign_id=f"c_{arch.value}",
        product_name=name,
        archetype=arch,
        pain_points=NO_OFFER_PAINS,
        usps=NO_OFFER_USPS,
        output_dir=tmp_path,
    )


def _beat_texts(beat: ScriptBeat) -> list:
    return [beat.spoken_text, beat.on_screen_text, beat.visual_cue, beat.visual_cue_en or ""]


@pytest.mark.parametrize("arch", list(ProductArchetype))
def test_scripts_never_invent_offers_or_numbers(tmp_path: Path, arch):
    brief = _brief(tmp_path, arch)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    for beat in script.beats:
        for text in _beat_texts(beat):
            low = text.lower()
            for word in BANNED_WORDS:
                assert word not in low, (arch.value, beat.scene_id, word, text)
            assert not NUMERIC_CLAIM.search(low), (arch.value, beat.scene_id, text)
            # No digit at all: the brief supplied none, so none may appear.
            assert not re.search(r"\d", text), (arch.value, beat.scene_id, text)
    assert find_unsupported_claims(script, brief) == []


def test_legacy_mug_script_has_no_invented_offer(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path)
    for beat in script.beats:
        for text in _beat_texts(beat):
            low = text.lower()
            assert "%" not in low and "ưu đãi" not in low and "°c" not in low, text
    assert all(b.estimated_duration <= MAX_BEAT_SECONDS for b in script.beats)
    assert validate_script(script.beats) == []


def test_offer_from_brief_is_used_verbatim_in_cta(tmp_path: Path):
    brief = _brief(tmp_path, ProductArchetype.TECH_GADGETS)
    brief.offers = ["Giảm 15% đến hết tuần này"]
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=ProductArchetype.TECH_GADGETS)
    cta = script.beats[-1]
    assert "15%" in cta.spoken_text and "15%" in cta.on_screen_text.replace("GIẢM", "")
    # ...and only the CTA carries it
    assert all("15%" not in b.spoken_text for b in script.beats[:-1])


def _write_research(tmp_path: Path, source: str, discount):
    (tmp_path / "competitor_research.json").write_text(
        json.dumps(
            {
                "campaign_id": "c",
                "product_intel": {
                    "title": "x",
                    "source": source,
                    "pricing": {"current_price": 199000, "discount_percent": discount, "currency": "VND"},
                },
            }
        ),
        encoding="utf-8",
    )


def test_research_offer_used_only_when_trusted(tmp_path: Path):
    arch = ProductArchetype.HOME_LIFESTYLE
    _write_research(tmp_path, source="llm", discount=20)
    brief = _brief(tmp_path, arch)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    assert "20%" in script.beats[-1].spoken_text
    assert "199.000đ" in script.beats[-1].spoken_text

    _write_research(tmp_path, source="heuristic_fallback", discount=20)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    assert "20%" not in script.beats[-1].spoken_text


def _concept(winner: str) -> dict:
    def angle(aid, hook):
        return {
            "angle_id": aid,
            "hook_strategy": {"spoken_hook": hook, "on_screen_text": f"CAP {aid}", "visual_hook": f"vis {aid}"},
        }

    return {
        "concept_options": [angle("angle_a", "Hook A"), angle("angle_b", "Hook B"), angle("angle_c", "Hook C")],
        "winning_concept": {"selected_angle_id": winner},
    }


def test_winning_angle_is_looked_up_by_id_with_fallback(tmp_path: Path):
    arch = ProductArchetype.GENERAL_COMMERCIAL
    brief = _brief(tmp_path, arch)
    (tmp_path / "creative_concept.json").write_text(json.dumps(_concept("angle_c")), encoding="utf-8")
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    assert script.beats[0].spoken_text == "Hook C"
    assert script.beats[0].on_screen_text == "CAP angle_c"

    (tmp_path / "creative_concept.json").write_text(json.dumps(_concept("missing_id")), encoding="utf-8")
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    assert script.beats[0].spoken_text == "Hook A"


VIETNAMESE_CHARS = re.compile(r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.I)


@pytest.mark.parametrize("arch", list(ProductArchetype))
def test_templates_emit_english_cue_direction_and_transitions(tmp_path: Path, arch):
    brief = _brief(tmp_path, arch)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    raw_tokens = [c.value for c in CameraChoreography if "_" in c.value] + [l.value for l in LightingContract]
    for beat in script.beats:
        assert beat.visual_cue_en, beat.scene_id
        # the product name is a proper noun and may legitimately stay Vietnamese
        assert not VIETNAMESE_CHARS.search(beat.visual_cue_en.replace(brief.product_name, "")), beat.visual_cue_en
        assert "[KOL" not in beat.visual_cue_en  # persona tag is injected by the prompt builder
        for tok in raw_tokens:
            assert tok not in beat.visual_cue_en and tok not in beat.visual_cue
    transitions = [b.transition for b in script.beats]
    assert transitions[0] is None
    assert script.beats[-1].transition["type"] == "fade"
    assert 0 < script.beats[-1].transition["duration"] <= 0.5
    assert all(t["type"] == "cut" for t in transitions[1:-1])
    assert all(t["type"] in SUPPORTED_TRANSITIONS for t in transitions[1:])

    # persists through script.json
    loaded = ScriptArtifact.model_validate(json.loads((tmp_path / "script.json").read_text(encoding="utf-8")))
    assert loaded.beats[-1].transition == script.beats[-1].transition
    assert loaded.beats[0].visual_cue_en == script.beats[0].visual_cue_en


def test_script_beat_direction_fields_validate_and_roundtrip():
    beat = ScriptBeat(
        scene_id="s1",
        beat_type="hook",
        spoken_text="Chào",
        on_screen_text="HI",
        visual_cue="cue",
        estimated_duration=3.0,
        shot_scale="close_up",
        lens="85mm_portrait",
        angle="low_angle_15deg",
        transition={"type": "dissolve", "duration": 0.3},
    )
    assert beat.shot_scale == ShotScale.CU and beat.lens == CameraLens.LENS_85MM and beat.angle == CameraAngle.LOW_ANGLE
    again = ScriptBeat.model_validate(json.loads(json.dumps(beat.model_dump(), default=str)))
    assert again.transition == {"type": "dissolve", "duration": 0.3}
    assert ScriptBeat(**{**beat.model_dump(), "transition": None}).transition is None
    with pytest.raises(ValueError):
        ScriptBeat(**{**beat.model_dump(), "transition": {"type": "spin_cycle", "duration": 0.3}})
    with pytest.raises(ValueError):
        ScriptBeat(**{**beat.model_dump(), "transition": {"type": "fade", "duration": 9}})


def test_dynamic_prompt_builder_emits_no_raw_enum_values():
    for role_name in ("PRESENTER", "MODEL", "PRODUCT_ONLY"):
        from pipeline.archetypes import CharacterRole

        prompt = DynamicPromptBuilder.build_subject_and_action_prompt(
            character_role=CharacterRole[role_name],
            archetype=ProductArchetype.TECH_GADGETS,
            product_name="Aurora",
            scene_action="demo",
            lighting=LightingContract.STUDIO_3POINT,
            camera=CameraChoreography.ZOOM_IN,
        )
        assert "zoom_in" not in prompt and "studio_3point" not in prompt


def _first_beats(tmp_path: Path, arch: ProductArchetype, **overrides):
    brief = _brief(tmp_path, arch)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    for k, v in overrides.items():
        setattr(script.beats[1], k, v)
    return script


def test_storyboard_prompts_use_english_visual_cue(tmp_path: Path):
    script = _first_beats(tmp_path, ProductArchetype.BEAUTY_SKINCARE)
    plan = generate_scene_plan(script=script, output_dir=tmp_path)
    for beat, shot in zip(script.beats, plan.shots):
        assert beat.visual_cue_en in shot.prompt_6part or beat.visual_cue_en[:40] in shot.prompt_6part
        assert beat.visual_cue not in shot.prompt_6part
        assert shot.transition == beat.transition


def test_storyboard_falls_back_to_vietnamese_cue_without_english(tmp_path: Path):
    script = _first_beats(tmp_path, ProductArchetype.BEAUTY_SKINCARE)
    script.beats[2].visual_cue_en = None
    plan = generate_scene_plan(script=script, output_dir=tmp_path)
    assert script.beats[2].visual_cue in plan.shots[2].prompt_6part


def test_script_direction_beats_planned_framing_and_overrides_beat_script(tmp_path: Path):
    script = _first_beats(
        tmp_path,
        ProductArchetype.TECH_GADGETS,
        shot_scale=ShotScale.ELS,
        lens=CameraLens.LENS_24MM,
        angle=CameraAngle.TOP_DOWN,
    )
    plan = generate_scene_plan(script=script, output_dir=tmp_path)
    shot = plan.shots[1]
    assert "extreme wide" in shot.prompt_6part and "24mm" in shot.prompt_6part and "top-down" in shot.prompt_6part
    assert shot.angle == CameraAngle.TOP_DOWN.value

    plan = generate_scene_plan(
        script=script, output_dir=tmp_path, shot_overrides={"shot_02": {"shot_scale": "close_up", "lens": "85mm_portrait"}}
    )
    assert "85mm" in plan.shots[1].prompt_6part and "extreme wide" not in plan.shots[1].prompt_6part


def test_persona_parameter_drives_prompts(tmp_path: Path):
    script = _first_beats(tmp_path, ProductArchetype.FASHION_APPAREL)
    default_plan = generate_scene_plan(script=script, output_dir=tmp_path)
    assert any(s.character_tag == "[KOL_MAIN]" for s in default_plan.shots)

    plan = generate_scene_plan(script=script, output_dir=tmp_path, persona="model_fashion")
    tagged = [s for s in plan.shots if s.character_tag]
    assert tagged and all(s.character_tag == "[MODEL_LD]" for s in tagged)
    assert all("Linh Dan" in s.prompt_6part for s in plan.shots if s.character_tag)
    assert all("Mai Ly" not in s.prompt_6part for s in plan.shots)


def test_character_path_drives_persona_in_dynamic_path(tmp_path: Path):
    char_dir = tmp_path / "chars" / "kol_custom"
    char_dir.mkdir(parents=True)
    (char_dir / "character.json").write_text(
        json.dumps({"name": "Bao Tram", "character_tag": "[KOL_BT]", "face_prompt": "Vietnamese woman with a long wavy hairstyle"}),
        encoding="utf-8",
    )
    script = _first_beats(tmp_path, ProductArchetype.TECH_GADGETS)
    plan = generate_scene_plan(script=script, output_dir=tmp_path, character_path=char_dir / "character.json")
    tagged = [s for s in plan.shots if s.character_tag]
    assert tagged and all(s.character_tag == "[KOL_BT]" for s in tagged)
    assert all("long wavy hairstyle" in s.identity_lock_directive for s in tagged)


def test_persona_drives_legacy_mug_storyboard(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path)
    plan = generate_scene_plan(script=script, output_dir=tmp_path, persona="kol_main")
    assert all(s.character_tag == "[KOL_MAIN]" for s in plan.shots)
    assert all("[KOL_MAIN]" in s.prompt_6part for s in plan.shots)
    assert max(s.estimated_duration for s in plan.shots) <= MAX_BEAT_SECONDS


def test_humanizer_is_idempotent_and_leaves_hyphenated_words_alone():
    from pipeline.cinematography import compact_video_prompt, humanize_directive_tokens

    once = humanize_directive_tokens("Camera movement: orbit and zoom_in, tilt-up, pedestal-up")
    assert humanize_directive_tokens(once) == once
    assert "tilt-up" in once and "pedestal-up" in once
    assert "smooth slow orbit around the subject" in once and "zoom_in" not in once
    prompt = compact_video_prompt("Camera movement: smooth slow orbit around the subject.")
    assert prompt.count("orbit") == 1
