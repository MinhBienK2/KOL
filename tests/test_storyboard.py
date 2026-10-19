from pathlib import Path
import json

from pipeline.briefing import create_product_brief
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan, build_6part_prompt
from pipeline.schemas import ScenePlanArtifact


def test_build_6part_prompt():
    prompt = build_6part_prompt(
        aspect_ratio="9:16",
        character_tag="[KOL_MA]",
        identity_lock="lock_directive",
        style_positive="clean, studio",
        style_negative="blurry",
        scene_action="smiling",
        camera_choreography="slow push",
    )
    assert "[9:16]" in prompt
    assert "[KOL_MA]" in prompt
    assert "lock_directive" in prompt
    assert "clean, studio" in prompt
    assert "blurry" in prompt
    assert "smiling" in prompt
    assert "slow push" in prompt


def test_generate_scene_plan(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path)
    plan = generate_scene_plan(script=script, output_dir=tmp_path)

    assert plan.campaign_id == script.campaign_id
    assert len(plan.shots) == 4
    for shot in plan.shots:
        assert shot.character_tag in ("[KOL_MAIN]", "[KOL_MA]")
        assert shot.prompt_6part.startswith("Generate a [9:16]")
        assert shot.estimated_duration > 0

    out_file = tmp_path / "scene_plan.json"
    assert out_file.exists()
    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    loaded = ScenePlanArtifact.model_validate(data)
    assert len(loaded.shots) == 4
