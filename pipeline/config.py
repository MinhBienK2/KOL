"""Global pipeline configuration and constants.

Secrets come from the environment. A gitignored ``.env`` at the repo root is loaded on import
(real environment variables win); see ``.env.example`` for the variable names.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class ConfigurationError(RuntimeError):
    """A required setting (e.g. an API key) is missing at the moment it is needed."""


def parse_env_file(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines (``#`` comments, optional ``export``, optional quotes)."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_dotenv(path: Path | str | None = None) -> dict[str, str]:
    """Load a gitignored ``.env`` into ``os.environ``; variables already set in the environment win.

    Defaults to ``<repo>/.env`` (override the location with ``KOL_ENV_FILE``). A missing or
    unreadable file is not an error. Returns the values that were actually applied.
    """
    env_path = Path(path or os.environ.get("KOL_ENV_FILE") or BASE_DIR / ".env")
    try:
        parsed = parse_env_file(env_path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    applied = {k: v for k, v in parsed.items() if k not in os.environ}
    os.environ.update(applied)
    return applied


class _RequiredSecret:
    """An API key resolved from the environment *when used*, never at import time.

    Offline runs import this module without any key. Interpolating the secret into a header
    (``f"Bearer {KEY}"``) or calling :meth:`value` raises :class:`ConfigurationError` if the
    variable is unset; ``repr`` never reveals the key.
    """

    def __init__(self, env_name: str) -> None:
        self.env_name = env_name

    def is_set(self) -> bool:
        return bool(os.environ.get(self.env_name, "").strip())

    def value(self) -> str:
        key = os.environ.get(self.env_name, "").strip()
        if not key:
            raise ConfigurationError(
                f"{self.env_name} is not set. Export it or add it to {BASE_DIR / '.env'} "
                f"(see .env.example). Offline mode (--offline / KOL_OFFLINE=1) needs no key."
            )
        return key

    def __str__(self) -> str:
        return self.value()

    def __format__(self, spec: str) -> str:
        return format(self.value(), spec)

    def __bool__(self) -> bool:
        return self.is_set()

    def __repr__(self) -> str:
        return f"<{self.env_name} {'set' if self.is_set() else 'NOT SET'}>"


load_dotenv()

PROJECTS_DIR = BASE_DIR / "projects"
OUTPUT_DIR = BASE_DIR / "output"
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
RAW_CLIPS_DIR = OUTPUT_DIR / "raw_clips"
SYNCED_CLIPS_DIR = OUTPUT_DIR / "synced_clips"
AUDIO_DIR = OUTPUT_DIR / "audio"
KEYFRAMES_DIR = OUTPUT_DIR / "keyframes"
CHARACTER_PATH = BASE_DIR / "assets" / "characters" / "kol_main" / "character.json"

MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://aiapi.2tocom.space").rstrip("/")
#: Resolved from ``MINIMAX_API_KEY`` at use time (``ConfigurationError`` if missing).
MINIMAX_API_KEY = _RequiredSecret("MINIMAX_API_KEY")

FLOW2API_BASE_URL = os.environ.get("FLOW2API_BASE_URL", "http://100.111.37.118:8000").rstrip("/")
FLOW2API_API_KEY = _RequiredSecret("FLOW2API_API_KEY")
DEFAULT_IMAGE_MODEL = os.environ.get("DEFAULT_IMAGE_MODEL", "gemini-3.1-flash-image-four-three-2k")

DEFAULT_VIDEO_MODEL = "MiniMax-Hailuo-2.3"
DEFAULT_TTS_MODEL = "tts-1"
DEFAULT_TTS_VOICE = "alloy"
DEFAULT_ASPECT_RATIO = "9:16"
TARGET_RESOLUTION = (1080, 1920)  # Width, Height for 9:16
