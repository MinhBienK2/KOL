from pathlib import Path
import json
import cv2
import pytest
from PIL import Image

from pipeline.briefing import create_product_brief
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from pipeline.identity_keyframe import IdentityReferenceError, generate_clean_keyframes, prepare_9_16_frame
from pipeline.schemas import AssetManifestArtifact


def test_prepare_9_16_frame(tmp_path: Path):
    src = Path("assets/characters/kol_main/portrait.png")
    dst = tmp_path / "test_frame.png"
    w, h = prepare_9_16_frame(src, dst, target_width=540, target_height=960)

    assert dst.exists()
    assert w == 540
    assert h == 960
    img = cv2.imread(str(dst))
    assert img.shape[:2] == (960, 540)


def test_generate_clean_keyframes(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path)
    plan = generate_scene_plan(script=script, output_dir=tmp_path)
    manifest = generate_clean_keyframes(
        scene_plan=plan,
        output_dir=tmp_path,
        keyframes_dir=tmp_path / "keyframes",
    )

    assert manifest.campaign_id == plan.campaign_id
    assert len(manifest.keyframes) == 4
    for kf in manifest.keyframes:
        assert kf.watermark_removed is True
        assert Path(kf.cleaned_image_path).exists()
        assert kf.width == 1080
        assert kf.height == 1920

    out_file = tmp_path / "asset_manifest.json"
    assert out_file.exists()
    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    loaded = AssetManifestArtifact.model_validate(data)
    assert len(loaded.keyframes) == 4


def test_product_isolation_and_wardrobe_consistency(tmp_path: Path):
    from pipeline.archetypes import CharacterRole, ProductArchetype

    brief = create_product_brief(
        campaign_id="campaign_fashion_test",
        product_name="Áo Khoác Blazer Nữ",
        archetype=ProductArchetype.FASHION_APPAREL,
        output_dir=tmp_path,
    )
    script = generate_commercial_script(brief=brief, output_dir=tmp_path)
    plan = generate_scene_plan(script=script, output_dir=tmp_path)
    product = tmp_path / "product_hero.jpg"
    Image.new("RGB", (1200, 1200), (200, 180, 160)).save(product)

    manifest = generate_clean_keyframes(
        scene_plan=plan,
        output_dir=tmp_path,
        keyframes_dir=tmp_path / "keyframes",
        reference_overrides={"product_hero": str(product)},
    )

    character = json.loads(Path("assets/characters/kol_main/character.json").read_text(encoding="utf-8"))
    face_anchor_name = Path(character["face_anchor"]).name

    kf_map = {kf.shot_id: kf for kf in manifest.keyframes}
    for shot in plan.shots:
        kf = kf_map[shot.shot_id]
        if shot.character_role == CharacterRole.PRODUCT_ONLY or getattr(shot.character_role, "value", None) == "product_only":
            # Product isolation: no character face reference
            assert face_anchor_name not in kf.image_path
            assert "ref_10" not in kf.image_path
        else:
            # Character shot: framed from the face anchor; the outfit sheet is a reference, never the frame
            assert face_anchor_name in kf.image_path
            assert kf.generation_mode in ("i2v", "r2v")
            assert kf.reference_assets is not None


def _fashion_plan(tmp_path: Path):
    from pipeline.archetypes import ProductArchetype

    brief = create_product_brief(
        campaign_id="campaign_synth", product_name="Áo Khoác Blazer Nữ",
        archetype=ProductArchetype.FASHION_APPAREL, output_dir=tmp_path,
    )
    script = generate_commercial_script(brief=brief, output_dir=tmp_path)
    plan = generate_scene_plan(script=script, output_dir=tmp_path)
    product = tmp_path / "product_hero.jpg"
    Image.new("RGB", (1200, 1200), (200, 180, 160)).save(product)
    return plan, product


def test_synthesized_first_frames_follow_the_scene_prompt(tmp_path: Path, monkeypatch):
    # QA r1: Stage 4 only padded face_anchor/product_hero into 9:16, so every presenter shot was
    # the same studio portrait and every product shot the same catalogue photo.
    from pipeline import identity_keyframe
    from pipeline.archetypes import CharacterRole

    calls = []

    def fake_synth(prompt, out_path, reference_paths):
        calls.append((prompt, [Path(p).name for p in reference_paths]))
        Image.new("RGB", (1080, 1920), (90, 60, 30)).save(out_path)
        return out_path

    monkeypatch.setattr(identity_keyframe, "synthesize_first_frame", fake_synth)
    plan, product = _fashion_plan(tmp_path)
    manifest = generate_clean_keyframes(
        scene_plan=plan, output_dir=tmp_path, keyframes_dir=tmp_path / "keyframes",
        reference_overrides={"product_hero": str(product)}, synthesize_frames=True,
    )
    assert len(calls) == len(plan.shots)
    kf_map = {kf.shot_id: kf for kf in manifest.keyframes}
    for shot, (prompt, refs) in zip(plan.shots, calls):
        kf = kf_map[shot.shot_id]
        assert kf.keyframe_source == "synthesized"
        assert shot.prompt_6part in prompt and "No text" in prompt
        if kf.generation_mode != "r2v":  # i2v starts from the synthesized frame, not the reference
            assert kf.reference_assets[0].endswith(f"{shot.shot_id}_synth.png")
        if shot.character_role == CharacterRole.PRODUCT_ONLY:
            assert refs == ["product_hero.jpg"]  # product isolation holds for synthesis too
        else:
            assert refs[0] == Path(json.loads(Path("assets/characters/kol_main/character.json").read_text())["face_anchor"]).name
            assert "product_hero.jpg" in refs


def test_failed_synthesis_stops_stage_4_without_padding_a_reference(tmp_path: Path, monkeypatch):
    from pipeline import identity_keyframe

    def boom(prompt, out_path, reference_paths):
        raise RuntimeError("Failed to obtain reCAPTCHA token")

    monkeypatch.setattr(identity_keyframe, "synthesize_first_frame", boom)
    plan, product = _fashion_plan(tmp_path)
    with pytest.raises(identity_keyframe.FirstFrameSynthesisError, match="reCAPTCHA"):
        generate_clean_keyframes(
            scene_plan=plan, output_dir=tmp_path, keyframes_dir=tmp_path / "keyframes",
            reference_overrides={"product_hero": str(product)}, synthesize_frames=True,
        )
    assert not (tmp_path / "asset_manifest.json").exists()
    assert not list((tmp_path / "keyframes").glob("*_clean.jpg"))


def test_per_shot_synthesis_references(tmp_path: Path, monkeypatch):
    from pipeline import identity_keyframe

    seen = {}

    def fake_synth(prompt, out_path, reference_paths):
        seen[out_path.name] = [Path(p).name for p in reference_paths]
        Image.new("RGB", (1080, 1920), (1, 2, 3)).save(out_path)
        return out_path

    monkeypatch.setattr(identity_keyframe, "synthesize_first_frame", fake_synth)
    plan, product = _fashion_plan(tmp_path)
    face = Path("assets/characters/kol_main/face_anchor.png").resolve()
    first, second = plan.shots[0].shot_id, plan.shots[1].shot_id
    manifest = generate_clean_keyframes(
        scene_plan=plan, output_dir=tmp_path, keyframes_dir=tmp_path / "keyframes",
        reference_overrides={
            "product_hero": str(product),
            "shots": {first: {"synthesis_references": [str(face)]}},
        },
        synthesize_frames=True,
    )
    kf_map = {kf.shot_id: kf for kf in manifest.keyframes}
    assert seen[f"{first}_synth.png"] == ["face_anchor.png"]
    assert kf_map[second].keyframe_source == "synthesized"


def test_per_shot_synthesis_opt_out_is_rejected(tmp_path: Path):
    plan, product = _fashion_plan(tmp_path)
    with pytest.raises(IdentityReferenceError, match="first_frame"):
        generate_clean_keyframes(
            scene_plan=plan, output_dir=tmp_path, keyframes_dir=tmp_path / "keyframes",
            reference_overrides={"product_hero": str(product), "shots": {plan.shots[1].shot_id: {"synthesize": False}}},
            synthesize_frames=True,
        )


def test_director_synthesizes_keyframes_only_for_real_video():
    from pipeline.director import _synthesize_keyframes
    from pipeline.offline import offline_mode

    assert _synthesize_keyframes("auto", "api") is True
    assert _synthesize_keyframes("auto", "ffmpeg") is False
    with offline_mode(True):
        assert _synthesize_keyframes("auto", "api") is False
    with pytest.raises(ValueError):
        _synthesize_keyframes("reference", "api")
    assert _synthesize_keyframes("synth", "ffmpeg") is True
