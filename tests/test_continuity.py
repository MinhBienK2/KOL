import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline.continuity import bible as bible_mod
from pipeline.continuity import chain

BASE_DIR = Path(__file__).resolve().parent.parent
BIBLE = BASE_DIR / "tests" / "fixtures" / "continuity" / "sample_bible" / "shot_bible.json"


def _bible(**shot_overrides):
    data = json.loads(BIBLE.read_text(encoding="utf-8"))
    data["shots"][1].update(shot_overrides)
    return bible_mod.ShotBible.model_validate(data)


def test_reference_bible_lints_clean():
    res = bible_mod.lint_bible(bible_mod.load_bible(BIBLE), BASE_DIR)
    assert res["ok"], res["errors"]


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"motion_prompt": "She rides away. [Static shot] [Push in]"}, "exactly one [Camera]"),
        ({"motion_prompt": "She rides away."}, "exactly one [Camera]"),
        ({"motion_prompt": "She rides away with her almond eyes shining. [Static shot]"}, "re-describes appearance"),
        ({"motion_prompt": "She rides away, 8k. [Static shot]"}, "banned token"),
        ({"vo_text": "Một câu thoại rất dài " * 6}, "shorten vo_text"),
        ({"handoff": "anchor", "keyframe_prompt": None}, "needs keyframe_prompt"),
    ],
)
def test_lint_catches_script_render_mismatches(override, fragment):
    res = bible_mod.lint_bible(_bible(**override), BASE_DIR)
    assert not res["ok"]
    assert any(fragment in e for e in res["errors"]), res["errors"]


def test_first_shot_must_be_anchor():
    data = json.loads(BIBLE.read_text(encoding="utf-8"))
    data["shots"][0]["handoff"] = "chain"
    res = bible_mod.lint_bible(bible_mod.ShotBible.model_validate(data), BASE_DIR)
    assert any("must be an anchor" in e for e in res["errors"])


def test_duration_must_be_hailuo_length():
    with pytest.raises(ValueError):
        _bible(duration=5)


def _clip(path: Path, blur_tail_except: int) -> Path:
    rng = np.random.default_rng(0)
    pattern = (rng.random((96, 64, 3)) * 255).astype(np.uint8)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 24, (64, 96))
    for i in range(30):
        frame = pattern.copy() if i == blur_tail_except else cv2.GaussianBlur(pattern, (9, 9), 4)
        writer.write(frame)
    writer.release()
    return path


def test_pick_handoff_takes_sharpest_tail_frame_not_the_last(tmp_path):
    clip = _clip(tmp_path / "c.mp4", blur_tail_except=25)
    res = chain.pick_handoff(clip, tmp_path / "h.png")
    assert res["frame_index"] == 25
    assert (tmp_path / "h.png").exists()


def test_seam_similarity_is_high_for_identical_frames(tmp_path):
    clip = _clip(tmp_path / "c.mp4", blur_tail_except=-1)
    frames = chain.read_frames(clip, chain.CHAIN_HEAD_DROP_FRAMES, chain.CHAIN_HEAD_DROP_FRAMES + 1)
    cv2.imwrite(str(tmp_path / "h.png"), frames[0])
    assert chain.seam_similarity(tmp_path / "h.png", clip) > 0.95


def test_end_frame_checklist_judges_contradictions_not_hidden_parts():
    from pipeline.continuity import judge
    b = _bible()
    keyframe = judge.checklist(b, b.shots[0], frame_role="keyframe")
    end = judge.checklist(b, b.shots[1], frame_role="end")
    assert sum("Product visible and matches" in i for i in keyframe) == len(b.product.must_show)
    assert not any("Product visible and matches" in i for i in end)
    assert any("hidden by distance" in i for i in end)
    assert end[-1].startswith("End state reached")


def test_lint_rejects_chaining_from_a_faceless_end_state():
    b = _bible(end_state="Riding away, mid-distance down the street, back to camera.")
    res = bible_mod.lint_bible(b, BASE_DIR)
    assert any("no readable face" in e for e in res["errors"])


def test_render_one_stops_on_an_unapproved_clip(tmp_path, monkeypatch):
    b = _bible()
    work = tmp_path
    kf = tmp_path / "kf.png"
    cv2.imwrite(str(kf), np.zeros((32, 18, 3), np.uint8))
    state = {"shots": {"shot_01": {"approved": False, "first_frame": str(kf), "clip": "c.mp4",
                                   "handoff": {"path": str(kf)}, "handoff_kind": "anchor", "attempts": []}}}
    (work / "chain_state.json").write_text(json.dumps(state))
    monkeypatch.setattr(chain.media, "render_i2v", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not render")))
    res = chain.render_chain(b, work, anchor_frames={"shot_01": str(kf)}, one=True)
    assert res["blocked_on"] == "shot_01"
    assert res["remaining"] == [s.shot_id for s in b.shots]


def test_printed_text_check_catches_melted_lettering():
    known = ["THONGNHAT", "KENDA"]
    assert chain.printed_text_check('lettering that reads "SSHMNAT."', known)["ok"] is False
    assert chain.printed_text_check('the down tube reads "THONGNHAT" and tyres say "KENDA"', known)["ok"] is True
    assert chain.printed_text_check('partly hidden lettering "NHAT"', known)["ok"] is True
    assert chain.printed_text_check("a red bicycle with white lettering", known)["ok"] is None


def test_approve_clip_refuses_hard_failures(tmp_path):
    record = {"clip": "c/shot_02_a1.mp4", "identity": {"similarity": 0.23}, "printed_text": {"ok": True}}
    state = {"shots": {"shot_02": {"clip": "c/shot_02_a1.mp4", "attempts": [record]}}}
    (tmp_path / "chain_state.json").write_text(json.dumps(state))
    with pytest.raises(ValueError, match="another person"):
        chain.approve_clip(tmp_path, "shot_02", "shot_02_a1.mp4", "looks fine to me", ["shot_01", "shot_02"])


def test_approve_clip_keeps_unrendered_shots_remaining(tmp_path):
    record = {"clip": "c/shot_01_a1.mp4", "identity": {"similarity": 0.7}, "printed_text": {"ok": True}}
    state = {"shots": {"shot_01": {"clip": "c/shot_01_a1.mp4", "attempts": [record]}}}
    (tmp_path / "chain_state.json").write_text(json.dumps(state))
    chain.approve_clip(tmp_path, "shot_01", "shot_01_a1.mp4", "ok", ["shot_01", "shot_02"])
    saved = json.loads((tmp_path / "chain_state.json").read_text())
    assert saved["remaining"] == ["shot_02"] and saved["approved"] is False


def test_lint_limits_chained_hops_and_checks_keyframe_from():
    data = json.loads(BIBLE.read_text(encoding="utf-8"))
    data["shots"][3].update({"handoff": "chain", "keyframe_from": None})
    res = bible_mod.lint_bible(bible_mod.ShotBible.model_validate(data), BASE_DIR)
    assert any("consecutive chained hops" in e for e in res["errors"])
    data["shots"][3].update({"handoff": "anchor", "keyframe_from": "shot_03"})
    res = bible_mod.lint_bible(bible_mod.ShotBible.model_validate(data), BASE_DIR)
    assert any("keyframe_from must name an earlier anchor" in e for e in res["errors"])


def test_face_yaw_separates_frontal_from_turned():
    from pipeline import face_identity
    frontal = np.array([0, 0, 0, 0, 40, 50, 60, 50, 50, 60, 0, 0, 0, 0, 0], dtype=np.float32)
    turned = frontal.copy()
    turned[8] = 62  # nose shifted toward one eye
    assert face_identity.face_yaw(frontal) == 0.0
    assert face_identity.face_yaw(turned) > chain.FRONTAL_MAX_YAW


def test_identity_consistency_scores_frontal_faces_only(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 24, (64, 64))
    for _ in range(48):
        writer.write(np.zeros((64, 64, 3), np.uint8))
    writer.release()
    same, other = np.ones(4), np.array([1.0, -1.0, 1.0, -1.0])
    faces = iter([(same, 0.0), (same, 0.0), (other, 0.9), (same, 0.05)])  # anchor, then 3 frames
    monkeypatch.setattr(chain.face_identity, "read_image", lambda p: np.zeros((8, 8, 3), np.uint8))
    monkeypatch.setattr(chain.face_identity, "embed_face_with_yaw", lambda img: next(faces, None))
    res = chain.identity_consistency(tmp_path / "anchor.png", video)
    assert res["turned_frames"] == 1 and res["frontal_frames"] == 2
    assert res["passed"] is True and res["similarity"] == 1.0
