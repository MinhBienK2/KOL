"""Step 3: Cinematic Storyboard & 6-Part Prompt Planning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pipeline import telemetry
from pipeline.config import ARTIFACTS_DIR, CHARACTER_PATH
from pipeline.schemas import ScenePlanArtifact, ScriptArtifact, StoryboardShot
from pipeline.workspace import ProjectWorkspace
from pipeline.archetypes import (
    CharacterPersona,
    CharacterRole,
    DynamicPromptBuilder,
    ProductArchetype,
    get_archetype_config,
)
from pipeline.slideshow_risk import score_slideshow_risk
from pipeline.wardrobe import resolve_wardrobe_and_environment
from pipeline.cinematography import (
    CameraAngle,
    CameraLens,
    ShotScale,
    build_framing_directive,
    camera_phrase,
    compact_video_prompt,
    generate_storyboard_contact_sheet,
    plan_shot_scales,
)
from pipeline.spatial_staging import SpatialContinuityContract
from pipeline.lip_sync_engine import determine_lip_sync_strategy
from pipeline.scriptwriter import LEGACY_MUG_CAMPAIGN_ID, LEGACY_MUG_SCENE_IDS

def build_6part_prompt(
    aspect_ratio: str,
    character_tag: str,
    identity_lock: str,
    style_positive: str,
    style_negative: str,
    scene_action: str,
    camera_choreography: str,
) -> str:
    """Builds a DramaClaw compliant 6-part cinematic prompt."""
    parts = [
        f"Generate a [{aspect_ratio}] aspect ratio cinematic commercial shot.",
        f"Character: {character_tag}.",
        f"Identity lock: {identity_lock}.",
        f"Style: {style_positive}. Avoid: {style_negative}.",
        f"Scene action: {scene_action}.",
        f"Camera choreography: {camera_choreography}.",
    ]
    return " ".join(parts)


def _coerce_enum(enum_cls, raw: Any, field: str):
    """Accept an enum member, its value, or its name (case-insensitive) for an override."""
    if isinstance(raw, enum_cls):
        return raw
    text = str(raw).strip().lower()
    for member in enum_cls:
        if text in (member.value.lower(), member.name.lower()):
            return member
    valid = ", ".join(m.value for m in enum_cls)
    raise ValueError(f"Invalid {field} override '{raw}'. Valid values: {valid}")


def _shot_override(overrides: Dict[str, Dict[str, Any]], shot_id: str, scene_id: str) -> Dict[str, Any]:
    """Merge overrides addressed by shot_id and/or scene_id (scene_id wins)."""
    merged: Dict[str, Any] = {}
    merged.update(overrides.get(shot_id, {}))
    merged.update(overrides.get(scene_id, {}))
    return merged


def _shot_intent(beat: Any) -> str:
    """Explicit commercial intent for the Slideshow Risk Gate and contact sheet."""
    purpose = (beat.narrative_purpose or "").strip()
    return f"{beat.beat_type}: {purpose}" if purpose else beat.beat_type


def generate_scene_plan(
    script: ScriptArtifact | None = None,
    script_path: Path | None = None,
    character_path: Path | None = None,
    output_dir: Path | None = None,
    workspace: Optional[ProjectWorkspace] = None,
    shot_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    persona: Optional[Union[str, CharacterPersona]] = None,
) -> ScenePlanArtifact:
    """Generates the cinematic scene plan artifact.

    The KOL that drives identity/wardrobe prompts is chosen by, in order: ``persona`` (a
    ``CharacterPersona`` or a PERSONA_CATALOG id such as "kol_main"), an explicitly
    passed ``character_path`` (a character.json, whose directory name becomes the persona
    id), else the archetype default.

    Per-shot direction precedence: ``shot_overrides`` > ``ScriptBeat.shot_scale/lens/angle``
    (persisted agent direction in script.json) > automatic beat-aware planning. English
    prompts use ``ScriptBeat.visual_cue_en`` when present, else the Vietnamese ``visual_cue``.

    ``shot_overrides`` lets an orchestrating agent direct individual shots. Keys are a
    ``shot_id`` ("shot_02") or a script ``scene_id``; values may contain ``shot_scale``
    (ShotScale value/name), ``lens`` (CameraLens), ``angle`` (CameraAngle) and
    ``extra_direction`` (free text appended to the generation prompt). Unknown scale,
    lens or angle values raise ``ValueError``.
    """
    shot_overrides = shot_overrides or {}
    target_artifacts_dir = workspace.artifacts_dir if workspace is not None else (output_dir or ARTIFACTS_DIR)
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)

    if script is None:
        source_script = script_path or (target_artifacts_dir / "script.json")
        if not source_script.exists():
            raise FileNotFoundError(f"Script file not found at {source_script}")
        with open(source_script, "r", encoding="utf-8") as f:
            script = ScriptArtifact.model_validate(json.load(f))

    char_file = character_path or CHARACTER_PATH
    with open(char_file, "r", encoding="utf-8") as f:
        char_data = json.load(f)

    explicit_persona: Optional[CharacterPersona] = None
    if persona is not None:
        explicit_persona = DynamicPromptBuilder.resolve_persona(script.archetype, persona)
    elif character_path is not None:
        explicit_persona = DynamicPromptBuilder.persona_from_character_file(char_file, script.archetype)

    char_tag = explicit_persona.character_tag if explicit_persona else char_data.get("character_tag", "[KOL_MAIN]")
    face_prompt = explicit_persona.base_face_prompt if explicit_persona else char_data.get("face_prompt", "")
    identity_lock = f"Same character, consistent facial structure, {face_prompt}"
    style_pos = "cinematic photorealistic, modern minimalist office, high-end commercial aesthetic, studio softbox lighting, 8k, tack sharp focus, clean background"
    style_neg = "watermark, text, logo overlay, deformed limbs, bad hands, blurry, lowres, oversaturated, 3d render, cartoon"

    is_legacy_mug = (
        script.campaign_id == LEGACY_MUG_CAMPAIGN_ID
        and script.archetype == ProductArchetype.GENERAL_COMMERCIAL
        and [b.scene_id for b in script.beats] == LEGACY_MUG_SCENE_IDS
    )
    if not is_legacy_mug:
        persona = explicit_persona or DynamicPromptBuilder.resolve_persona(script.archetype)
        arch_config = get_archetype_config(script.archetype)
        wardrobe, environment = resolve_wardrobe_and_environment(script.archetype)

        # Beat-aware framing: presenter faces stay readable, macro for texture beats, varied rhythm.
        planned_scales = plan_shot_scales(script.beats)

        # Spatial continuity contract: one environment, one colour temperature, one key-light side.
        spatial_contract = SpatialContinuityContract(
            environment_name=environment.name,
            nominal_kelvin=environment.nominal_color_temp_kelvin,
        )
        framing_meta: Dict[str, Dict[str, str]] = {}

        shots: List[StoryboardShot] = []
        for idx, beat in enumerate(script.beats, start=1):
            shot_id = f"shot_{idx:02d}"
            is_prod_only = beat.character_role == CharacterRole.PRODUCT_ONLY
            override = _shot_override(shot_overrides, shot_id, beat.scene_id)
            shot_scale = (
                _coerce_enum(ShotScale, override["shot_scale"], "shot_scale")
                if "shot_scale" in override
                else (beat.shot_scale or planned_scales[idx - 1])
            )
            lens_override = (
                _coerce_enum(CameraLens, override["lens"], "lens") if "lens" in override else beat.lens
            )
            angle_override = (
                _coerce_enum(CameraAngle, override["angle"], "angle") if "angle" in override else beat.angle
            )
            # English cue for video models; the Vietnamese visual_cue stays the fallback.
            scene_action = beat.visual_cue_en or beat.visual_cue
            shot_type_label = f"{shot_scale.value.upper()} • {beat.beat_type.capitalize()}"
            telemetry.stage_progress(
                3,
                idx,
                len(script.beats),
                unit="shots",
                label=f"Planning {shot_id}",
                item={"id": shot_id, "label": shot_type_label, "status": "planned", "beat_type": beat.beat_type},
            )
            framing = build_framing_directive(
                scale=shot_scale,
                lens=lens_override,
                angle=angle_override,
                focal_point=script.product_name if is_prod_only else persona.name,
            )
            framing_meta[shot_id] = {"shot_scale": shot_scale.name, "lens": framing.lens.value}
            lip_decision = determine_lip_sync_strategy(
                shot_id=shot_id,
                character_role=beat.character_role,
                audio_strategy=beat.audio_strategy,
                spoken_text=beat.spoken_text,
            )

            # Build enriched multi-layer prompt combining Framing, Identity, WEAR, SET, Action, and Articulation
            base_prompt = DynamicPromptBuilder.build_subject_and_action_prompt(
                character_role=beat.character_role,
                archetype=script.archetype,
                product_name=script.product_name,
                scene_action=scene_action,
                persona=persona,
                lighting=beat.lighting_contract,
                camera=beat.camera_choreography,
            )
            framing_clause = framing.to_natural_clause()
            prompt_parts = [
                framing_clause,
                base_prompt,
                environment.prompt_set_directive,
            ]
            if not is_prod_only:
                prompt_parts.append(wardrobe.prompt_wear_directive)
                if lip_decision.prompt_articulation_directive:
                    prompt_parts.append(lip_decision.prompt_articulation_directive)

            extra_direction = str(override.get("extra_direction", "")).strip()
            if extra_direction:
                prompt_parts.append(extra_direction.rstrip(".") + ".")

            # Model-ready: plain camera/lighting wording, no duplicate/filler sentences, word budget.
            full_cinematic_prompt = compact_video_prompt(" ".join(prompt_parts))

            # Prompt ledger: the supervisor must see the exact cinematic prompt before rendering.
            telemetry.record_prompt(
                shot_id,
                full_cinematic_prompt,
                stage=3,
                source="scene_plan",
                mode="T2V" if is_prod_only else "I2V",
                shot_type=shot_type_label,
                angle=framing.angle.value,
                camera_motion=beat.camera_choreography.value if beat.camera_choreography else "Smooth commercial track",
                lighting=beat.lighting_contract.value if beat.lighting_contract else arch_config.default_lighting.value,
                estimated_duration=beat.estimated_duration,
                segments=[
                    {"label": "Framing & optics", "text": framing_clause},
                    {"label": "Subject & action", "text": base_prompt},
                    {"label": "Set & environment", "text": environment.prompt_set_directive},
                    *([{"label": "Wardrobe", "text": wardrobe.prompt_wear_directive}] if not is_prod_only else []),
                    *(
                        [{"label": "Articulation", "text": lip_decision.prompt_articulation_directive}]
                        if not is_prod_only and lip_decision.prompt_articulation_directive
                        else []
                    ),
                ],
            )

            shots.append(
                StoryboardShot(
                    shot_id=shot_id,
                    scene_id=beat.scene_id,
                    shot_type=shot_type_label,
                    angle=framing.angle.value,
                    camera_motion=beat.camera_choreography.value if beat.camera_choreography else "Smooth commercial track",
                    lighting=beat.lighting_contract.value if beat.lighting_contract else arch_config.default_lighting.value,
                    character_tag=None if is_prod_only else persona.character_tag,
                    identity_lock_directive=None if is_prod_only else f"Same character {persona.character_tag}, {persona.base_face_prompt}",
                    style_constraints=f"{arch_config.display_name} commercial aesthetic | Avoid: {style_neg}",
                    scene_description=scene_action,
                    prompt_6part=full_cinematic_prompt,
                    estimated_duration=beat.estimated_duration,
                    character_role=beat.character_role,
                    camera_choreography=beat.camera_choreography.value if beat.camera_choreography else None,
                    lighting_contract=beat.lighting_contract.value if beat.lighting_contract else None,
                    narrative_purpose=beat.narrative_purpose,
                    color_temp_kelvin=environment.nominal_color_temp_kelvin,
                    shot_intent=_shot_intent(beat),
                    transition=beat.transition,
                    spatial_staging=(
                        f"{environment.name} @ {environment.nominal_color_temp_kelvin}K, "
                        f"key light locked to {spatial_contract.locked_key_light_azimuth} degrees camera-left"
                    ),
                    is_hero_moment=idx in (2, 3) or "solution" in beat.beat_type or "reveal" in beat.beat_type,
                )
            )

        # Generate DramaClaw Storyboard Contact Sheet
        contact_sheet_path = target_artifacts_dir / "storyboard_contact_sheet.jpg"
        sheet_shot_dicts = []
        for s in shots:
            d = s.model_dump()
            d.update(framing_meta.get(s.shot_id, {}))
            matching_beat = next((b for b in script.beats if b.scene_id == s.scene_id), None)
            if matching_beat:
                d["spoken_text"] = matching_beat.spoken_text
                d["on_screen_text"] = matching_beat.on_screen_text
            sheet_shot_dicts.append(d)

        generate_storyboard_contact_sheet(
            shots=sheet_shot_dicts,
            output_path=contact_sheet_path,
            campaign_title=f"{script.product_name} Storyboard",
        )

        telemetry.register_artifact(contact_sheet_path, stage=3, label="Storyboard contact sheet")

        risk_report = score_slideshow_risk(shots)
        telemetry.note(
            f"Storyboard slideshow risk: score {risk_report.average_score} ({risk_report.verdict})",
            average_score=risk_report.average_score,
            verdict=risk_report.verdict,
            passed=risk_report.passed,
            hard_reject_reasons=risk_report.hard_reject_reasons,
        )
        continuity_ok, continuity_issues = spatial_contract.validate_shot_continuity(
            [(s.shot_id, s.color_temp_kelvin or spatial_contract.nominal_kelvin) for s in shots]
        )
        scene_plan = ScenePlanArtifact(
            campaign_id=script.campaign_id,
            shots=shots,
            slideshow_risk=risk_report.model_dump(),
            spatial_staging_contract={
                "environment_name": spatial_contract.environment_name,
                "nominal_kelvin": spatial_contract.nominal_kelvin,
                "max_kelvin_drift": spatial_contract.max_kelvin_drift,
                "locked_key_light_azimuth": spatial_contract.locked_key_light_azimuth,
                "continuity_ok": continuity_ok,
                "issues": continuity_issues,
            },
            storyboard_contact_sheet=str(contact_sheet_path),
        )
        out_file = target_artifacts_dir / "scene_plan.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(scene_plan.model_dump(), f, ensure_ascii=False, indent=2)
        return scene_plan

    shot_configs = [
        {
            "shot_id": "shot_01",
            "scene_id": "shot_01_hook",
            "shot_type": "Close-up with presenter reaction",
            "angle": "Eye level slightly low angle",
            "camera_motion": "Slow smooth push-in",
            "lighting": "Cool corporate morning daylight with soft rim light",
            "scene_action": f"{char_tag} sitting at a modern wooden office desk looking at a cold cup of coffee, touching the cold mug and shaking her head with an expressive surprised and disappointed look",
            "camera_choreography": "Camera motion: slow push-in, shallow depth of field, 4k 60fps feel",
            "duration": 3.5,
        },
        {
            "shot_id": "shot_02",
            "scene_id": "shot_02_pain",
            "shot_type": "Over-the-shoulder POV to desk",
            "angle": "High-angle POV looking down to workspace",
            "camera_motion": "Subtle handheld tracking tilt",
            "lighting": "Contrasty office daylight highlighting liquid condensation",
            "scene_action": f"Close-up of workspace where melting water droplets drip from a cold cup onto important paper reports and laptop keyboard, {char_tag} hands gently wiping the droplets with a tissue with frustrated gesture",
            "camera_choreography": "Camera motion: steady tracking pan, crisp macro focus on droplets, dynamic commercial pacing",
            "duration": 5.0,
        },
        {
            "shot_id": "shot_03",
            "scene_id": "shot_03_solution",
            "shot_type": "Medium Glamour Product Presenter Shot",
            "angle": "Straight on slightly dynamic three-quarter angle",
            "camera_motion": "Cinematic slow arc orbit with shallow DOF",
            "lighting": "Warm studio luxury backlight, soft beauty key light",
            "scene_action": f"{char_tag} holding the sleek matte-finish Lumina Smart Mug with both hands, gently tapping the glossy touch LED lid that lights up, taking a warm sip and smiling with immense satisfaction",
            "camera_choreography": "Camera motion: slow cinematic orbit zoom-in, smooth floating stabilizer movement, high luxury commercial feel",
            "duration": 6.0,
        },
        {
            "shot_id": "shot_04",
            "scene_id": "shot_04_cta",
            "shot_type": "Medium Presenter CTA Shot",
            "angle": "Eye level centered hero angle",
            "camera_motion": "Slow forward push-in with cheerful natural posture",
            "lighting": "Bright radiant commercial key lighting, vibrant and trustworthy",
            "scene_action": f"{char_tag} standing upright in professional tailored office attire, holding up the Lumina Smart Mug toward the camera, smiling warmly and gesturing with invitation to check the link below",
            "camera_choreography": "Camera motion: gentle push-in, perfect centering for bottom CTA badge and promo graphic",
            "duration": 5.0,
        },
    ]
    script_durations = {b.scene_id: b.estimated_duration for b in script.beats}
    script_transitions = {b.scene_id: b.transition for b in script.beats}
    for cfg in shot_configs:
        cfg["duration"] = script_durations.get(cfg["scene_id"], cfg["duration"])

    shots: List[StoryboardShot] = []
    for idx, cfg in enumerate(shot_configs, start=1):
        telemetry.stage_progress(
            3,
            idx,
            len(shot_configs),
            unit="shots",
            label=f"Planning {cfg['shot_id']}",
            item={"id": cfg["shot_id"], "label": cfg["shot_type"], "status": "planned"},
        )
        prompt_6 = build_6part_prompt(
            aspect_ratio="9:16",
            character_tag=char_tag,
            identity_lock=identity_lock,
            style_positive=style_pos,
            style_negative=style_neg,
            scene_action=cfg["scene_action"],
            camera_choreography=cfg["camera_choreography"],
        )
        telemetry.record_prompt(
            cfg["shot_id"],
            prompt_6,
            stage=3,
            source="scene_plan",
            mode="I2V",
            shot_type=cfg["shot_type"],
            angle=cfg["angle"],
            camera_motion=cfg["camera_motion"],
            lighting=cfg["lighting"],
            estimated_duration=cfg["duration"],
            segments=[{"label": "6-part cinematic prompt", "text": prompt_6}],
        )
        shots.append(
            StoryboardShot(
                shot_id=cfg["shot_id"],
                scene_id=cfg["scene_id"],
                shot_type=cfg["shot_type"],
                angle=cfg["angle"],
                camera_motion=cfg["camera_motion"],
                lighting=cfg["lighting"],
                character_tag=char_tag,
                identity_lock_directive=identity_lock,
                style_constraints=f"{style_pos} | Avoid: {style_neg}",
                scene_description=cfg["scene_action"],
                prompt_6part=prompt_6,
                estimated_duration=cfg["duration"],
                transition=script_transitions.get(cfg["scene_id"]),
            )
        )

    legacy_risk_report = score_slideshow_risk(shots)
    telemetry.note(
        f"Storyboard slideshow risk: score {legacy_risk_report.average_score} ({legacy_risk_report.verdict})",
        average_score=legacy_risk_report.average_score,
        verdict=legacy_risk_report.verdict,
        passed=legacy_risk_report.passed,
        hard_reject_reasons=legacy_risk_report.hard_reject_reasons,
    )
    scene_plan = ScenePlanArtifact(
        campaign_id=script.campaign_id,
        shots=shots,
        slideshow_risk=legacy_risk_report.model_dump(),
    )

    out_file = target_artifacts_dir / "scene_plan.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(scene_plan.model_dump(), f, ensure_ascii=False, indent=2)

    return scene_plan
