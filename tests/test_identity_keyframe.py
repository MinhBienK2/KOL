from pathlib import Path
import json
import cv2

from pipeline.briefing import create_product_brief
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from pipeline.identity_keyframe import generate_clean_keyframes, prepare_9_16_frame
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

    manifest = generate_clean_keyframes(
        scene_plan=plan,
        output_dir=tmp_path,
        keyframes_dir=tmp_path / "keyframes",
    )

    kf_map = {kf.shot_id: kf for kf in manifest.keyframes}
    for shot in plan.shots:
        kf = kf_map[shot.shot_id]
        if shot.character_role == CharacterRole.PRODUCT_ONLY or getattr(shot.character_role, "value", None) == "product_only":
            # Product isolation: no character face reference
            assert "portrait.png" not in kf.image_path
            assert "ref_10" not in kf.image_path
        else:
            # Character shot: bound to campaign wardrobe or canonical fashion identity reference
            assert any(k in kf.image_path for k in ("fashion_french_dress", "01_standing_front_0deg.jpg", "expressions"))
