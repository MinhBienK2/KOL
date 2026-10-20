"""Offline tests: API keys come from the environment / gitignored .env, never from source (round 4)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import config
from pipeline.config import ConfigurationError, load_dotenv, parse_env_file
from pipeline.offline import OfflineNetworkError, offline_mode
from tools import generate_video

ROOT = Path(__file__).resolve().parent.parent


def test_parse_env_file_handles_comments_quotes_export():
    text = '# c\n\nA=1\nexport B = "two words"\nC=\'x\'\nBAD LINE\nD=a=b\n'
    assert parse_env_file(text) == {"A": "1", "B": "two words", "C": "x", "D": "a=b"}


def test_load_dotenv_never_overrides_real_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = tmp_path / ".env"
    env.write_text("KOL_T_FROM_FILE=file\nKOL_T_BOTH=file\n", encoding="utf-8")
    monkeypatch.delenv("KOL_T_FROM_FILE", raising=False)
    monkeypatch.setenv("KOL_T_BOTH", "real")
    applied = load_dotenv(env)
    try:
        assert applied == {"KOL_T_FROM_FILE": "file"}
        import os

        assert os.environ["KOL_T_FROM_FILE"] == "file" and os.environ["KOL_T_BOTH"] == "real"
    finally:
        monkeypatch.delenv("KOL_T_FROM_FILE", raising=False)


def test_missing_env_file_is_fine(tmp_path: Path):
    assert load_dotenv(tmp_path / "nope.env") == {}


def test_missing_key_raises_clear_configuration_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    assert not config.MINIMAX_API_KEY
    assert "NOT SET" in repr(config.MINIMAX_API_KEY)
    with pytest.raises(ConfigurationError, match="MINIMAX_API_KEY is not set"):
        f"Bearer {config.MINIMAX_API_KEY}"
    with pytest.raises(ConfigurationError, match=r"\.env"):
        config.MINIMAX_API_KEY.value()


def test_key_resolved_at_call_time_and_never_in_repr(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "secret-123")
    assert f"Bearer {config.MINIMAX_API_KEY}" == "Bearer secret-123"
    assert "secret-123" not in repr(config.MINIMAX_API_KEY)


def test_generate_video_submit_without_key_raises_config_error_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with patch("urllib.request.urlopen") as urlopen:
        with pytest.raises(ConfigurationError):
            generate_video.submit_video_job(prompt="x")
    urlopen.assert_not_called()
    assert generate_video.is_retryable_error(ConfigurationError("x")) is False


def test_offline_mode_needs_no_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with offline_mode(True), pytest.raises(OfflineNetworkError):
        generate_video.submit_video_job(prompt="x")


def test_no_api_key_literal_left_in_tracked_source():
    files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    pattern = re.compile(r"sk-[A-Za-z0-9_\-]{20,}")
    offenders = []
    for name in files:
        path = ROOT / name
        if path.suffix in {".png", ".jpg", ".jpeg", ".mp4", ".wav", ".mp3", ".webp"} or not path.is_file():
            continue
        try:
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(name)
        except UnicodeDecodeError:
            continue
    assert offenders == []


def test_env_is_gitignored_and_example_lists_names():
    ignored = subprocess.run(["git", "check-ignore", ".env"], cwd=ROOT, capture_output=True, text=True)
    assert ignored.returncode == 0
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "MINIMAX_API_KEY=" in example and "sk-" not in example
