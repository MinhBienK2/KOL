"""Face Identity Gate (ADR 0004): SFace similarity of generated faces against the Face Anchor.

Core logic is tested with mocked embeddings; calibration tests use the real YuNet/SFace models and
skip when they are not cached (they are never downloaded by the test-suite).
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline import face_identity, offline
from pipeline.config import BASE_DIR
from pipeline.verification import FACE_ROLES, verify_face_identity_gate

needs_models = pytest.mark.skipif(not face_identity.models_available(), reason="YuNet/SFace models not cached")

MAIN = BASE_DIR / "assets/characters/kol_main"
OTHER_PERSONA = BASE_DIR / "tests/fixtures/different_face.png"


# ---------------------------------------------------------------- mocked-embedding unit tests


def _write_image(path: Path, value: int = 128) -> Path:
    cv2.imwrite(str(path), np.full((64, 64, 3), value, dtype=np.uint8))
    return path


def test_cosine_similarity_basics():
    a = np.array([[1.0, 0.0]])
    assert face_identity.cosine_similarity(a, a) == pytest.approx(1.0)
    assert face_identity.cosine_similarity(a, np.array([[0.0, 1.0]])) == pytest.approx(0.0)
    assert face_identity.cosine_similarity(a, np.zeros((1, 2))) == 0.0


def test_verify_shot_identity_image_pass_and_fail(tmp_path, monkeypatch):
    img = _write_image(tmp_path / "kf.png")
    monkeypatch.setattr(face_identity, "embed_face", lambda frame: np.array([[0.8, 0.6]]))
    ok = face_identity.verify_shot_identity(np.array([[1.0, 0.0]]), img)
    assert ok["face_found"] and ok["passed"] and ok["similarity"] == pytest.approx(0.8)
    low = face_identity.verify_shot_identity(np.array([[1.0, 0.0]]), img, threshold=0.9)
    assert low["face_found"] and not low["passed"]


def test_verify_shot_identity_no_face(tmp_path, monkeypatch):
    img = _write_image(tmp_path / "kf.png")
    monkeypatch.setattr(face_identity, "embed_face", lambda frame: None)
    res = face_identity.verify_shot_identity(np.array([[1.0, 0.0]]), img)
    assert res == {**res, "similarity": None, "face_found": False, "passed": False}


def test_verify_shot_identity_video_takes_best_frame(tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    for i in range(20):
        writer.write(np.full((64, 64, 3), i * 10, dtype=np.uint8))
    writer.release()
    frames = face_identity.sample_video_frames(video, 3)
    assert len(frames) == 3

    scores = iter([None, np.array([[0.0, 1.0]]), np.array([[1.0, 0.0]])])  # no face, off-identity, on-identity
    monkeypatch.setattr(face_identity, "embed_face", lambda frame: next(scores))
    res = face_identity.verify_shot_identity(np.array([[1.0, 0.0]]), video, n_frames=3)
    assert res["frames_checked"] == 3 and res["frames_with_face"] == 2
    assert res["similarity"] == pytest.approx(1.0) and res["passed"]


def test_sample_video_frames_bad_file(tmp_path):
    assert face_identity.sample_video_frames(tmp_path / "missing.mp4", 3) == []


def test_threshold_env_override(monkeypatch):
    assert face_identity.face_similarity_threshold() == face_identity.DEFAULT_FACE_SIMILARITY_THRESHOLD
    monkeypatch.setenv("KOL_FACE_SIMILARITY_THRESHOLD", "0.5")
    assert face_identity.face_similarity_threshold() == 0.5
    monkeypatch.setenv("KOL_FACE_SIMILARITY_THRESHOLD", "bogus")
    assert face_identity.face_similarity_threshold() == face_identity.DEFAULT_FACE_SIMILARITY_THRESHOLD


# ---------------------------------------------------------------- model download guard


def test_ensure_model_offline_missing_is_unavailable(tmp_path):
    with offline.offline_mode(True), pytest.raises(face_identity.FaceModelsUnavailable):
        face_identity.ensure_model(face_identity.DETECTOR_MODEL, tmp_path)


def test_ensure_model_rejects_corrupt_download(tmp_path, monkeypatch):
    def fake_retrieve(url, filename, **kwargs):  # e.g. a Git LFS pointer instead of the weights
        Path(filename).write_text("version https://git-lfs.github.com/spec/v1\n")

    monkeypatch.setattr(offline, "guarded_urlretrieve", fake_retrieve)
    with pytest.raises(face_identity.FaceModelsUnavailable, match="SHA-256"):
        face_identity.ensure_model(face_identity.DETECTOR_MODEL, tmp_path)
    assert not (tmp_path / face_identity.DETECTOR_MODEL.filename).exists()


# ---------------------------------------------------------------- gate logic with mocked identity


@pytest.fixture
def gate_files(tmp_path):
    kf = {name: _write_image(tmp_path / f"{name}.png") for name in ("s1", "s2", "s3")}
    clip = tmp_path / "raw_shot_01.mp4"
    clip.write_bytes(b"x")  # presence only; the identity call is mocked
    plan = {
        "campaign_id": "c",
        "shots": [
            {"shot_id": "shot_01", "character_role": "presenter"},
            {"shot_id": "shot_02", "character_role": "product_only"},
            {"shot_id": "shot_03", "character_role": "model"},
        ],
    }
    manifest = {
        "campaign_id": "c",
        "keyframes": [
            {"shot_id": "shot_01", "cleaned_image_path": str(kf["s1"])},
            {"shot_id": "shot_02", "cleaned_image_path": str(kf["s2"])},
            {"shot_id": "shot_03", "cleaned_image_path": str(kf["s3"])},
        ],
        "raw_video_clips": [str(clip)],
    }
    plan_p, manifest_p = tmp_path / "scene_plan.json", tmp_path / "asset_manifest.json"
    plan_p.write_text(json.dumps(plan))
    manifest_p.write_text(json.dumps(manifest))
    return plan_p, manifest_p


def _mock_identity(monkeypatch, results):
    """``results``: {(media file stem prefix): result dict}; records every compared media path."""
    seen = []
    monkeypatch.setattr(face_identity, "embed_face", lambda frame: np.array([[1.0, 0.0]]))

    def fake(anchor, media, **kwargs):
        seen.append(Path(media).name)
        for key, res in results.items():
            if key in Path(media).name:
                return {"threshold": 0.363, "frames_checked": 1, "frames_with_face": int(res["face_found"]), **res}
        raise AssertionError(f"unexpected media {media}")

    monkeypatch.setattr(face_identity, "verify_shot_identity", fake)
    return seen


GOOD = {"similarity": 0.6, "face_found": True, "passed": True}
BAD = {"similarity": 0.1, "face_found": True, "passed": False}
NONE = {"similarity": None, "face_found": False, "passed": False}


def test_gate_passes_and_skips_product_only(gate_files, monkeypatch):
    plan, manifest = gate_files
    seen = _mock_identity(monkeypatch, {"s1": GOOD, "s3": GOOD, "raw_shot_01": GOOD})
    gate = verify_face_identity_gate(plan, manifest)
    assert gate.passed, gate.error_message
    assert gate.details["status"] == "verified"
    statuses = {s["shot_id"]: s["status"] for s in gate.details["shots"]}
    assert statuses == {"shot_01": "passed", "shot_02": "skipped", "shot_03": "passed"}
    assert "s2.png" not in seen  # Product Isolation: the product_only keyframe is never face-checked
    assert set(gate.details["shots"][0]["checks"]) == {"keyframe", "clip"}
    assert "product_only" not in FACE_ROLES


def test_gate_fails_on_low_similarity_clip_even_if_keyframe_ok(gate_files, monkeypatch):
    plan, manifest = gate_files
    _mock_identity(monkeypatch, {"s1": GOOD, "s3": GOOD, "raw_shot_01": BAD})
    gate = verify_face_identity_gate(plan, manifest)
    assert not gate.passed
    assert "shot_01 clip" in gate.error_message and "0.100" in gate.error_message
    assert gate.details["shots_failed"] == 1 and gate.details["status"] == "failed"


def test_gate_presenter_without_face_fails_but_model_without_face_is_allowed(gate_files, monkeypatch):
    plan, manifest = gate_files
    _mock_identity(monkeypatch, {"s1": NONE, "s3": NONE, "raw_shot_01": GOOD})
    gate = verify_face_identity_gate(plan, manifest)
    assert not gate.passed
    assert "shot_01 keyframe: no face found" in gate.error_message
    assert "shot_03" not in gate.error_message
    assert {s["shot_id"]: s["status"] for s in gate.details["shots"]}["shot_03"] == "passed"


def test_gate_model_with_wrong_face_fails(gate_files, monkeypatch):
    plan, manifest = gate_files
    _mock_identity(monkeypatch, {"s1": GOOD, "s3": BAD, "raw_shot_01": GOOD})
    gate = verify_face_identity_gate(plan, manifest)
    assert not gate.passed and "shot_03 keyframe" in gate.error_message


def test_gate_unverified_when_inputs_missing(tmp_path):
    gate = verify_face_identity_gate(tmp_path / "nope.json", tmp_path / "nope2.json")
    assert gate.passed and gate.details["status"] == "unverified"


def test_gate_unverified_offline_without_models(gate_files, tmp_path, monkeypatch):
    plan, manifest = gate_files
    monkeypatch.setenv("KOL_MODEL_DIR", str(tmp_path / "empty_models"))
    with offline.offline_mode(True):
        gate = verify_face_identity_gate(plan, manifest)
    assert gate.passed is True
    assert gate.details["status"] == "unverified"
    assert "unavailable" in gate.details["reason"]


# ---------------------------------------------------------------- real-model calibration


@needs_models
def test_calibration_same_image_is_near_one():
    sim = face_identity.identity_similarity(MAIN / "portrait.png", MAIN / "portrait.png")
    assert sim == pytest.approx(1.0, abs=1e-3)


@needs_models
def test_calibration_same_persona_above_and_other_persona_below_threshold():
    threshold = face_identity.DEFAULT_FACE_SIMILARITY_THRESHOLD
    same = face_identity.identity_similarity(MAIN / "portrait.png", MAIN / "outfits/studio_chic_black/character_sheet.png")
    other = face_identity.identity_similarity(MAIN / "portrait.png", OTHER_PERSONA)
    assert same is not None and other is not None
    assert same >= threshold, f"same persona scored {same:.3f}"
    assert other < threshold, f"different persona scored {other:.3f}"
    assert same > other + 0.2


@needs_models
def test_gate_real_models_pass_same_persona_and_fail_other(tmp_path):
    """End to end on real faces: a persona's own keyframe passes, another persona's keyframe fails."""
    def run(keyframe: Path):
        plan = tmp_path / "scene_plan.json"
        manifest = tmp_path / "asset_manifest.json"
        plan.write_text(json.dumps({"campaign_id": "c", "shots": [{"shot_id": "shot_01", "character_role": "presenter"}]}))
        manifest.write_text(
            json.dumps({"campaign_id": "c", "keyframes": [{"shot_id": "shot_01", "cleaned_image_path": str(keyframe)}]})
        )
        return verify_face_identity_gate(plan, manifest, character_file=MAIN / "character.json")

    assert run(MAIN / "outfits/studio_chic_black/character_sheet.png").passed
    wrong = run(OTHER_PERSONA)
    assert not wrong.passed and "below threshold" in wrong.error_message


@needs_models
def test_real_video_frames_match_anchor(tmp_path):
    img = cv2.imread(str(MAIN / "portrait.png"))
    img = cv2.resize(img, (480, 848))
    video = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (480, 848))
    for _ in range(20):
        writer.write(img)
    writer.release()
    res = face_identity.verify_shot_identity(MAIN / "portrait.png", video, n_frames=3)
    assert res["passed"] and res["frames_with_face"] >= 1
