"""Thin clients for the paid media calls the continuity path makes (image, vision, video, speech)."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from pipeline.config import FLOW2API_API_KEY, FLOW2API_BASE_URL, MINIMAX_API_KEY, MINIMAX_BASE_URL
from pipeline.offline import guard_network, guarded_urlopen, guarded_urlretrieve
from tools.generate_video import poll_and_download_video, submit_video_job, upload_first_frame

FLOW2API_IMAGE_MODELS = {"9:16": "gemini-3.1-flash-image-portrait-2k", "16:9": "gemini-3.1-flash-image-landscape-2k"}


class MediaError(RuntimeError):
    pass


def _headers() -> dict:
    return {"Authorization": f"Bearer {MINIMAX_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def _post(path: str, body: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(MINIMAX_BASE_URL + path, data=json.dumps(body).encode("utf-8"), headers=_headers())
    try:
        with guarded_urlopen(req, operation=f"minimax{path}", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MediaError(f"{path}: HTTP {exc.code} {exc.read()[:300].decode('utf-8', 'replace')}") from exc


def _get(path: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(MINIMAX_BASE_URL + path, headers=_headers())
    with guarded_urlopen(req, operation=f"minimax{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def upload(path: str | Path) -> str:
    """Temporary public URL for a local file (MiniMax OSS, ~1h)."""
    return upload_first_frame(Path(path).resolve())


def minimax_image(prompt: str, out_path: Path, *, reference_urls: Optional[List[str]] = None,
                  aspect_ratio: str = "9:16", attempts: int = 3) -> Path:
    """image-01 render. The gateway serves one job at a time; 503s are retried with back-off."""
    body = {"model": "image-01", "prompt": prompt[:4000], "aspect_ratio": aspect_ratio, "resolution": "2K"}
    if reference_urls:
        body["file_list"] = [{"type": "character", "image_file": url} for url in reference_urls]
    last = ""
    for attempt in range(attempts):
        job = _post("/v1/media/image", body)
        task_id = job.get("task_id")
        if not task_id:
            raise MediaError(f"image-01 submit failed: {job}")
        for _ in range(100):
            time.sleep(4)
            state = _get(f"/v1/media/image/jobs/{task_id}")
            if state.get("status") == "Success":
                guarded_urlretrieve(state["images"][0]["url"], out_path, operation="minimax.image_download")
                return out_path
            if state.get("status") in ("Fail", "Failed"):
                last = str(state.get("error") or state)
                break
        time.sleep(10 * (attempt + 1))
    raise MediaError(f"image-01 failed after {attempts} attempts: {last}")


def flow2api_image(prompt: str, out_path: Path, *, reference_paths: List[Path], aspect_ratio: str = "9:16") -> Path:
    """Gemini Flash Image with several reference images in one message (identity + product + scene)."""
    guard_network("flow2api.image_generation")
    content: list = [{"type": "text", "text": prompt}]
    for ref in reference_paths:
        mime = mimetypes.guess_type(str(ref))[0] or "image/png"
        data = base64.b64encode(Path(ref).read_bytes()).decode("utf-8")
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
    payload = {"model": FLOW2API_IMAGE_MODELS.get(aspect_ratio, FLOW2API_IMAGE_MODELS["9:16"]),
               "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(
        f"{FLOW2API_BASE_URL}/v1/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {FLOW2API_API_KEY}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with guarded_urlopen(req, operation="flow2api.image_generation", timeout=300) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MediaError(f"flow2api: HTTP {exc.code} {exc.read()[:300].decode('utf-8', 'replace')}") from exc
    text = res["choices"][0]["message"]["content"]
    match = re.search(r"\((https?://[^\)]+)\)", text)
    if not match:
        raise MediaError(f"flow2api returned no image: {text[:200]}")
    guarded_urlretrieve(match.group(1), out_path, operation="flow2api.download_image")
    return out_path


def describe_image(path: str | Path, question: str) -> str:
    """Vision model description of a local image (used by the keyframe/clip judges)."""
    res = _post("/v1/media/vision/describe", {"question": question, "image_url": upload(path)}, timeout=180)
    return str((res.get("data") or {}).get("description") or "")


def render_i2v(first_frame: str | Path, prompt: str, out_path: Path, *, duration: int = 6, resolution: str = "768P") -> Path:
    """One Hailuo-2.3 image-to-video clip from a local first frame."""
    task_id = submit_video_job(prompt=prompt, image_url=upload(first_frame), aspect_ratio="9:16",
                               duration=duration, resolution=resolution)
    poll_and_download_video(task_id, out_path, timeout_seconds=600)
    return out_path


def speech(text: str, out_path: Path, *, voice: str, speed: float = 1.0) -> Path:
    """Vietnamese TTS (speech-01) to an mp3."""
    guard_network("tts.speech")
    body = {"model": "speech-01", "input": text, "voice": voice, "speed": speed, "response_format": "mp3"}
    req = urllib.request.Request(MINIMAX_BASE_URL + "/v1/audio/speech", data=json.dumps(body).encode("utf-8"), headers=_headers())
    try:
        with guarded_urlopen(req, operation="tts.speech", timeout=90) as resp:
            out_path.write_bytes(resp.read())
    except urllib.error.HTTPError as exc:
        raise MediaError(f"speech: HTTP {exc.code} {exc.read()[:300].decode('utf-8', 'replace')}") from exc
    return out_path


def music(prompt: str, out_path: Path) -> Path:
    """Instrumental bed from music-01 (no lyrics -> instrumental; the call blocks until rendered)."""
    job = _post("/v1/media/music", {"prompt": prompt, "title": "bed"}, timeout=300)
    tracks = (job.get("data") or {}).get("tracks") or []
    url = tracks[0].get("audio_url") if tracks else None
    if not url:
        raise MediaError(f"music returned no audio: {job}")
    guarded_urlretrieve(url, out_path, operation="minimax.music_download")
    return out_path
