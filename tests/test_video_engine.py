"""Offline contract tests for the Stage-5 video engine (ComfyUI gateway provider)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.video_engine import (
    VideoGenerationError,
    render_single_video_clip,
    verify_generated_clip,
)
from tests.test_helpers import create_test_clip

PORTRAIT = Path("assets/characters/kol_main/portrait.png")


def _model_node(graph: dict) -> dict:
    for node in graph.values():
        if node["class_type"] in ("MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"):
            return node
    raise AssertionError("no MiniMax H3 node in the submitted graph")


def test_render_single_video_clip_i2v_mocked(tmp_path: Path):
    dst_clip = tmp_path / "shot_01.mp4"

    def mock_poll(prompt_id: str, output_path: Path, timeout_seconds: int = 600):
        return create_test_clip(PORTRAIT, output_path, duration=2.0)

    with patch("pipeline.video_engine.upload_image", return_value="frame.png") as mock_upload, \
         patch("pipeline.video_engine.submit_graph", return_value="prompt_123") as mock_submit, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=mock_poll) as mock_poll_fn:

        res = render_single_video_clip(
            shot_id="shot_01",
            prompt="A woman smiles and takes a sip from smart mug",
            output_path=dst_clip,
            image_path=PORTRAIT,
            duration=4.0,
            max_retries=2,
            initial_retry_delay=0.1,
        )

        assert dst_clip.exists()
        assert res == str(dst_clip)
        mock_upload.assert_called_once()
        mock_submit.assert_called_once()
        mock_poll_fn.assert_called_once()

        graph = mock_submit.call_args[0][0]
        model = _model_node(graph)
        assert model["class_type"] == "MiniMaxH3ImageToVideo"
        assert model["inputs"]["first_frame"]  # the keyframe is wired as the first frame
        assert model["inputs"]["width"] % 32 == 0 and model["inputs"]["height"] % 32 == 0


def test_render_single_video_clip_t2v_mocked(tmp_path: Path):
    dst_clip = tmp_path / "shot_02_t2v.mp4"

    def mock_poll(prompt_id: str, output_path: Path, timeout_seconds: int = 600):
        return create_test_clip(PORTRAIT, output_path, duration=2.0)

    with patch("pipeline.video_engine.upload_image") as mock_upload, \
         patch("pipeline.video_engine.submit_graph", return_value="prompt_t2v") as mock_submit, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=mock_poll):

        res = render_single_video_clip(
            shot_id="shot_02",
            prompt="Dramatic camera orbit around modern Nordic interior desk",
            output_path=dst_clip,
            image_path=None,  # Pure T2V
            duration=5.0,
            max_retries=1,
        )

        assert dst_clip.exists()
        mock_upload.assert_not_called()
        mock_submit.assert_called_once()
        model = _model_node(mock_submit.call_args[0][0])
        assert "first_frame" not in model["inputs"]
        assert "last_frame" not in model["inputs"]


def test_zero_tolerance_forbids_slideshow_fallback_on_failure(tmp_path: Path):
    dst_clip = tmp_path / "failed_shot.mp4"

    with patch("pipeline.video_engine.upload_image", return_value="frame.png"), \
         patch("pipeline.video_engine.submit_graph", side_effect=RuntimeError("Gateway 504 Timeout")):

        with pytest.raises(VideoGenerationError) as exc_info:
            render_single_video_clip(
                shot_id="shot_fail",
                prompt="Fast dynamic drone fly-through",
                output_path=dst_clip,
                image_path=PORTRAIT,
                duration=4.0,
                max_retries=2,
                initial_retry_delay=0.05,
            )

        assert "Zero-tolerance policy forbids static image slideshow fallback" in str(exc_info.value)
        assert not dst_clip.exists()


def test_verify_generated_clip_valid_and_invalid(tmp_path: Path):
    valid_clip = tmp_path / "valid.mp4"
    create_test_clip(PORTRAIT, valid_clip, duration=1.0)
    assert verify_generated_clip(valid_clip) is True

    empty_clip = tmp_path / "empty.mp4"
    empty_clip.touch()
    assert verify_generated_clip(empty_clip) is False

    missing_clip = tmp_path / "missing.mp4"
    assert verify_generated_clip(missing_clip) is False
