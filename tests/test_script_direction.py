"""Stage 2: agent-directable scripts, speech-fit durations and clean visual cues."""

from pathlib import Path

import pytest

from pipeline.archetypes import AudioStrategy, CameraChoreography, CharacterRole, ProductArchetype
from pipeline.briefing import create_product_brief
from pipeline.schemas import ScriptBeat
from pipeline.scriptwriter import (
    MAX_BEAT_SECONDS,
    estimate_speech_seconds,
    fit_beat_durations_to_speech,
    generate_commercial_script,
    validate_script,
)

RAW_ENUM_TOKENS = [c.value for c in CameraChoreography if "_" in c.value]


def _beat(beat_type="hook", spoken="Xin chào các bạn", duration=3.0, **kw) -> ScriptBeat:
    return ScriptBeat(
        scene_id=kw.pop("scene_id", f"shot_01_{beat_type}"),
        beat_type=beat_type,
        spoken_text=spoken,
        on_screen_text=kw.pop("on_screen_text", "HOOK"),
        visual_cue=kw.pop("visual_cue", "KOL giơ cao sản phẩm"),
        estimated_duration=duration,
        **kw,
    )


def test_estimate_speech_seconds_scales_with_syllables():
    assert estimate_speech_seconds("") == 0.0
    short = estimate_speech_seconds("Xin chào")
    long = estimate_speech_seconds("Xin chào các bạn, hôm nay mình giới thiệu một sản phẩm tuyệt vời")
    assert 0 < short < long


@pytest.mark.parametrize("arch", [a for a in ProductArchetype])
def test_template_beats_fit_their_speech(tmp_path: Path, arch):
    brief = create_product_brief(output_dir=tmp_path, archetype=arch, campaign_id=f"c_{arch.value}")
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    for beat in script.beats:
        need = estimate_speech_seconds(beat.spoken_text)
        if beat.audio_strategy != AudioStrategy.MUSIC_AND_SFX_ONLY:
            assert beat.estimated_duration >= need - 1e-6, (beat.scene_id, beat.estimated_duration, need)
        assert beat.estimated_duration <= MAX_BEAT_SECONDS
    assert script.target_duration == pytest.approx(sum(b.estimated_duration for b in script.beats))


@pytest.mark.parametrize("arch", [a for a in ProductArchetype])
def test_visual_cues_do_not_leak_raw_enum_values(tmp_path: Path, arch):
    brief = create_product_brief(output_dir=tmp_path, archetype=arch, campaign_id=f"c_{arch.value}")
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=arch)
    for beat in script.beats:
        for token in RAW_ENUM_TOKENS:
            assert token not in beat.visual_cue, (beat.scene_id, token)


def test_fit_durations_extends_but_never_shrinks_and_reports_overflow():
    short_text = _beat(spoken="Chào", duration=5.0)
    overflowing = _beat(
        beat_type="feature",
        spoken=" ".join(["từ"] * 80),
        duration=3.0,
        scene_id="shot_02_feature",
    )
    warnings = fit_beat_durations_to_speech([short_text, overflowing])
    assert short_text.estimated_duration == 5.0
    assert overflowing.estimated_duration == MAX_BEAT_SECONDS
    assert any("shot_02_feature" in w for w in warnings)


def test_music_only_beats_are_not_stretched_for_speech():
    beat = _beat(spoken="x " * 30, duration=3.0, audio_strategy=AudioStrategy.MUSIC_AND_SFX_ONLY)
    fit_beat_durations_to_speech([beat])
    assert beat.estimated_duration == 3.0


def test_validate_script_accepts_well_formed_script():
    beats = [
        _beat("hook", "Bạn mệt vì cà phê nguội?", 3.0, scene_id="shot_01_hook"),
        _beat("demo", "Chạm nhẹ là biết nhiệt độ.", 4.0, scene_id="shot_02_demo"),
        _beat("cta", "Nhấp link bên dưới nhé!", 3.0, scene_id="shot_03_cta"),
    ]
    assert validate_script(beats) == []


def test_validate_script_flags_structure_and_limits():
    beats = [
        _beat("pain", "Chào", 12.0, scene_id="shot_01_pain", visual_cue=""),
        _beat("demo", "Chào", 3.0, scene_id="shot_01_pain"),
    ]
    issues = " | ".join(validate_script(beats))
    assert "first beat" in issues.lower()  # must open with a hook
    assert "last beat" in issues.lower()  # must close with a CTA
    assert "duplicate scene_id" in issues.lower()
    assert "visual_cue" in issues
    assert "exceeds" in issues.lower()  # 12s > model clip limit


def test_validate_script_flags_slow_hook_and_overlong_total():
    beats = [_beat("hook", "Chào", 6.0, scene_id="s1")]
    beats += [_beat("demo", "Chào", 6.0, scene_id=f"s{i}") for i in range(2, 8)]
    beats += [_beat("cta", "Chào", 6.0, scene_id="s9")]
    issues = " | ".join(validate_script(beats))
    assert "hook" in issues.lower() and "seconds" in issues.lower()
    assert "total" in issues.lower()


def test_agent_can_inject_its_own_beats(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path)
    custom = [
        _beat("hook", "Cà phê nguội rồi à?", 3.0, scene_id="shot_01_hook", character_role=CharacterRole.PRESENTER),
        {
            "scene_id": "shot_02_cta",
            "beat_type": "cta",
            "spoken_text": "Mua ngay nhé!",
            "on_screen_text": "MUA NGAY",
            "visual_cue": "KOL giơ cao ly",
            "estimated_duration": 3.0,
        },
    ]
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, beats=custom)
    assert [b.beat_type for b in script.beats] == ["hook", "cta"]
    assert script.beats[0].spoken_text == "Cà phê nguội rồi à?"
    assert (tmp_path / "script.json").exists()
    assert script.target_duration == pytest.approx(sum(b.estimated_duration for b in script.beats))


def test_agent_beats_with_blocking_errors_are_rejected(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path)
    bad = [_beat("demo", "Chào", 3.0, scene_id="shot_01_demo")]
    with pytest.raises(ValueError, match="first beat"):
        generate_commercial_script(brief=brief, output_dir=tmp_path, beats=bad)
    # strict=False downgrades to warnings so an agent can deliberately break the rules
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, beats=bad, strict=False)
    assert len(script.beats) == 1


def test_long_product_names_keep_their_brand():
    from pipeline.scriptwriter import _clean_spoken_product_name

    spoken = _clean_spoken_product_name("Ly Giữ Nhiệt Thông Minh Lumina Pro")
    assert spoken.endswith("Lumina Pro")
    assert len(spoken.split()) <= 5
    assert _clean_spoken_product_name("Ly Giữ Nhiệt") == "Ly Giữ Nhiệt"
