"""Honest R2V / fail-loud routing, resumable tasks, fingerprint cache and fail-fast batch (offline)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline import video_engine as ve
from pipeline.schemas import AssetManifestArtifact, KeyframeAsset, ScenePlanArtifact
from pipeline.video_engine import VideoGenerationError
from tests.test_helpers import create_test_clip
from tools.generate_video import VideoAPIError

PORTRAIT = Path("assets/characters/kol_main/portrait.png").resolve()


def _png(path: Path, color: str) -> Path:
    from PIL import Image

    Image.new("RGB", (400, 700), color).save(path)
    return path


def _poll_writes_clip(task_id: str, output_path: Path, timeout_seconds: int = 300):
    return create_test_clip(PORTRAIT, output_path, duration=1.0)


def _render(tmp_path: Path, **overrides):
    kwargs = dict(
        shot_id="shot_01",
        prompt="Model walks through a sunlit loft",
        output_path=tmp_path / "shot_01.mp4",
        image_path=PORTRAIT,
        duration=4.0,
        max_retries=3,
        initial_retry_delay=0.0,
    )
    kwargs.update(overrides)
    return ve.render_single_video_clip(**kwargs)


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("pipeline.video_engine.time.sleep"), patch("pipeline.video_engine.random.uniform", return_value=0.0):
        yield


# --- fail-loud first frame / honest R2V -------------------------------------------------


def test_missing_first_frame_fails_loudly_instead_of_degrading_to_t2v(tmp_path: Path):
    with patch("pipeline.video_engine.upload_first_frame") as up, \
         patch("pipeline.video_engine.submit_video_job") as sub:
        with pytest.raises(VideoGenerationError, match="First Frame"):
            _render(tmp_path, image_path=tmp_path / "does_not_exist.png")
    up.assert_not_called()
    sub.assert_not_called()


def test_r2v_sends_face_anchor_as_subject_reference_not_as_first_frame(tmp_path: Path):
    sheet = _png(tmp_path / "character_sheet.png", "white")
    face = _png(tmp_path / "face_anchor.png", "gray")
    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/face.png") as up, \
         patch("pipeline.video_engine.submit_video_job", return_value="t_r2v") as sub, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=_poll_writes_clip), \
         patch("pipeline.video_engine.telemetry.record_prompt") as rec:
        _render(tmp_path, image_path=sheet, generation_mode="r2v", reference_assets=[str(sheet), str(face)])

    up.assert_called_once()
    assert Path(up.call_args[0][0]) == face
    kwargs = sub.call_args.kwargs
    assert kwargs["subject_reference"] == ["https://cdn/face.png"]
    assert kwargs["image_url"] is None
    assert kwargs["model"] == ve.DEFAULT_R2V_MODEL
    modes = {c.kwargs.get("mode") for c in rec.call_args_list if c.kwargs.get("mode")}
    assert modes == {"R2V"}


def test_r2v_without_resolvable_face_anchor_raises_before_any_api_call(tmp_path: Path):
    sheet = _png(tmp_path / "character_sheet.png", "white")
    with patch("pipeline.video_engine.upload_first_frame") as up, patch("pipeline.video_engine.submit_video_job") as sub:
        with pytest.raises(VideoGenerationError, match="face anchor"):
            _render(
                tmp_path,
                image_path=sheet,
                generation_mode="r2v",
                reference_assets=[str(sheet), str(tmp_path / "missing_face.png")],
            )
    up.assert_not_called()
    sub.assert_not_called()


def test_r2v_face_anchor_i2v_strategy_is_recorded_as_degraded_i2v(tmp_path: Path):
    sheet = _png(tmp_path / "character_sheet.png", "white")
    face = _png(tmp_path / "face_anchor.png", "gray")
    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/face.png") as up, \
         patch("pipeline.video_engine.submit_video_job", return_value="t") as sub, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=_poll_writes_clip), \
         patch("pipeline.video_engine.telemetry.record_prompt") as rec:
        _render(
            tmp_path,
            image_path=sheet,
            generation_mode="r2v",
            reference_assets=[str(sheet), str(face)],
            r2v_strategy="face_anchor_i2v",
        )
    assert Path(up.call_args[0][0]) == face
    assert sub.call_args.kwargs["image_url"] == "https://cdn/face.png"
    assert "subject_reference" not in sub.call_args.kwargs
    first = next(c for c in rec.call_args_list if c.kwargs.get("mode"))
    assert first.kwargs["mode"] == "I2V"
    assert first.kwargs["degraded_from"] == "R2V"


# --- retry classification ---------------------------------------------------------------


def test_non_retryable_api_error_is_not_resubmitted(tmp_path: Path):
    err = VideoAPIError("MiniMax error 1026: sensitive", 1026)
    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/f.png"), \
         patch("pipeline.video_engine.submit_video_job", side_effect=err) as sub:
        with pytest.raises(VideoGenerationError, match="1026"):
            _render(tmp_path)
    assert sub.call_count == 1


def test_retryable_error_is_retried_then_succeeds(tmp_path: Path):
    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/f.png"), \
         patch("pipeline.video_engine.submit_video_job", side_effect=[VideoAPIError("rate", 1002), "t_ok"]) as sub, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=_poll_writes_clip):
        _render(tmp_path)
    assert sub.call_count == 2


# --- idempotent task resume -------------------------------------------------------------


def test_poll_timeout_resumes_same_task_instead_of_paying_twice(tmp_path: Path):
    calls = {"n": 0}

    def poll(task_id, output_path, timeout_seconds=300):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("still rendering")
        assert task_id == "t_slow"
        return _poll_writes_clip(task_id, output_path)

    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/f.png") as up, \
         patch("pipeline.video_engine.submit_video_job", return_value="t_slow") as sub, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=poll):
        out = _render(tmp_path)

    assert sub.call_count == 1 and up.call_count == 1
    assert Path(out).exists()
    # No dangling in-flight task once the clip is finished; provenance meta is written.
    assert not (tmp_path / "shot_01.task.json").exists()
    meta = json.loads((tmp_path / "shot_01.meta.json").read_text())
    assert meta["task_id"] == "t_slow" and meta["fingerprint"]


def test_rerun_after_crash_resumes_in_flight_task(tmp_path: Path):
    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/f.png"), \
         patch("pipeline.video_engine.submit_video_job", return_value="t_inflight"), \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=TimeoutError("slow")):
        with pytest.raises(VideoGenerationError):
            _render(tmp_path, max_retries=1)
    assert (tmp_path / "shot_01.task.json").exists()

    seen = []

    def poll(task_id, output_path, timeout_seconds=300):
        seen.append(task_id)
        return _poll_writes_clip(task_id, output_path)

    with patch("pipeline.video_engine.upload_first_frame") as up, \
         patch("pipeline.video_engine.submit_video_job") as sub, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=poll):
        _render(tmp_path, max_retries=1)
    assert seen == ["t_inflight"]
    up.assert_not_called()
    sub.assert_not_called()


def test_changed_prompt_does_not_resume_old_task(tmp_path: Path):
    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/f.png"), \
         patch("pipeline.video_engine.submit_video_job", return_value="t_old"), \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=TimeoutError("slow")):
        with pytest.raises(VideoGenerationError):
            _render(tmp_path, max_retries=1)

    seen = []

    def poll(task_id, output_path, timeout_seconds=300):
        seen.append(task_id)
        return _poll_writes_clip(task_id, output_path)

    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/f.png"), \
         patch("pipeline.video_engine.submit_video_job", return_value="t_new") as sub, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=poll):
        _render(tmp_path, prompt="A completely different directorial prompt", max_retries=1)
    sub.assert_called_once()
    assert seen == ["t_new"]


def test_failed_remote_task_is_resubmitted_not_resumed(tmp_path: Path):
    polls = []

    def poll(task_id, output_path, timeout_seconds=300):
        polls.append(task_id)
        if task_id == "t_dead":
            raise VideoAPIError("Video generation failed", None, task_failed=True)
        return _poll_writes_clip(task_id, output_path)

    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/f.png"), \
         patch("pipeline.video_engine.submit_video_job", side_effect=["t_dead", "t_fresh"]) as sub, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=poll):
        _render(tmp_path)
    assert polls == ["t_dead", "t_fresh"]
    assert sub.call_count == 2


# --- fingerprint cache ------------------------------------------------------------------


def test_clip_cache_status_distinguishes_hit_stale_legacy_and_miss(tmp_path: Path):
    clip = tmp_path / "c.mp4"
    assert ve.clip_cache_status(clip, "fp1") == "miss"
    create_test_clip(PORTRAIT, clip, duration=1.0)
    assert ve.clip_cache_status(clip, "fp1") == "legacy"  # pre-fingerprint clips stay usable
    (tmp_path / "c.meta.json").write_text(json.dumps({"fingerprint": "fp1"}))
    assert ve.clip_cache_status(clip, "fp1") == "hit"
    assert ve.clip_cache_status(clip, "fp2") == "stale"


def _plan(prompts: dict[str, str]) -> ScenePlanArtifact:
    return ScenePlanArtifact.model_validate(
        {
            "campaign_id": "c1",
            "shots": [
                {
                    "shot_id": sid,
                    "scene_id": sid,
                    "shot_type": "Medium",
                    "angle": "eye",
                    "camera_motion": "push in",
                    "lighting": "soft",
                    "style_constraints": "none",
                    "scene_description": "d",
                    "prompt_6part": prompt,
                    "estimated_duration": 4.0,
                }
                for sid, prompt in prompts.items()
            ],
        }
    )


def _manifest(shot_ids) -> AssetManifestArtifact:
    return AssetManifestArtifact(
        campaign_id="c1",
        keyframes=[KeyframeAsset(shot_id=s, cleaned_image_path=str(PORTRAIT), generation_mode="i2v") for s in shot_ids],
    )


def _batch(tmp_path: Path, prompts: dict[str, str], **kwargs):
    art = tmp_path / "artifacts"
    art.mkdir(exist_ok=True)
    with patch("pipeline.video_engine.score_slideshow_risk", return_value=MagicMock(passed=True, hard_reject_reasons=[])):
        return ve.render_all_video_clips(
            scene_plan=_plan(prompts),
            manifest=_manifest(prompts),
            artifacts_dir=art,
            raw_clips_dir=tmp_path / "clips",
            initial_retry_delay=0.0,
            **kwargs,
        )


def test_batch_reuses_current_clips_but_rerenders_when_prompt_changed(tmp_path: Path):
    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn/f.png"), \
         patch("pipeline.video_engine.submit_video_job", return_value="t1") as sub, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=_poll_writes_clip):
        _batch(tmp_path, {"shot_01": "prompt A", "shot_02": "prompt B"})
        assert sub.call_count == 2
        _batch(tmp_path, {"shot_01": "prompt A", "shot_02": "prompt B"})
        assert sub.call_count == 2  # fully cached, no new paid jobs
        _batch(tmp_path, {"shot_01": "prompt A", "shot_02": "prompt B EDITED"})
        assert sub.call_count == 3  # only the edited shot is re-rendered


def test_batch_fails_fast_and_does_not_submit_remaining_shots(tmp_path: Path):
    with patch("pipeline.video_engine.render_single_video_clip", side_effect=VideoGenerationError("boom")) as render:
        with pytest.raises(VideoGenerationError, match="shot_01"):
            _batch(tmp_path, {"shot_01": "a", "shot_02": "b", "shot_03": "c"}, max_concurrency=1)
    assert render.call_count == 1
