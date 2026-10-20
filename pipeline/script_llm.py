"""LLM-drafted commercial scripts (Stage 2).

``draft_script_with_llm`` asks the configured LLM (MiniMax via :mod:`pipeline.llm`) for the whole beat
list as strict JSON, then runs it through the same gates an agent-authored script gets: ScriptBeat
parsing, speech-fitted durations, ``validate_script`` and the no-fabrication lint. One repair retry
feeds the concrete errors back; if that still fails (or the provider is unreachable) the function
returns ``None`` and the caller falls back to the deterministic archetype templates.

The prompt is recorded in telemetry (model and prompt text, never any credential).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pipeline import llm, telemetry
from pipeline.archetypes import (
    AudioStrategy,
    CameraChoreography,
    CharacterRole,
    LightingContract,
    ProductArchetype,
    get_archetype_config,
)
from pipeline.cinematography import CameraAngle, CameraLens, ShotScale
from pipeline.composer import SUPPORTED_TRANSITIONS
from pipeline.offline import OfflineNetworkError, is_offline
from pipeline.schemas import BriefArtifact, ScriptBeat
from pipeline import scriptwriter as sw

STAGE_SCRIPTWRITING = telemetry.stage_number("scriptwriting")

MIN_BEATS = 4
MAX_BEATS = 8
MAX_CAPTION_CHARS = 38
SCRIPT_LLM_TIMEOUT = 150
_VIETNAMESE_CHARS = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.IGNORECASE
)
_ENUM_FIELDS: Dict[str, Any] = {
    "character_role": CharacterRole,
    "audio_strategy": AudioStrategy,
    "camera_choreography": CameraChoreography,
    "lighting_contract": LightingContract,
    "shot_scale": ShotScale,
    "lens": CameraLens,
    "angle": CameraAngle,
}


def _values(enum_cls: Any) -> str:
    return ", ".join(m.value for m in enum_cls)


SYSTEM_PROMPT = f"""You are a senior Vietnamese short-form video ad scriptwriter (TikTok / Reels / Shorts) and
a cinematographer who writes shot descriptions for AI video models. You write the complete beat-by-beat script
for ONE commercial and answer with STRICT JSON only (no markdown, no commentary).

HARD CONSTRAINTS
- First beat is the hook (beat_type "hook", duration <= {sw.MAX_HOOK_SECONDS:g}s). Last beat is the call to action (beat_type "cta").
- {MIN_BEATS}-{MAX_BEATS} beats; every beat lasts {sw.MIN_BEAT_SECONDS:g}-{sw.MAX_BEAT_SECONDS:g}s (one shot, one idea); total <= {sw.MAX_TOTAL_SECONDS:g}s.
- spoken_text: natural, conversational Vietnamese a real KOL would say. Short enough to be spoken inside the beat:
  about 4 words per second (e.g. 3s = at most ~10 words, 6s = ~22 words). Use the SHORT display name of the product,
  never a pasted description. No stiff marketing boilerplate.
  EVERY beat needs a non-empty spoken_text, including product-only/ASMR beats (there it is a soft off-camera voiceover
  line over the visuals). Only audio_strategy "music_and_sfx_only" may have an empty spoken_text.
- on_screen_text: Vietnamese caption, UPPERCASE, at most {MAX_CAPTION_CHARS} characters INCLUDING spaces (aim for 2-4 words), punchy.
- visual_cue_en: ENGLISH only, written for a video model: subject, ONE action, camera movement/framing, lighting, setting.
  One action per shot. No Vietnamese words, no character names or tags, no brand-name spelling tricks.
- visual_cue: the same shot described in Vietnamese (for the Vietnamese crew).
- NO FABRICATION: never invent prices, discounts, percentages, numbers, statistics, awards, certifications, warranties,
  ratings, "best seller" or expert/doctor endorsements. Use a number or offer ONLY if it appears in the brief or research
  facts you are given. Without a supplied offer the CTA is neutral ("xem chi tiết ở link bên dưới").
- Build on the winning concept: its angle, hook strategy, character role and audio strategy.

ENUMS (use these exact strings)
- character_role: {_values(CharacterRole)}
- audio_strategy: {_values(AudioStrategy)}
- camera_choreography: {_values(CameraChoreography)}
- lighting_contract: {_values(LightingContract)}
- shot_scale: {_values(ShotScale)}
- lens: {_values(CameraLens)}
- angle: {_values(CameraAngle)}
- transition.type: {", ".join(SUPPORTED_TRANSITIONS)} (hard "cut" between most beats; a short "fade" or similar into the CTA;
  transition.duration 0 for cut, otherwise 0.2-0.6)
- character_role "presenter" speaks to camera (on_camera_speech); "model" and "product_only" use off_camera_vo or
  music_and_sfx_only (nobody lip-syncs).

OUTPUT SCHEMA
{{"beats": [{{
  "beat_type": "hook|...|cta", "duration_seconds": 3.0,
  "spoken_text": "...", "on_screen_text": "...",
  "visual_cue": "...", "visual_cue_en": "...",
  "character_role": "...", "audio_strategy": "...", "camera_choreography": "...", "lighting_contract": "...",
  "shot_scale": "...", "lens": "...", "angle": "...",
  "transition": {{"type": "cut", "duration": 0.0}},
  "narrative_purpose": "one short English sentence"
}}]}}"""


# ------------------------------------------------------------------------------
# Prompt construction
# ------------------------------------------------------------------------------

def _winning_angle(concept: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return sw._select_winning_option(concept) if concept else None


def _research_facts(research: Dict[str, Any]) -> Dict[str, Any]:
    intel = (research.get("research") or {}).get("product_intel") or {}
    keep = ("title", "brand", "category", "features", "dramatic_benefits", "sensory_anchors", "pricing")
    facts = {k: intel[k] for k in keep if intel.get(k)}
    objections = [o.get("objection") for o in intel.get("objection_matrix") or [] if isinstance(o, dict)]
    if objections:
        facts["objections"] = objections[:4]
    return facts


def build_prompts(
    brief: BriefArtifact,
    archetype: ProductArchetype,
    research: Dict[str, Any],
    offer: Optional[str],
) -> Tuple[str, str]:
    """Return (system_prompt, user_prompt) for the script draft."""
    config = get_archetype_config(archetype)
    winning = _winning_angle(research.get("concept"))
    concept_block: Dict[str, Any] = {}
    if winning:
        concept_block = {
            k: winning.get(k)
            for k in (
                "title", "angle_archetype", "character_role", "audio_strategy", "hook_strategy", "narrative_arc",
                "conversion_thesis",
            )
            if winning.get(k)
        }
        directives = ((research.get("concept") or {}).get("winning_concept") or {}).get("directorial_directives")
        if directives:
            concept_block["directorial_directives"] = directives
    template_flow = [
        f"{t.beat_type} ({t.target_duration:g}s, {t.recommended_role.value}): {t.narrative_purpose}"
        for t in config.beat_templates
    ]
    display = sw.derive_display_name(brief.product_name)
    user = {
        "product": {
            "full_name": brief.product_name,
            "short_display_name_for_speech": display,
            "category": brief.category,
            "usps": brief.usps,
            "pain_points": brief.pain_points,
            "target_persona": brief.target_persona,
            "visual_tone": brief.visual_tone,
            "supplied_offers": [offer] if offer else [],
        },
        "presenter": {"name": brief.presenter.name, "role": brief.presenter.role},
        "brief_defaults": {
            "character_role": brief.character_role.value,
            "audio_strategy": brief.target_audio_strategy.value,
        },
        "research_facts": _research_facts(research),
        "winning_concept": concept_block,
        "archetype_rules": {
            "archetype": archetype.value,
            "style": config.display_name,
            "description": config.description,
            "character_guidance": config.character_guidance,
            "audio_guidance": config.audio_foley_guidance,
            "default_lighting": config.default_lighting.value,
            "allowed_character_roles": [r.value for r in config.allowed_character_roles],
            "allowed_audio_strategies": [a.value for a in config.allowed_audio_strategies],
            "primary_camera_motions": [m.value for m in config.primary_camera_motions],
            "suggested_beat_flow": template_flow,
        },
    }
    text = (
        "Write the commercial script for this product. The only facts, numbers and offers you may state are in the "
        "JSON below.\n\n" + json.dumps(user, ensure_ascii=False, indent=2)
    )
    return SYSTEM_PROMPT, text


# ------------------------------------------------------------------------------
# Parsing and validation
# ------------------------------------------------------------------------------

def _coerce_enum(enum_cls: Any, value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, enum_cls):
        return value
    raw = str(value).strip()
    for member in enum_cls:
        if raw == member.value or raw.lower() == member.value.lower() or raw.upper() == member.name:
            return member
    raise ValueError(f"'{value}' is not one of: {_values(enum_cls)}")


def parse_beats(
    payload: Any,
    brief: BriefArtifact,
    archetype: ProductArchetype,
    display_name: str,
) -> Tuple[List[ScriptBeat], List[str]]:
    """Turn the model's JSON into ScriptBeats. Returns (beats, errors); errors are repair feedback."""
    errors: List[str] = []
    raw_beats = payload.get("beats") if isinstance(payload, dict) else payload
    if not isinstance(raw_beats, list) or not raw_beats:
        return [], ['top-level JSON must be {"beats": [ ... ]} with a non-empty list']
    if not MIN_BEATS <= len(raw_beats) <= MAX_BEATS:
        errors.append(f"use between {MIN_BEATS} and {MAX_BEATS} beats (got {len(raw_beats)})")

    config = get_archetype_config(archetype)
    beats: List[ScriptBeat] = []
    for idx, raw in enumerate(raw_beats, start=1):
        label = f"beat {idx}"
        if not isinstance(raw, dict):
            errors.append(f"{label}: must be a JSON object")
            continue
        beat_type = re.sub(r"[^a-z0-9_]+", "_", str(raw.get("beat_type") or "").strip().lower()).strip("_")
        if not beat_type:
            errors.append(f"{label}: missing beat_type")
            continue
        fields: Dict[str, Any] = {}
        for name, enum_cls in _ENUM_FIELDS.items():
            try:
                fields[name] = _coerce_enum(enum_cls, raw.get(name))
            except ValueError as exc:
                errors.append(f"{label}.{name}: {exc}")
        role = fields.get("character_role") or brief.character_role
        audio = fields.get("audio_strategy") or brief.target_audio_strategy or config.default_audio_strategy
        # Only a presenter lip-syncs; everyone else is voiced off camera.
        if audio == AudioStrategy.ON_CAMERA_SPEECH and role != CharacterRole.PRESENTER:
            audio = AudioStrategy.OFF_CAMERA_VO
        fields["character_role"], fields["audio_strategy"] = role, audio
        for name in ("spoken_text", "on_screen_text", "visual_cue", "visual_cue_en"):
            if raw.get(name) is not None and not isinstance(raw.get(name), str):
                errors.append(f"{label}.{name}: must be a string")
        try:
            duration = float(raw.get("duration_seconds", raw.get("estimated_duration")))
        except (TypeError, ValueError):
            errors.append(f"{label}: duration_seconds must be a number")
            continue
        transition = None if idx == 1 else raw.get("transition") or dict(sw._CUT_TRANSITION)
        try:
            beats.append(
                ScriptBeat(
                    scene_id=f"shot_{idx:02d}_{beat_type}",
                    beat_type=beat_type,
                    spoken_text=(raw.get("spoken_text") or "").strip(),
                    on_screen_text=(raw.get("on_screen_text") or "").strip(),
                    visual_cue=(raw.get("visual_cue") or "").strip(),
                    visual_cue_en=(raw.get("visual_cue_en") or "").strip() or None,
                    estimated_duration=duration,
                    archetype=archetype,
                    narrative_purpose=(raw.get("narrative_purpose") or None),
                    transition=transition,
                    **fields,
                )
            )
        except Exception as exc:  # pydantic ValidationError (bad transition etc.)
            errors.append(f"{label}: {str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__}")
    # Beats with parse errors were skipped; indices above stay aligned with the model's own numbering.
    for beat in beats:
        if not beat.spoken_text.strip() and beat.audio_strategy != AudioStrategy.MUSIC_AND_SFX_ONLY:
            errors.append(f"{beat.scene_id}: spoken_text is empty but the beat is voiced")
        if len(beat.on_screen_text) > MAX_CAPTION_CHARS:
            errors.append(f"{beat.scene_id}: on_screen_text is {len(beat.on_screen_text)} chars (max {MAX_CAPTION_CHARS})")
        if not beat.visual_cue_en:
            errors.append(f"{beat.scene_id}: visual_cue_en is required")
        else:
            english = beat.visual_cue_en.replace(display_name, "").replace(brief.product_name, "")
            if _VIETNAMESE_CHARS.search(english):
                errors.append(f"{beat.scene_id}: visual_cue_en must be English (no Vietnamese words)")
    return beats, errors


def check_script(
    beats: List[ScriptBeat], brief: BriefArtifact, research: Dict[str, Any]
) -> List[str]:
    """validate_script (after fitting durations to speech) plus the no-fabrication lint."""
    issues = sw.fit_beat_durations_to_speech(beats)
    issues += sw.validate_script(beats)
    issues += sw.find_unsupported_claims(beats, brief, research)
    return list(dict.fromkeys(issues))


# ------------------------------------------------------------------------------
# LLM round trip
# ------------------------------------------------------------------------------

def _repair_prompt(user_prompt: str, previous: str, errors: List[str]) -> str:
    bullets = "\n".join(f"- {e}" for e in errors[:20])
    return (
        f"{user_prompt}\n\nYOUR PREVIOUS ANSWER WAS REJECTED.\nPrevious answer:\n{previous}\n\n"
        f"Errors to fix:\n{bullets}\n\nReturn the complete corrected script as strict JSON in the same schema. "
        "Shorten spoken lines or durations as required, and remove every number or claim that is not in the facts above."
    )


def _call(system: str, user: str, model: Optional[str], attempt: int) -> Dict[str, Any]:
    started = time.monotonic()
    meta = {"model": model or llm.default_model(), "attempt": attempt, "system_prompt_chars": len(system),
            "user_prompt_chars": len(user)}
    try:
        result = llm.chat(system, user, model=model, timeout=SCRIPT_LLM_TIMEOUT, temperature=0.7, max_tokens=6000)
    except Exception as exc:
        telemetry.record_api_call(
            "llm.script_draft", request=meta, response={"error": str(exc)}, status="error", ok=False,
            duration_seconds=time.monotonic() - started, stage=STAGE_SCRIPTWRITING,
        )
        raise
    telemetry.record_api_call(
        "llm.script_draft", request={**meta, "model_used": result.get("model")},
        response={"content_chars": len(result.get("content") or ""), "usage": result.get("usage")},
        status=200, ok=True, duration_seconds=time.monotonic() - started, stage=STAGE_SCRIPTWRITING,
    )
    return result


def draft_script_with_llm(
    brief: BriefArtifact,
    archetype: ProductArchetype,
    artifacts_dir: Optional[Path] = None,
    model: Optional[str] = None,
) -> Optional[List[ScriptBeat]]:
    """Draft validated beats with the LLM, or ``None`` when the templates should be used instead.

    Never calls the provider offline. Failure reasons are written to telemetry notes.
    """
    if is_offline():
        return None
    research = sw.load_research_context(artifacts_dir)
    offer = sw._resolve_offer(brief, artifacts_dir)
    display = sw.derive_display_name(brief.product_name)
    system, user = build_prompts(brief, archetype, research, offer)
    if offer:  # an advertiser-supplied offer is a legitimate source for the lint
        research = {**research, "supplied_offer": offer}

    prompt = user
    previous = ""
    last_errors: List[str] = []
    used_model = model or llm.default_model()
    for attempt in (1, 2):
        try:
            result = _call(system, prompt, model, attempt)
        except OfflineNetworkError:
            return None
        except Exception as exc:
            telemetry.note(f"LLM script draft unavailable ({exc}); using deterministic templates",
                           error=str(exc), fallback="deterministic_beat_templates")
            return None
        used_model = result.get("model") or used_model
        previous = result.get("content") or ""
        telemetry.record_prompt(
            f"script_draft_attempt_{attempt}", f"{system}\n\n---\n\n{prompt}", stage=STAGE_SCRIPTWRITING,
            model=used_model, kind="script_llm",
        )
        try:
            payload = llm.extract_json(previous)
        except ValueError as exc:
            last_errors = [f"response was not valid JSON: {exc}"]
        else:
            beats, parse_errors = parse_beats(payload, brief, archetype, display)
            last_errors = parse_errors or check_script(beats, brief, research)
            if not last_errors:
                telemetry.note(
                    f"LLM script draft accepted ({len(beats)} beats, model {used_model}, attempt {attempt})",
                    model=used_model, attempt=attempt, generator="llm_script",
                )
                return beats
        telemetry.note(
            f"LLM script draft attempt {attempt} rejected: " + "; ".join(last_errors[:8]),
            attempt=attempt, errors=last_errors, model=used_model,
        )
        prompt = _repair_prompt(user, previous[:6000], last_errors)

    telemetry.note(
        "LLM script draft failed validation after one repair retry; using deterministic templates",
        errors=last_errors, model=used_model, fallback="deterministic_beat_templates",
    )
    return None
