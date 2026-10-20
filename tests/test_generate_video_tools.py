"""Offline contract tests for tools/generate_video.py (MiniMax submit/poll/download)."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools import generate_video as gv


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _json_resp(payload: dict) -> _Resp:
    return _Resp(json.dumps(payload).encode("utf-8"))


def _captured_payload(urlopen_mock: MagicMock) -> dict:
    req = urlopen_mock.call_args[0][0]
    return json.loads(req.data.decode("utf-8"))


# --- duration / resolution contract -------------------------------------------------


@pytest.mark.parametrize(
    "duration,resolution,expected",
    [(4, None, 6), (6, None, 6), (8.4, None, 6), (8.5, None, 10), (10, "768P", 10), (10, "1080P", 6), (12, "1080p", 6)],
)
def test_normalize_duration_respects_hailuo_resolution_matrix(duration, resolution, expected):
    assert gv.normalize_duration(duration, resolution) == expected


# --- submit -------------------------------------------------------------------------


def test_submit_sends_subject_reference_and_resolution():
    with patch("urllib.request.urlopen", return_value=_json_resp({"task_id": "t1", "base_resp": {"status_code": 0}})) as m:
        task_id = gv.submit_video_job(
            prompt="p",
            image_url=None,
            subject_reference=["https://cdn/face.png"],
            resolution="1080P",
            duration=10,
            model="S2V-01",
        )
    assert task_id == "t1"
    payload = _captured_payload(m)
    assert payload["subject_reference"] == [{"type": "character", "image": ["https://cdn/face.png"]}]
    assert payload["resolution"] == "1080P"
    assert payload["duration"] == 6  # 10s is not allowed at 1080P
    assert "input_image" not in payload


def test_submit_omits_optional_fields_by_default():
    with patch("urllib.request.urlopen", return_value=_json_resp({"task_id": "t2"})) as m:
        gv.submit_video_job(prompt="p", image_url="https://cdn/f.png")
    payload = _captured_payload(m)
    assert "subject_reference" not in payload and "resolution" not in payload
    assert payload["input_image"] == "https://cdn/f.png"


@pytest.mark.parametrize("code,retryable", [(1026, False), (1008, False), (1004, False), (2013, False), (1002, True)])
def test_submit_raises_typed_error_on_base_resp_failure(code, retryable):
    body = {"base_resp": {"status_code": code, "status_msg": "nope"}}
    with patch("urllib.request.urlopen", return_value=_json_resp(body)):
        with pytest.raises(gv.VideoAPIError) as exc_info:
            gv.submit_video_job(prompt="p")
    assert exc_info.value.code == code
    assert exc_info.value.retryable is retryable
    assert gv.is_retryable_error(exc_info.value) is retryable


def test_is_retryable_error_classifies_http_and_network_errors():
    def mk(code):
        return urllib.error.HTTPError("u", code, "m", {}, None)

    assert gv.is_retryable_error(mk(429)) is True
    assert gv.is_retryable_error(mk(503)) is True
    assert gv.is_retryable_error(mk(401)) is False
    assert gv.is_retryable_error(mk(402)) is False
    assert gv.is_retryable_error(TimeoutError("x")) is True
    assert gv.is_retryable_error(urllib.error.URLError("dns")) is True
    assert gv.is_retryable_error(FileNotFoundError("img")) is False


# --- poll ---------------------------------------------------------------------------


def test_poll_tolerates_transient_errors_then_downloads_atomically(tmp_path: Path):
    out = tmp_path / "clip.mp4"
    seq = [
        urllib.error.URLError("connection reset"),
        _json_resp({"status": "Processing"}),
        _json_resp({"status": "Success", "video_url": "https://cdn/v.mp4"}),
    ]
    seen_dest = []

    def fake_retrieve(url, dest):
        seen_dest.append(str(dest))
        Path(dest).write_bytes(b"video-bytes" * 10)
        return str(dest), None

    with patch("urllib.request.urlopen", side_effect=seq), \
         patch("urllib.request.urlretrieve", side_effect=fake_retrieve), \
         patch("tools.generate_video.time.sleep"):
        result = gv.poll_and_download_video("tid", out, timeout_seconds=60)

    assert result == str(out)
    assert out.exists() and out.read_bytes().startswith(b"video-bytes")
    # Downloaded to a temp name first so a half-written file never looks like a clip.
    assert seen_dest and seen_dest[0].endswith(".part")
    assert not Path(seen_dest[0]).exists()


def test_poll_gives_up_after_too_many_consecutive_transient_errors(tmp_path: Path):
    err = urllib.error.URLError("down")
    with patch("urllib.request.urlopen", side_effect=[err] * 10), patch("tools.generate_video.time.sleep"):
        with pytest.raises(urllib.error.URLError):
            gv.poll_and_download_video("tid", tmp_path / "c.mp4", timeout_seconds=60, max_transient_errors=3)


def test_poll_fail_status_with_sensitive_content_is_not_retryable(tmp_path: Path):
    body = {"status": "Fail", "base_resp": {"status_code": 1027, "status_msg": "sensitive output"}}
    with patch("urllib.request.urlopen", return_value=_json_resp(body)), patch("tools.generate_video.time.sleep"):
        with pytest.raises(gv.VideoAPIError) as exc_info:
            gv.poll_and_download_video("tid", tmp_path / "c.mp4", timeout_seconds=60)
    assert exc_info.value.code == 1027
    assert exc_info.value.retryable is False
    assert exc_info.value.task_failed is True


def test_poll_timeout_raises_timeout_error(tmp_path: Path):
    with patch("urllib.request.urlopen", side_effect=lambda *a, **k: _json_resp({"status": "Processing"})), \
         patch("tools.generate_video.time.sleep"):
        with pytest.raises(TimeoutError):
            gv.poll_and_download_video("tid", tmp_path / "c.mp4", timeout_seconds=0)
