"""Stage 4 contract tests: agent-supplied references, preflight gate, strict isolation, watermark guard."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from pipeline import identity_keyframe as ik
from pipeline.archetypes import CharacterRole
from pipeline.briefing import create_product_brief
from pipeline.identity_keyframe import (
    IdentityReferenceError,
    generate_clean_keyframes,
    preflight_identity_assets,
    resolve_product_hero_reference,
)
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from tools.dramaclaw_shot_builder import clean_watermark_inpaint


def _img(path: Path, size=(400, 300), color=(120, 90, 60)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _plan(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path)
    return generate_scene_plan(script=script, output_dir=tmp_path)


def _run(tmp_path, plan, **kw):
    return generate_clean_keyframes(
        scene_plan=plan, output_dir=tmp_path, keyframes_dir=tmp_path / "keyframes", **kw
    )


class _FakeWorkspace:
    def __init__(self, root: Path):
        self.input_dir = root / "input"
        self.input_dir.mkdir(parents=True, exist_ok=True)


def test_product_hero_never_falls_back_to_character_portrait(tmp_path, monkeypatch):
    monkeypatch.setattr(ik, "BASE_DIR", tmp_path)  # no assets/products here
    with pytest.raises(IdentityReferenceError, match="product"):
        resolve_product_hero_reference(workspace=None)


def test_product_hero_prefers_named_input_over_alphabetical(tmp_path):
    ws = _FakeWorkspace(tmp_path)
    _img(ws.input_dir / "a_lifestyle.jpg")
    hero = _img(ws.input_dir / "z_product_hero.png")
    assert resolve_product_hero_reference(workspace=ws) == hero


def test_agent_supplied_references_are_used(tmp_path):
    plan = _plan(tmp_path)
    roles = [CharacterRole.PRESENTER, CharacterRole.MODEL, CharacterRole.PRODUCT_ONLY, CharacterRole.PRESENTER]
    for s, role in zip(plan.shots, roles):
        s.character_role = role
        s.generation_mode = None
    sheet = _img(tmp_path / "my" / "sheet.png", (2752, 1536))
    face = _img(tmp_path / "my" / "face.png", (1080, 1920))
    prod = _img(tmp_path / "my" / "prod.png", (1200, 1200))
    ff = _img(tmp_path / "my" / "ff_shot.png", (1080, 1920))
    overrides = {
        "character_sheet": str(sheet),
        "face_anchor": str(face),
        "product_hero": str(prod),
        "shots": {plan.shots[0].shot_id: {"first_frame": str(ff)}},
    }
    manifest = _run(tmp_path, plan, reference_overrides=overrides)
    kf = {k.shot_id: k for k in manifest.keyframes}
    assert kf[plan.shots[0].shot_id].image_path == str(ff)
    assert kf[plan.shots[1].shot_id].reference_assets == [str(sheet), str(face)]
    assert kf[plan.shots[2].shot_id].image_path == str(prod)
    assert kf[plan.shots[2].shot_id].generation_mode == "product_hero"


def test_overrides_file_in_artifacts_dir_is_discovered(tmp_path):
    plan = _plan(tmp_path)
    plan.shots[1].character_role = CharacterRole.PRODUCT_ONLY
    prod = _img(tmp_path / "p.png", (1200, 1200))
    (tmp_path / "reference_overrides.json").write_text(json.dumps({"product_hero": str(prod)}))
    manifest = _run(tmp_path, plan)
    hero = [k for k in manifest.keyframes if k.generation_mode == "product_hero"]
    assert hero and all(k.image_path == str(prod) for k in hero)


def test_missing_override_path_fails_loudly(tmp_path):
    plan = _plan(tmp_path)
    with pytest.raises(IdentityReferenceError, match="face_anchor"):
        _run(tmp_path, plan, reference_overrides={"face_anchor": str(tmp_path / "nope.png")})
    assert not (tmp_path / "asset_manifest.json").exists()


def test_presenter_first_frame_is_single_view_not_multi_panel_sheet(tmp_path):
    plan = _plan(tmp_path)
    for s in plan.shots:
        s.character_role = CharacterRole.PRESENTER
        s.generation_mode = None
        s.reference_expression = None
    manifest = _run(tmp_path, plan)
    for k in manifest.keyframes:
        assert "character_sheet" not in k.image_path
        assert k.generation_mode == "i2v"


def test_r2v_keeps_dual_anchor_references_but_clean_frame_is_single_view(tmp_path):
    plan = _plan(tmp_path)
    plan.shots[0].character_role = CharacterRole.MODEL
    manifest = _run(tmp_path, plan)
    k = manifest.keyframes[0]
    assert k.generation_mode == "r2v"
    assert any("character_sheet" in r for r in k.reference_assets)
    assert len(k.reference_assets) == 2
    assert "character_sheet" not in k.image_path


def test_preflight_missing_sheet_blocks_before_any_output(tmp_path):
    plan = _plan(tmp_path)
    plan.shots[0].character_role = CharacterRole.MODEL
    with pytest.raises(IdentityReferenceError, match="character_sheet"):
        _run(tmp_path, plan, reference_overrides={"character_sheet": str(tmp_path / "gone.png")})
    assert not list((tmp_path / "keyframes").glob("*.jpg"))


def test_preflight_report_flags_low_resolution(tmp_path):
    small = _img(tmp_path / "small.png", (300, 300))
    report = preflight_identity_assets({"character_sheet": small, "face_anchor": small})
    assert report["ok"] is True
    assert {w["asset"] for w in report["warnings"]} == {"character_sheet", "face_anchor"}
    with pytest.raises(IdentityReferenceError, match="resolution"):
        preflight_identity_assets({"character_sheet": small}, strict_resolution=True)


def test_preflight_report_written_to_artifacts(tmp_path):
    plan = _plan(tmp_path)
    _run(tmp_path, plan)
    report = json.loads((tmp_path / "identity_preflight.json").read_text())
    assert report["ok"] is True


def test_watermark_guard_leaves_bright_content_untouched(tmp_path):
    white = np.full((400, 400, 3), 250, dtype=np.uint8)  # white product on white background
    p = tmp_path / "white.png"
    cv2.imwrite(str(p), white)
    pixels = clean_watermark_inpaint(p, p)
    assert pixels == 0
    assert (cv2.imread(str(p)) == white).all()


def test_watermark_text_on_dark_is_inpainted(tmp_path):
    img = np.full((1000, 1000, 3), 40, dtype=np.uint8)
    cv2.putText(img, "WM", (700, 960), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 4)
    p = tmp_path / "wm.png"
    cv2.imwrite(str(p), img)
    pixels = clean_watermark_inpaint(p, p)
    assert pixels > 0
    out = cv2.imread(str(p))
    assert out[900:, 520:].max() < 120
