from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from pipeline.video_engine import (
    VideoGenerationError,
    render_single_video_clip,
    verify_generated_clip,
)
from tests.test_helpers import create_test_clip


def test_render_single_video_clip_i2v_mocked(tmp_path: Path):
    src_img = Path("assets/characters/kol_main/portrait.png")
    dst_clip = tmp_path / "shot_01.mp4"

    def mock_poll(task_id: str, output_path: Path, timeout_seconds: int = 300):
        return create_test_clip(src_img, output_path, duration=2.0)

    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn.oss.mock/frame.png") as mock_upload, \
         patch("pipeline.video_engine.submit_video_job", return_value="task_mock_123") as mock_submit, \
         patch("pipeline.video_engine.poll_and_download_video", side_effect=mock_poll) as mock_poll_fn:

        res = render_single_video_clip(
            shot_id="shot_01",
            prompt="A woman smiles and takes a sip from smart mug",
            output_path=dst_clip,
            image_path=src_img,
            duration=4.0,
            max_retries=2,
            initial_retry_delay=0.1,
        )

        assert dst_clip.exists()
        assert res == str(dst_clip)
        mock_upload.assert_called_once()
        mock_submit.assert_called_once_with(
            prompt="A woman smiles and takes a sip from smart mug",
            image_url="https://cdn.oss.mock/frame.png",
            aspect_ratio="9:16",
            duration=6,
            model="MiniMax-Hailuo-2.3",
        )
        mock_poll_fn.assert_called_once()


def test_render_single_video_clip_t2v_mocked(tmp_path: Path):
    src_img = Path("assets/characters/kol_main/portrait.png")
    dst_clip = tmp_path / "shot_02_t2v.mp4"

    def mock_poll(task_id: str, output_path: Path, timeout_seconds: int = 300):
        return create_test_clip(src_img, output_path, duration=2.0)

    with patch("pipeline.video_engine.upload_first_frame") as mock_upload, \
         patch("pipeline.video_engine.submit_video_job", return_value="task_t2v_456") as mock_submit, \
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
        mock_submit.assert_called_once_with(
            prompt="Dramatic camera orbit around modern Nordic interior desk",
            image_url=None,
            aspect_ratio="9:16",
            duration=6,
            model="MiniMax-Hailuo-2.3",
        )


def test_zero_tolerance_forbids_slideshow_fallback_on_failure(tmp_path: Path):
    dst_clip = tmp_path / "failed_shot.mp4"

    with patch("pipeline.video_engine.upload_first_frame", return_value="https://cdn.oss.mock/frame.png"), \
         patch("pipeline.video_engine.submit_video_job", side_effect=RuntimeError("API Gateway 504 Timeout")):

        with pytest.raises(VideoGenerationError) as exc_info:
            render_single_video_clip(
                shot_id="shot_fail",
                prompt="Fast dynamic drone fly-through",
                output_path=dst_clip,
                image_path=Path("assets/characters/kol_main/portrait.png"),
                duration=4.0,
                max_retries=2,
                initial_retry_delay=0.05,
            )

        assert "Zero-tolerance policy forbids static image slideshow fallback" in str(exc_info.value)
        assert not dst_clip.exists()


def test_verify_generated_clip_valid_and_invalid(tmp_path: Path):
    src_img = Path("assets/characters/kol_main/portrait.png")
    valid_clip = tmp_path / "valid.mp4"
    create_test_clip(src_img, valid_clip, duration=1.0)
    assert verify_generated_clip(valid_clip) is True

    # Empty file
    empty_clip = tmp_path / "empty.mp4"
    empty_clip.touch()
    assert verify_generated_clip(empty_clip) is False

    # Missing file
    missing_clip = tmp_path / "missing.mp4"
    assert verify_generated_clip(missing_clip) is False
