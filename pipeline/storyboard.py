"""Step 3: Cinematic Storyboard & 6-Part Prompt Planning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pipeline.config import ARTIFACTS_DIR, CHARACTER_PATH
from pipeline.schemas import ScenePlanArtifact, ScriptArtifact, StoryboardShot


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
    )

    out_file = target_artifacts_dir / "scene_plan.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(scene_plan.model_dump(), f, ensure_ascii=False, indent=2)

    return scene_plan
