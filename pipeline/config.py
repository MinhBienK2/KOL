"""Global pipeline configuration and constants."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE_DIR / "projects"
OUTPUT_DIR = BASE_DIR / "output"
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
RAW_CLIPS_DIR = OUTPUT_DIR / "raw_clips"
SYNCED_CLIPS_DIR = OUTPUT_DIR / "synced_clips"
AUDIO_DIR = OUTPUT_DIR / "audio"
KEYFRAMES_DIR = OUTPUT_DIR / "keyframes"
CHARACTER_PATH = BASE_DIR / "assets" / "characters" / "kol_main" / "character.json"

MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://aiapi.2tocom.space").rstrip("/")
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "sk-cu-hr7Y6QZPkzksXlfn74J4yeF_xmL9Rlubf_tAhD4Sgfw")

FLOW2API_BASE_URL = os.environ.get("FLOW2API_BASE_URL", "http://100.111.37.118:8000").rstrip("/")
FLOW2API_API_KEY = os.environ.get("FLOW2API_API_KEY", "projectx")
DEFAULT_IMAGE_MODEL = os.environ.get("DEFAULT_IMAGE_MODEL", "gemini-3.1-flash-image-four-three-2k")

DEFAULT_VIDEO_MODEL = "MiniMax-Hailuo-2.3"
DEFAULT_TTS_MODEL = "tts-1"
DEFAULT_TTS_VOICE = "alloy"
DEFAULT_ASPECT_RATIO = "9:16"
TARGET_RESOLUTION = (1080, 1920)  # Width, Height for 9:16
