"""Step 3: Cinematic Storyboard & 6-Part Prompt Planning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pipeline.config import ARTIFACTS_DIR, CHARACTER_PATH
from pipeline.schemas import ScenePlanArtifact, ScriptArtifact, StoryboardShot
from pipeline.archetypes import (
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
    generate_storyboard_contact_sheet,
)
from pipeline.lip_sync_engine import determine_lip_sync_strategy

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


def generate_scene_plan(
    script: ScriptArtifact | None = None,
    script_path: Path | None = None,
    character_path: Path | None = None,
    output_dir: Path | None = None,
) -> ScenePlanArtifact:
    """Generates the cinematic scene plan artifact."""
    target_artifacts_dir = output_dir or ARTIFACTS_DIR
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

    char_tag = char_data.get("character_tag", "[KOL_MA]")
    face_prompt = char_data.get("face_prompt", "")
    identity_lock = f"Same character, consistent facial structure, {face_prompt}"
    style_pos = "cinematic photorealistic, modern minimalist office, high-end commercial aesthetic, studio softbox lighting, 8k, tack sharp focus, clean background"
    style_neg = "watermark, text, logo overlay, deformed limbs, bad hands, blurry, lowres, oversaturated, 3d render, cartoon"

    if script.campaign_id != "campaign_lumina_mug_01" or script.archetype != ProductArchetype.GENERAL_COMMERCIAL or len(script.beats) != 4:
        persona = DynamicPromptBuilder.resolve_persona(script.archetype)
        arch_config = get_archetype_config(script.archetype)
        wardrobe, environment = resolve_wardrobe_and_environment(script.archetype)

        # Dynamic Framing Scale cycle: Wide -> Cowboy -> Macro -> Medium -> Medium Close-Up -> Close-Up
        scale_cycle = [
            ShotScale.WS,
            ShotScale.MWS,
            ShotScale.ECU,
            ShotScale.MS,
            ShotScale.MCU,
            ShotScale.CU,
        ]

        shots: List[StoryboardShot] = []
        for idx, beat in enumerate(script.beats, start=1):
            shot_id = f"shot_{idx:02d}"
            is_prod_only = beat.character_role == CharacterRole.PRODUCT_ONLY
            shot_scale = scale_cycle[(idx - 1) % len(scale_cycle)]
            framing = build_framing_directive(scale=shot_scale, focal_point=script.product_name if is_prod_only else persona.name)
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
                scene_action=beat.visual_cue,
                persona=persona,
                lighting=beat.lighting_contract,
                camera=beat.camera_choreography,
            )
            prompt_parts = [
                framing.prompt_optics_directive,
                base_prompt,
                environment.prompt_set_directive,
            ]
            if not is_prod_only:
                prompt_parts.append(wardrobe.prompt_wear_directive)
                if lip_decision.prompt_articulation_directive:
                    prompt_parts.append(lip_decision.prompt_articulation_directive)

            full_cinematic_prompt = " ".join(prompt_parts)

            expr_path = None
            if not is_prod_only:
                expr_path = DynamicPromptBuilder.get_reference_expression_path(
                    persona=persona,
                    archetype=script.archetype,
                    emotion_intent=beat.beat_type,
                )

            shots.append(
                StoryboardShot(
                    shot_id=shot_id,
                    scene_id=beat.scene_id,
                    shot_type=f"{shot_scale.value.upper()} • {beat.beat_type.capitalize()}",
                    angle=framing.angle.value,
                    camera_motion=beat.camera_choreography.value if beat.camera_choreography else "Smooth commercial track",
                    lighting=beat.lighting_contract.value if beat.lighting_contract else arch_config.default_lighting.value,
                    character_tag=None if is_prod_only else persona.character_tag,
                    identity_lock_directive=None if is_prod_only else f"Same character {persona.character_tag}, {persona.base_face_prompt}",
                    style_constraints=f"{arch_config.display_name} commercial aesthetic | Avoid: {style_neg}",
                    scene_description=beat.visual_cue,
                    prompt_6part=full_cinematic_prompt,
                    estimated_duration=beat.estimated_duration,
                    reference_expression=expr_path,
                    character_role=beat.character_role,
                    camera_choreography=beat.camera_choreography.value if beat.camera_choreography else None,
                    lighting_contract=beat.lighting_contract.value if beat.lighting_contract else None,
                    narrative_purpose=beat.narrative_purpose,
                    color_temp_kelvin=environment.nominal_color_temp_kelvin,
                    is_hero_moment=idx in (2, 3) or "solution" in beat.beat_type or "reveal" in beat.beat_type,
                )
            )

        # Generate DramaClaw Storyboard Contact Sheet
        contact_sheet_path = target_artifacts_dir / "storyboard_contact_sheet.jpg"
        sheet_shot_dicts = []
        for s in shots:
            d = s.model_dump()
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

        scene_plan = ScenePlanArtifact(
            campaign_id=script.campaign_id,
            shots=shots,
            slideshow_risk=score_slideshow_risk(shots).model_dump(),
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
            "reference_expression": "assets/characters/kol_main/expressions/03_surprised.jpg",
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
            "reference_expression": "assets/characters/kol_main/expressions/04_looking_down.jpg",
            "duration": 5.0,
        },
        {
            "shot_id": "shot_03",
            "scene_id": "shot_03_solution",
            "shot_type": "Medium Glamour Product Presenter Shot",
            "angle": "Straight on slightly dynamic three-quarter angle",
            "camera_motion": "Cinematic slow arc orbit with shallow DOF",
            "lighting": "Warm studio luxury backlight, soft beauty key light",
            "scene_action": f"{char_tag} holding the sleek matte-finish Lumina Smart Mug with both hands, gently tapping the glossy touch LED lid that illuminates '65°C', taking a warm sip and smiling with immense satisfaction",
            "camera_choreography": "Camera motion: slow cinematic orbit zoom-in, smooth floating stabilizer movement, high luxury commercial feel",
            "reference_expression": "assets/characters/kol_main/expressions/02_smiling.jpg",
            "duration": 12.0,
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
            "reference_expression": "assets/characters/kol_main/expressions/02_smiling.jpg",
            "duration": 6.5,
        },
    ]

    shots: List[StoryboardShot] = []
    for cfg in shot_configs:
        prompt_6 = build_6part_prompt(
            aspect_ratio="9:16",
            character_tag=char_tag,
            identity_lock=identity_lock,
            style_positive=style_pos,
            style_negative=style_neg,
            scene_action=cfg["scene_action"],
            camera_choreography=cfg["camera_choreography"],
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
                reference_expression=cfg["reference_expression"],
            )
        )

    scene_plan = ScenePlanArtifact(
        campaign_id=script.campaign_id,
        shots=shots,
        slideshow_risk=score_slideshow_risk(shots).model_dump(),
    )

    out_file = target_artifacts_dir / "scene_plan.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(scene_plan.model_dump(), f, ensure_ascii=False, indent=2)

    return scene_plan
