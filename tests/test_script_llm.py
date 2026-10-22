"""Stage 2 LLM-drafted scripts: acceptance, no-fabrication rejection, repair retry, offline/template fallback."""

import copy
import json
from pathlib import Path

import pytest

from pipeline import llm
from pipeline.archetypes import ProductArchetype, get_archetype_config
from pipeline.briefing import create_product_brief
from pipeline.offline import offline_mode
from pipeline.schemas import ScriptArtifact
from pipeline.scriptwriter import (
    derive_display_name,
    estimate_speech_seconds,
    find_unsupported_claims,
    generate_commercial_script,
    validate_script,
)

ARCH = ProductArchetype.TECH_GADGETS
NAME = "Tai nghe chống ồn Sonic Air Pro"
USPS = ["Chống ồn chủ động ANC", "Pin 30 giờ", "Sạc nhanh USB-C"]


def _beat(beat_type, spoken, caption, cue_en, duration=3.5, transition=None, **extra):
    return {
        "beat_type": beat_type,
        "duration_seconds": duration,
        "spoken_text": spoken,
        "on_screen_text": caption,
        "visual_cue": "Cận cảnh " + beat_type,
        "visual_cue_en": cue_en,
        "motion_cue_en": "she lifts the earbuds slowly toward the lens, ending with them held still at chest height",
        "character_role": "presenter",
        "audio_strategy": "on_camera_speech",
        "camera_choreography": "zoom_in",
        "lighting_contract": "studio_3point",
        "shot_scale": "close_up",
        "lens": "85mm_portrait",
        "angle": "eye_level",
        "transition": transition or {"type": "cut", "duration": 0.0},
        "narrative_purpose": "test beat",
        **extra,
    }


GOOD = {
    "beats": [
        _beat("hook", "Ồn quá không làm việc nổi? Thử Sonic Air Pro đi!", "HẾT ỒN ÀO CHƯA?",
              "Close-up of a tired presenter pulling noisy office chatter away by putting on sleek over-ear headphones, soft studio key light",
              duration=3.5, transition={"type": "cut", "duration": 0.0}),
        _beat("demo", "Bật chống ồn chủ động là mọi tiếng ồn xung quanh dịu hẳn.", "CHỐNG ỒN CHỦ ĐỘNG",
              "Medium shot of the presenter tapping the ANC button on her earcup, slow push-in, clean studio lighting", duration=4.5),
        _beat("proof", "Pin 30 giờ, dùng cả tuần không lo hết pin.", "PIN 30 GIỜ",
              "Medium close-up of the presenter clicking a USB-C cable into the earcup and smiling to camera, cool white light", duration=4.0),
        _beat("cta", "Xem chi tiết Sonic Air Pro ở link bên dưới nhé!", "XEM CHI TIẾT • LINK BIO",
              "Presenter smiles and holds up the headphones toward the camera, bright studio light", duration=4.0,
              transition={"type": "fade", "duration": 0.4}),
    ]
}


@pytest.fixture
def brief(tmp_path: Path):
    return create_product_brief(
        campaign_id="c_sonic", product_name=NAME, archetype=ARCH, usps=USPS,
        pain_points=["Văn phòng ồn ào khó tập trung"], output_dir=tmp_path,
    )


class FakeLLM:
    """Replaces llm.chat; returns queued payloads (dict -> JSON, str -> raw) and records every call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, system, user, model=None, timeout=90, temperature=None, max_tokens=None):
        self.calls.append({"system": system, "user": user, "model": model})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return {"content": content, "model": "mock/minimax", "usage": {"total_tokens": 1}}


def _run(tmp_path, brief, monkeypatch, *replies, **kwargs):
    fake = FakeLLM(*replies)
    monkeypatch.setattr(llm, "chat", fake)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=ARCH, **kwargs)
    return script, fake


def test_good_llm_draft_is_used(tmp_path, brief, monkeypatch):
    script, fake = _run(tmp_path, brief, monkeypatch, GOOD)
    assert len(fake.calls) == 1
    assert [b.beat_type for b in script.beats] == ["hook", "demo", "proof", "cta"]
    assert script.beats[0].spoken_text.startswith("Ồn quá")
    assert script.beats[0].transition is None and script.beats[-1].transition["type"] == "fade"
    assert script.beats[0].shot_scale.value == "close_up" and script.beats[0].lens.value == "85mm_portrait"
    assert script.beats[0].scene_id == "shot_01_hook" and script.beats[0].archetype == ARCH
    assert validate_script(script.beats) == []
    for beat in script.beats:
        assert beat.estimated_duration >= estimate_speech_seconds(beat.spoken_text)
    # "30" comes from the brief's own USP, so the grounding lint accepts it
    assert find_unsupported_claims(script, brief) == []
    saved = ScriptArtifact.model_validate_json((tmp_path / "script.json").read_text(encoding="utf-8"))
    assert saved.beats[2].spoken_text == script.beats[2].spoken_text
    # the prompt carries the brief facts and hard constraints, and never a credential
    assert "Pin 30 giờ" in fake.calls[0]["user"] and "short_display_name_for_speech" in fake.calls[0]["user"]
    assert "Tai nghe Sonic Air Pro" in fake.calls[0]["user"]
    assert "NO FABRICATION" in fake.calls[0]["system"] and "api" not in fake.calls[0]["user"].lower().replace("capi", "")


def test_durations_are_stretched_to_fit_speech(tmp_path, brief, monkeypatch):
    draft = copy.deepcopy(GOOD)
    draft["beats"][1]["duration_seconds"] = 2.0  # line needs more than 2s
    script, fake = _run(tmp_path, brief, monkeypatch, draft)
    assert len(fake.calls) == 1
    assert script.beats[1].estimated_duration >= estimate_speech_seconds(script.beats[1].spoken_text)


def test_fabricated_discount_is_rejected_then_templates_used(tmp_path, brief, monkeypatch):
    bad = copy.deepcopy(GOOD)
    bad["beats"][3]["spoken_text"] = "Giảm 50% hôm nay, bấm link bên dưới!"
    bad["beats"][3]["on_screen_text"] = "GIẢM 50% • LINK BIO"
    script, fake = _run(tmp_path, brief, monkeypatch, bad, bad)
    assert len(fake.calls) == 2  # first attempt + one repair retry, both fabricated
    assert "50" in fake.calls[1]["user"] and "REJECTED" in fake.calls[1]["user"]
    assert all("50%" not in b.spoken_text for b in script.beats)
    assert script.beats[0].spoken_text != GOOD["beats"][0]["spoken_text"]  # template copy
    assert [b.beat_type for b in script.beats] == [t.beat_type for t in get_archetype_config(ARCH).beat_templates]


def test_fabricated_claim_repaired_on_retry(tmp_path, brief, monkeypatch):
    bad = copy.deepcopy(GOOD)
    bad["beats"][2]["spoken_text"] = "Hơn 10.000 người đã tin dùng, bảo hành 24 tháng."
    script, fake = _run(tmp_path, brief, monkeypatch, bad, GOOD)
    assert len(fake.calls) == 2
    assert "unsupported claim" in fake.calls[1]["user"] or "not found in brief" in fake.calls[1]["user"]
    assert script.beats[2].spoken_text == GOOD["beats"][2]["spoken_text"]


def test_offer_supplied_by_brief_is_allowed(tmp_path, brief, monkeypatch):
    brief.offers = ["Giảm 15% đến hết tuần này"]
    draft = copy.deepcopy(GOOD)
    draft["beats"][3]["spoken_text"] = "Giảm 15% đến hết tuần này, xem link bên dưới!"
    script, fake = _run(tmp_path, brief, monkeypatch, draft)
    assert len(fake.calls) == 1 and "15%" in script.beats[-1].spoken_text


def test_invalid_structure_triggers_repair_retry(tmp_path, brief, monkeypatch):
    broken = copy.deepcopy(GOOD)
    broken["beats"][0]["beat_type"] = "intro"  # first beat must be a hook
    broken["beats"][1]["transition"] = {"type": "spin_cycle", "duration": 0.3}
    broken["beats"][2]["lens"] = "999mm_telescope"
    script, fake = _run(tmp_path, brief, monkeypatch, broken, GOOD)
    assert len(fake.calls) == 2
    repair_prompt = fake.calls[1]["user"]
    assert "spin_cycle" in repair_prompt or "transition" in repair_prompt
    assert "999mm_telescope" in repair_prompt and "Errors to fix" in repair_prompt
    assert script.beats[0].beat_type == "hook" and len(script.beats) == 4


def test_non_json_then_json_is_repaired(tmp_path, brief, monkeypatch):
    script, fake = _run(tmp_path, brief, monkeypatch, "Xin lỗi, tôi không thể.", GOOD)
    assert len(fake.calls) == 2 and "not valid JSON" in fake.calls[1]["user"]
    assert script.beats[0].beat_type == "hook"


def test_vietnamese_visual_cue_en_and_long_caption_are_rejected(tmp_path, brief, monkeypatch):
    bad = copy.deepcopy(GOOD)
    bad["beats"][1]["visual_cue_en"] = "Cận cảnh ngón tay bấm nút"
    bad["beats"][2]["on_screen_text"] = "MỘT DÒNG CHỮ TRÊN MÀN HÌNH QUÁ DÀI KHÔNG THỂ ĐỌC KỊP"
    script, fake = _run(tmp_path, brief, monkeypatch, bad, GOOD)
    assert len(fake.calls) == 2
    assert "must be English" in fake.calls[1]["user"] and "max 38" in fake.calls[1]["user"]


def test_missing_motion_cue_is_rejected_and_repaired(tmp_path, brief, monkeypatch):
    # Without a motion cue Stage 5 would send the whole still-frame description as the I2V prompt.
    bad = copy.deepcopy(GOOD)
    del bad["beats"][1]["motion_cue_en"]
    script, fake = _run(tmp_path, brief, monkeypatch, bad, GOOD)
    assert len(fake.calls) == 2 and "motion_cue_en is required" in fake.calls[1]["user"]
    assert all(b.motion_cue_en for b in script.beats)


def test_provider_error_falls_back_to_templates_without_retry(tmp_path, brief, monkeypatch):
    script, fake = _run(tmp_path, brief, monkeypatch, llm.LLMError("boom"))
    assert len(fake.calls) == 1
    assert len(script.beats) >= 4 and script.beats[0].beat_type == "hook"


def test_offline_uses_templates_without_calling_llm(tmp_path, brief, monkeypatch):
    fake = FakeLLM(GOOD)
    monkeypatch.setattr(llm, "chat", fake)
    with offline_mode(True):
        script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=ARCH)
    assert fake.calls == []
    assert script.beats[0].spoken_text != GOOD["beats"][0]["spoken_text"]


def test_use_llm_false_and_explicit_beats_skip_the_llm(tmp_path, brief, monkeypatch):
    fake = FakeLLM(GOOD)
    monkeypatch.setattr(llm, "chat", fake)
    generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=ARCH, use_llm=False)
    generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=ARCH, beats=[
        {"scene_id": "s1", "beat_type": "hook", "spoken_text": "Chào", "on_screen_text": "HI", "visual_cue": "cue",
         "estimated_duration": 3.0},
        {"scene_id": "s2", "beat_type": "cta", "spoken_text": "Xem ngay", "on_screen_text": "LINK", "visual_cue": "cue",
         "estimated_duration": 3.0},
    ])
    assert fake.calls == []


def test_non_presenter_on_camera_speech_becomes_voiceover(tmp_path, brief, monkeypatch):
    draft = copy.deepcopy(GOOD)
    draft["beats"][1]["character_role"] = "product_only"  # still says on_camera_speech
    script, _ = _run(tmp_path, brief, monkeypatch, draft)
    assert script.beats[1].audio_strategy.value == "off_camera_vo"


def test_research_numbers_are_valid_grounding(tmp_path, brief, monkeypatch):
    (tmp_path / "competitor_research.json").write_text(json.dumps({
        "product_intel": {"title": NAME, "source": "llm", "features": ["Driver 40mm"]}}), encoding="utf-8")
    draft = copy.deepcopy(GOOD)
    draft["beats"][2]["spoken_text"] = "Driver 40mm cho âm bass đầy đặn."
    script, fake = _run(tmp_path, brief, monkeypatch, draft)
    assert len(fake.calls) == 1 and "40mm" in script.beats[2].spoken_text


def test_untrusted_research_pricing_does_not_ground_numbers(tmp_path, brief, monkeypatch):
    (tmp_path / "competitor_research.json").write_text(json.dumps({
        "product_intel": {"title": NAME, "source": "heuristic_fallback",
                          "pricing": {"current_price": 199000, "discount_percent": 20, "currency": "VND"}}}),
        encoding="utf-8")
    draft = copy.deepcopy(GOOD)
    draft["beats"][3]["spoken_text"] = "Giảm 20% còn 199.000đ, xem link bên dưới!"
    _, fake = _run(tmp_path, brief, monkeypatch, draft, draft)
    assert len(fake.calls) == 2


def test_telemetry_records_prompt_and_model_but_no_key(tmp_path, brief, monkeypatch):
    from pipeline.telemetry import RunTelemetry
    from pipeline import telemetry

    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret-key")
    rec = RunTelemetry("p1", telemetry_dir=tmp_path / "run")
    with telemetry.use_recorder(rec):
        _run(tmp_path, brief, monkeypatch, GOOD)
    prompts = rec.state["prompts"]
    record = prompts["script_draft_attempt_1"]
    assert record["model"] == "mock/minimax" and "Pin 30 giờ" in record["prompt"]
    assert "sk-super-secret-key" not in json.dumps(rec.state, default=str)


def test_display_name_never_pastes_the_description():
    assert derive_display_name(NAME) == "Tai nghe Sonic Air Pro"
    long_desc = "Tai nghe bluetooth chống ồn chủ động ANC, pin 30 giờ, sạc nhanh USB-C"
    short = derive_display_name(long_desc)
    assert len(short.split()) <= 5 and "pin" not in short and "30" not in short
    assert derive_display_name("Bàn Phím Cơ Không Dây CyberKey RGB Bluetooth") == "Bàn Phím Cơ CyberKey"
    assert derive_display_name("Ly Giữ Nhiệt") == "Ly Giữ Nhiệt"


def test_template_copy_uses_display_name_not_description(tmp_path):
    desc = "Tai nghe bluetooth chống ồn chủ động ANC, pin 30 giờ, sạc nhanh USB-C"
    brief = create_product_brief(campaign_id="c_desc", product_name=desc, archetype=ARCH, output_dir=tmp_path)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path, archetype=ARCH, use_llm=False)
    spoken = " ".join(b.spoken_text + " " + b.on_screen_text for b in script.beats)
    assert "pin 30 giờ" not in spoken.lower() and "usb-c" not in spoken.lower()
