from pathlib import Path
import json

from PIL import Image

from pipeline.briefing import create_product_brief
from pipeline.identity_keyframe import generate_clean_keyframes
from pipeline.schemas import ScenePlanArtifact
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from pipeline.video_engine import video_prompt_for
from tools import prompt_pack


def _run_dir(tmp_path: Path) -> Path:
    from pipeline.archetypes import ProductArchetype

    run = tmp_path / "projects" / "fashion_apparel" / "pp_test" / "runs" / "v1"
    artifacts = run / "artifacts"
    artifacts.mkdir(parents=True)
    brief = create_product_brief(
        campaign_id="pp_test", product_name="Áo Khoác Blazer Nữ",
        archetype=ProductArchetype.FASHION_APPAREL, output_dir=artifacts,
    )
    script = generate_commercial_script(brief=brief, output_dir=artifacts)
    generate_scene_plan(script=script, output_dir=artifacts)
    input_dir = run.parent.parent / "input"
    input_dir.mkdir()
    Image.new("RGB", (1200, 1200), (200, 180, 160)).save(input_dir / "product_hero.jpg")
    return run


def test_prompt_pack_matches_what_stage_4_would_send(tmp_path: Path, monkeypatch):
    # The pack is a review surface: if it drifts from Stage 4, QA approves prompts that are never sent.
    from pipeline import identity_keyframe

    run = _run_dir(tmp_path)
    artifacts = run / "artifacts"
    sent = {}

    def fake_synth(prompt, out_path, reference_paths):
        sent[Path(out_path).name.split("_synth")[0]] = (prompt, [Path(p).name for p in reference_paths])
        Image.new("RGB", (1080, 1920), (90, 60, 30)).save(out_path)
        return out_path

    monkeypatch.setattr(identity_keyframe, "synthesize_first_frame", fake_synth)
    plan = ScenePlanArtifact.model_validate(json.loads((artifacts / "scene_plan.json").read_text()))
    manifest = generate_clean_keyframes(
        scene_plan=plan, output_dir=artifacts, keyframes_dir=run / "keyframes",
        reference_overrides={"product_hero": str(run.parent.parent / "input" / "product_hero.jpg")},
        synthesize_frames=True,
    )

    pack = prompt_pack.build_prompt_pack(run)
    assert pack["errors"] == []
    assert [s["shot_id"] for s in pack["shots"]] == [s.shot_id for s in plan.shots]
    for shot in pack["shots"]:
        prompt, refs = sent[shot["shot_id"]]
        assert shot["image"]["prompt"] == prompt
        assert [Path(r["path"]).name for r in shot["image"]["references"]] == refs
        planned = next(s for s in plan.shots if s.shot_id == shot["shot_id"])
        kf = next(k for k in manifest.keyframes if k.shot_id == shot["shot_id"])
        assert shot["video"]["prompt"] == video_prompt_for(planned, kf)
        assert shot["video"]["generated_seconds"] in (6, 10)


def test_prompt_pack_cli_writes_json_and_markdown_without_network(tmp_path: Path, monkeypatch):
    from pipeline import identity_keyframe

    def no_network(*_a, **_k):
        raise AssertionError("prompt pack must never call the image provider")

    monkeypatch.setattr(identity_keyframe, "synthesize_first_frame", no_network)
    run = _run_dir(tmp_path)
    assert prompt_pack.main(["--run", str(run)]) == 0
    md = (run / "artifacts" / "prompt_pack.md").read_text()
    data = json.loads((run / "artifacts" / "prompt_pack.json").read_text())
    assert data["shots"] and "**First frame**" in md and "**Video**" in md


def test_lints_flag_studio_light_tungsten_daylight_and_junk_tags():
    # QA r1 v2 "passed" Stage 3 with studio lighting in a kitchen and "8k".
    class Shot:
        prompt_6part = "Mai Ly in the kitchen, bright midday daylight through the window, studio portrait lighting, 8k"
        scene_description = ""
        color_temp_kelvin = 3200
        motion_prompt = None

    codes = {l["code"] for l in prompt_pack.lint_shot(Shot(), Shot.prompt_6part, Shot.prompt_6part, False)}
    assert {"studio_light_in_location", "kelvin_vs_daylight", "image_junk_tags", "video_junk_tags",
            "video_prompt_is_scene_prompt"} <= codes

    class Clean(Shot):
        prompt_6part = "Mai Ly in a kitchen, warm early sunlight at sunrise"  # golden hour really is ~3200K
        motion_prompt = "[Push in] she flips the egg slowly, ending with the spatula raised."

    assert prompt_pack.lint_shot(Clean(), Clean.prompt_6part, Clean.motion_prompt, False) == []


def test_video_prompt_that_redescribes_the_image_is_an_error():
    class Shot:
        prompt_6part = "kitchen"
        scene_description = ""
        color_temp_kelvin = None
        motion_prompt = "[Push in] She waves. SET: a kitchen. Subject: Vietnamese woman, bob hairstyle."

    codes = {l["code"] for l in prompt_pack.lint_shot(Shot(), "kitchen", Shot.motion_prompt, False)}
    assert "video_redescribes_image" in codes


def test_still_frame_prompt_drops_camera_moves_and_speech_articulation():
    # QA preprod r1: first-frame prompts carried "slow orbit" and "jaw and lip movements in rhythm".
    from pipeline.identity_keyframe import still_frame_prompt

    text = ("SHOT. Delivery action: Direct eye contact to camera, she waves, speaking with clear engaged expression. "
            "Camera move: smooth slow orbit around the subject. SET: an alley. "
            "Presenter speaking directly to camera with active mouth articulation, synchronized natural jaw and lip "
            "movements in rhythm with spoken dialogue.")
    still = still_frame_prompt(text)
    assert "orbit" not in still and "jaw" not in still and "speaking with" not in still
    assert "SET: an alley." in still and "lips softly parted" in still


def test_r2v_video_prompt_carries_the_scene_because_no_frame_is_sent():
    # QA preprod r1: model shots go R2V (face only); a motion-only prompt left set, bike and wardrobe to chance.
    from pipeline.video_engine import video_prompt_for

    class Shot:
        motion_prompt = "[Tracking shot] She pedals steadily, ending at the alley exit."
        prompt_6part = ("wide shot. Visual acting action: She rides the red bicycle. Camera movement: tracking. "
                        "SET: Narrow wet alley. LIGHT: soft overcast daylight, 6500K. WEAR: black tee, half-helmet.")

    class R2V:
        generation_mode = "r2v"
        reference_assets = ["face_anchor.png", "sheet.png"]

    class I2V:
        generation_mode = "i2v"
        reference_assets = None

    assert video_prompt_for(Shot(), I2V()) == Shot.motion_prompt
    r2v = video_prompt_for(Shot(), R2V())
    assert r2v.startswith(Shot.motion_prompt)
    assert "She rides the red bicycle." in r2v and "SET: Narrow wet alley." in r2v and "WEAR:" in r2v
    assert "Camera movement" not in r2v


def test_heavily_trimmed_clip_is_flagged():
    assert prompt_pack.trim_lints(2.5, 6)[0]["code"] == "clip_heavily_trimmed"
    assert prompt_pack.trim_lints(4.5, 6) == []


def test_archetype_default_set_and_wardrobe_are_flagged_for_review():
    from pipeline.wardrobe import ENVIRONMENT_CATALOG, WARDROBE_CATALOG

    env = ENVIRONMENT_CATALOG["env_studio_infinity_cyclorama"]
    wear = WARDROBE_CATALOG["costume_executive_blazer"]
    codes = {l["code"] for l in prompt_pack.default_look_lints(f"x. {env.prompt_set_directive} {wear.prompt_wear_directive}")}
    assert codes == {"default_set", "default_wear"}
    assert prompt_pack.default_look_lints("SET: a narrow alley. WEAR: black tee.") == []


def test_product_reference_does_not_override_a_described_label():
    # QA preprod r3: the hero photo carried a third-party label the brief replaced with a blank one.
    from types import SimpleNamespace
    from pipeline.identity_keyframe import compose_synthesis_prompt

    prompt = compose_synthesis_prompt(SimpleNamespace(prompt_6part="A tote with a plain blank label."), ["product_hero"])
    assert "not any printed text or logo" in prompt and "follow the text" in prompt
