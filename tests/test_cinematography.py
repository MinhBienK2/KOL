from pathlib import Path
import pytest
from pipeline.archetypes import ProductArchetype
from pipeline.cinematography import (
    CameraAngle,
    CameraLens,
    FramingDirective,
    ShotScale,
    build_framing_directive,
    generate_storyboard_contact_sheet,
)
from pipeline.wardrobe import (
    CostumeStyle,
    EnvironmentSetting,
    WardrobeItem,
    resolve_wardrobe_and_environment,
)
from pipeline.lip_sync_engine import (
    AudioStrategy,
    CharacterRole,
    analyze_speech_energy,
    determine_lip_sync_strategy,
)


def test_resolve_wardrobe_and_environment_all_archetypes():
    for arch in ProductArchetype:
        wardrobe, env = resolve_wardrobe_and_environment(arch)
        assert isinstance(wardrobe, WardrobeItem)
        assert isinstance(env, EnvironmentSetting)
        assert wardrobe.prompt_wear_directive.startswith("WEAR:")
        assert env.prompt_set_directive.startswith("SET:")
        assert env.nominal_color_temp_kelvin in (3200, 5000, 5500, 5600)


def test_build_framing_directive():
    f_ws = build_framing_directive(ShotScale.WS)
    assert f_ws.shot_scale == ShotScale.WS
    assert f_ws.lens == CameraLens.LENS_24MM
    assert "WIDE_SHOT" in f_ws.prompt_optics_directive

    f_ecu = build_framing_directive(ShotScale.ECU)
    assert f_ecu.shot_scale == ShotScale.ECU
    assert f_ecu.lens == CameraLens.LENS_100MM
    assert "EXTREME_MACRO" in f_ecu.prompt_optics_directive


def test_storyboard_contact_sheet_generation(tmp_path: Path):
    shots = [
        {
            "shot_id": "shot_01",
            "shot_scale": "WS",
            "estimated_duration": 3.0,
            "camera_motion": "pedestal",
            "character_role": "model",
            "lighting": "editorial_fashion",
            "color_temp_kelvin": 5000,
            "shot_intent": "Pattern Interrupt",
            "scene_description": "Model steps forward on gala runway in evening dress",
            "spoken_text": "Check out the new Grace Noir dress",
            "on_screen_text": "GRACE NOIR • FRENCH SATIN",
        },
        {
            "shot_id": "shot_02",
            "shot_scale": "ECU",
            "estimated_duration": 4.0,
            "camera_motion": "macro_push_in",
            "character_role": "product_only",
            "lighting": "editorial_fashion",
            "color_temp_kelvin": 5000,
            "shot_intent": "Material Texture Proof",
            "scene_description": "Macro 100mm lens tracks along fluid mulberry silk fibers",
            "spoken_text": "",
            "on_screen_text": "100% FRENCH MULBERRY SILK",
        },
    ]
    out_sheet = tmp_path / "contact_sheet.jpg"
    res = generate_storyboard_contact_sheet(shots, out_sheet, campaign_title="Test Storyboard")
    assert out_sheet.exists()
    assert out_sheet.stat().st_size > 1000
    assert res == str(out_sheet)


def test_lip_sync_decisions():
    # Music only -> pure BGM, no mouth articulation
    dec_music = determine_lip_sync_strategy(
        shot_id="shot_01",
        character_role=CharacterRole.MODEL,
        audio_strategy=AudioStrategy.MUSIC_AND_SFX_ONLY,
        spoken_text="",
    )
    assert not dec_music.needs_mouth_articulation
    assert dec_music.voiceover_mix_mode == "pure_bgm"

    # Off-camera VO -> no mouth articulation
    dec_vo = determine_lip_sync_strategy(
        shot_id="shot_02",
        character_role=CharacterRole.MODEL,
        audio_strategy=AudioStrategy.OFF_CAMERA_VO,
        spoken_text="Smooth fabric flows with every step",
    )
    assert not dec_vo.needs_mouth_articulation
    assert dec_vo.voiceover_mix_mode == "off_camera_narration"

    # Presenter speech -> needs mouth articulation
    dec_pres = determine_lip_sync_strategy(
        shot_id="shot_03",
        character_role=CharacterRole.PRESENTER,
        audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
        spoken_text="Don't miss out on this 40% limited drop!",
    )
    assert dec_pres.needs_mouth_articulation
    assert dec_pres.voiceover_mix_mode == "sync_mouth"
    assert "articulation" in dec_pres.prompt_articulation_directive.lower()
