#!/usr/bin/env python3
"""Generate a per-outfit character sheet and register its identity.

ADR 0008 requires one multi-panel sheet per outfit, but the repository shipped a single
`studio_chic_black` sheet: `ARCHETYPE_IDENTITY_MAP` already points archetypes at
`kol_main_spa` / `kol_main_cozy` / `kol_main_techwear` / `kol_main_fashion`, so those
campaigns silently fell back to the black outfit. This tool closes that gap without
touching the canonical sheet.

It renders two references from the locked face anchor:

1. a 4-panel full-body turnaround (front / 45 / 90 / 180) on a flat neutral background;
2. a 2x2 close-up head grid (0 / 30 / 45 / 90), so the sheet matches the existing
   `character_sheet.png` layout (four body panels above four face panels).

Providers:
- ``flow2api`` (default): repo multimodal default (Gemini image / Nano Banana). The face
  anchor is honored; the probe measured SFace cosine ~0.84.
- ``minimax``: MiniMax ``image-01``. This proxy accepts ``file_list`` but ignores its
  content for identity: the probe measured SFace cosine ~0.16, i.e. a different face.
  Keep it for layout tests only; do not register a MiniMax sheet for production.

Both sources are watermark-cleaned with the same Telea pass used by the keyframe stage,
then composed at 2516 px wide (>= the 2048 px pre-flight minimum).

Example::

    python3 tools/generate_character_sheet.py \\
        --outfit-id minimalist_spa_silk \\
        --wardrobe-id costume_minimalist_spa_silk \\
        --identity-id kol_main_spa \\
        --identity-name "Minimalist Spa Silk" \\
        --character-tag "[KOL_MAIN_SPA]" \\
        --register

``--single-pass --aspect-ratio 16:9`` sends the canonical sheet plus the face anchor in one
Flow2API call and uses the returned image directly. 16:9 is required: the 4:3 image model
returns a portrait 3:4 canvas here and adds a second face row.

`--from-images` composes from already-downloaded sources and never touches the network.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from PIL import Image, ImageOps

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline.config import (  # noqa: E402
    FLOW2API_API_KEY,
    FLOW2API_BASE_URL,
    MINIMAX_API_KEY,
    MINIMAX_BASE_URL,
)
from pipeline.offline import (  # noqa: E402
    OfflineNetworkError,
    guard_network,
    guarded_urlopen,
    guarded_urlretrieve,
)
from pipeline.wardrobe import WARDROBE_CATALOG, WardrobeItem  # noqa: E402
from tools.dramaclaw_shot_builder import (  # noqa: E402
    clean_watermark_inpaint,
    upload_reference_image,
)

CHARACTER_FILE = BASE_DIR / "assets" / "characters" / "kol_main" / "character.json"
DEFAULT_REFERENCE = BASE_DIR / "assets" / "characters" / "kol_main" / "face_anchor.png"

#: Matches the canonical studio_chic_black sheet: 4 x 629 px body panels over 4 x 629 px faces.
SHEET_WIDTH = 2516
FACE_PANEL = (629, 624)
TOP_BAND = 50
PANEL_GAP = 72
BOTTOM_BAND = 50
SHEET_BG = (219, 219, 219)  # matches the generated face grid; body studio grey is normalised onto it

IMAGE_MODEL = "image-01"
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 180
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 5
_TRANSIENT_MARKERS = ("503", "502", "504", "429", "upstream", "timeout", "temporarily")


class SheetGenerationError(RuntimeError):
    """MiniMax or composition failed; never paper over it with a placeholder sheet."""


# --------------------------------------------------------------------------------------
# Prompt construction
# --------------------------------------------------------------------------------------


def _outfit_text(item: WardrobeItem) -> str:
    parts = [item.garment_description]
    if item.color_palette:
        parts.append(f"Color palette: {', '.join(item.color_palette)}.")
    if item.fabric_materials:
        parts.append(f"Fabric: {', '.join(item.fabric_materials)}.")
    if item.accessories:
        parts.append(f"Accessories: {', '.join(item.accessories)}.")
    return " ".join(parts)


def build_body_prompt(item: WardrobeItem) -> str:
    """Prompt for the 4-panel full-body turnaround.

    Wardrobe hair styling is intentionally not applied: identity locking owns the
    hairstyle, and the catalog's per-outfit hair changes (blowout, updo, crop) would
    break the face anchor.
    """
    return (
        "Photorealistic professional character turnaround reference sheet on one seamless "
        "flat light grey studio background (#E8E8E8), soft even diffused lighting, no vignette, "
        "no background shadow. "
        "The exact same young Vietnamese woman as the reference image: refined oval face, soft "
        "double eyelids, dark brown almond eyes, straight nose bridge, natural lips, warm fair skin, "
        "chin-length black bob haircut. Preserve her face, skin tone, body proportions and hairstyle "
        "EXACTLY. The reference clothing is irrelevant: replace it completely with the outfit below. "
        f"OUTFIT: {_outfit_text(item)} "
        "Four separate full-body figures in one horizontal row, equal scale, standing upright with "
        "arms relaxed at the sides, empty hands, neutral closed-mouth expression, head-to-toe fully "
        "in frame with feet visible. Left to right: front view 0 degrees, three-quarter view 45 degrees, "
        "side profile 90 degrees, rear view 180 degrees. No text, no labels, no watermark, no props, "
        "no overlapping figures, no cropped limbs. Editorial costume-sheet quality, 8k detail."
    )


def build_face_prompt(item: WardrobeItem) -> str:
    """Prompt for the 2x2 close-up head grid (bust only, outfit collar visible)."""
    return (
        "Photorealistic 2x2 grid of close-up head-and-shoulders portraits of the exact same young "
        "Vietnamese woman as the reference image: refined oval face, soft double eyelids, dark brown "
        "almond eyes, straight nose bridge, natural lips, warm fair skin, chin-length black bob haircut. "
        "Preserve her face and hairstyle EXACTLY; do not copy the reference clothing. "
        f"OUTFIT: {_outfit_text(item)} "
        "Four distinct head angles, equal scale and framing: top-left front view 0 degrees, top-right "
        "three-quarter view 30 degrees, bottom-left three-quarter view 45 degrees, bottom-right side "
        "profile 90 degrees. Neutral expression, eyes open, mouth closed. Seamless flat light grey "
        "background (#E8E8E8), even beauty lighting, no text, no labels, no watermark, no props. "
        "Sharp facial detail, 8k."
    )


def build_single_sheet_prompt(item: WardrobeItem) -> str:
    """One-call prompt: use the canonical sheet as a layout/identity template + a face close-up.

    The canonical sheet is the strongest layout reference available (4 body panels over 4
    face panels); the face anchor is the strongest identity reference. The prompt explicitly
    separates the two roles so the model does not copy the black outfit.
    """
    return (
        "You are given TWO reference images of the SAME young Vietnamese woman.\n"
        "REFERENCE 1 = her existing character sheet: four full-body views on the top row and four "
        "close-up face views on the bottom row, wearing a black outfit. Use REFERENCE 1 for LAYOUT, "
        "panel order, panel proportions and body proportions ONLY. Do NOT copy its black clothing.\n"
        "REFERENCE 2 = a clear close-up face anchor. Use REFERENCE 2 for FACIAL IDENTITY.\n\n"
        "TASK: create ONE new photorealistic character reference sheet for this exact same woman, "
        "with a new outfit, in a single image. Do not add a second person.\n\n"
        "IDENTITY LOCK (highest priority): exact same refined oval face, soft double eyelids, dark "
        "brown almond eyes, straight nose bridge, natural lips, warm fair skin, same skin tone, same "
        "chin-length black bob haircut and hairline. Neutral expression, eyes open, mouth closed, no "
        "smile. Do not beautify, change age, or change ethnicity.\n\n"
        f"NEW OUTFIT (replace the black outfit completely): {_outfit_text(item)} "
        "Cozy kitchen/home loungewear styling, soft natural fabric folds, no logos, no visible brand.\n\n"
        "LAYOUT — match REFERENCE 1 exactly: one LANDSCAPE sheet, width greater than height (the "
        "requested aspect ratio), do NOT create or rotate into a tall/portrait image; exactly EIGHT "
        "panels in exactly TWO rows and FOUR columns, thin light-grey gutters, no outer frame, no third "
        "row, no second face row. "
        "TOP ROW (taller, about 60% of the sheet height): exactly FOUR separate FULL-BODY panels, "
        "head-to-toe with feet visible, standing upright, arms relaxed at the sides, empty hands, equal "
        "scale: left to right front 0 degrees, three-quarter 45 degrees, side profile 90 degrees, back "
        "180 degrees (the fourth panel shows her back, no face). Do not omit the back view. "
        "BOTTOM ROW: exactly FOUR separate head-and-shoulders CLOSE-UP panels, one row only, equal "
        "scale: left to right front 0 degrees, three-quarter 30 degrees, three-quarter 45 degrees, side "
        "profile 90 degrees. Do not duplicate the face row. Every panel shows the same woman, same "
        "outfit, same lighting.\n\n"
        "BACKGROUND: one flat seamless light neutral grey (#E8E8E8) across all eight panels, soft even "
        "studio lighting, no vignette, no background shadows, no kitchen props, no furniture.\n\n"
        "FORBIDDEN: different face, different hairstyle, black top, black trousers, dress, duplicate "
        "person, overlapping figures, mismatched outfit between panels, cropped head or feet, extra "
        "limbs, text, numbers, labels, watermark, logo, frame, collage seams, portrait/tall canvas, "
        "third row, duplicated face row, missing back view.\n\n"
        "STYLE: photorealistic editorial costume sheet, sharp facial detail, natural skin texture, 8k."
    )


# --------------------------------------------------------------------------------------
# MiniMax image-01
# --------------------------------------------------------------------------------------


def _poll_image_job(task_id: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {MINIMAX_API_KEY}"}
    poll_url = f"{MINIMAX_BASE_URL}/v1/media/image/jobs/{task_id}"
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        req = urllib.request.Request(poll_url, headers=headers)
        with guarded_urlopen(req, operation="minimax.image_poll", timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        status = str(payload.get("status", ""))
        if status == "Success":
            images = payload.get("images") or []
            if not images or not images[0].get("url"):
                raise SheetGenerationError(f"MiniMax job {task_id} succeeded without an image: {payload}")
            return images[0]["url"]
        if status in {"Fail", "Failed", "Error"}:
            raise SheetGenerationError(f"MiniMax job {task_id} failed: {payload}")
    raise SheetGenerationError(f"MiniMax job {task_id} timed out after {POLL_TIMEOUT_SECONDS}s")


def generate_minimax_image(
    prompt: str,
    aspect_ratio: str,
    reference_paths: Sequence[Path],
    output_path: Path,
) -> dict[str, Any]:
    """Submit one MiniMax image-01 job, download it, and Telea-clean the watermark."""
    guard_network("minimax.image_generation", f"character sheet {output_path.name}")
    if not reference_paths:
        raise SheetGenerationError("At least one identity reference is required")

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _generate_once(prompt, aspect_ratio, reference_paths, output_path)
        except SheetGenerationError as exc:
            last_error = exc
            if not any(marker in str(exc).lower() for marker in _TRANSIENT_MARKERS) or attempt == MAX_ATTEMPTS:
                raise
            delay = RETRY_BACKOFF_SECONDS * attempt
            print(f"[Sheet] Transient MiniMax failure ({exc}); retrying in {delay}s ({attempt}/{MAX_ATTEMPTS})")
            time.sleep(delay)
    raise SheetGenerationError(f"MiniMax image generation failed: {last_error}")


def _generate_once(
    prompt: str,
    aspect_ratio: str,
    reference_paths: Sequence[Path],
    output_path: Path,
) -> dict[str, Any]:
    file_list = []
    for reference in reference_paths:
        file_list.append({"type": "character", "image_file": upload_reference_image(reference)})

    body = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "file_list": file_list,
    }
    req = urllib.request.Request(
        f"{MINIMAX_BASE_URL}/v1/media/image",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with guarded_urlopen(req, operation="minimax.image_generation", timeout=180) as resp:
        submitted = json.loads(resp.read().decode("utf-8"))
    task_id = submitted.get("task_id")
    if not task_id:
        raise SheetGenerationError(f"MiniMax rejected the image job: {submitted}")

    image_url = _poll_image_job(task_id)
    size, watermark_pixels = _download_and_clean(image_url, output_path, operation="minimax.image_download")
    return {
        "provider": "minimax",
        "model": IMAGE_MODEL,
        "task_id": task_id,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "references": [str(p) for p in reference_paths],
        "image_url": image_url,
        "size": list(size),
        "watermark_pixels": watermark_pixels,
    }


FLOW2API_MODELS = {
    "16:9": "gemini-3.1-flash-image-landscape-2k",
    "1:1": "gemini-3.1-flash-image-square-2k",
    "4:3": "gemini-3.1-flash-image-four-three-2k",
    "3:4": "gemini-3.1-flash-image-three-four-2k",
    "9:16": "gemini-3.1-flash-image-portrait-2k",
}


def _download_and_clean(image_url: str, output_path: Path, *, operation: str) -> tuple[tuple[int, int], int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = output_path.with_name(f".raw_{output_path.name}")
    guarded_urlretrieve(image_url, raw_path, operation=operation)
    watermark_pixels = clean_watermark_inpaint(raw_path, output_path)
    raw_path.unlink(missing_ok=True)
    with Image.open(output_path) as im:
        return im.size, watermark_pixels


def generate_flow2api_image(
    prompt: str,
    aspect_ratio: str,
    reference_paths: Sequence[Path],
    output_path: Path,
) -> dict[str, Any]:
    """Generate with the repo's default multimodal provider (Gemini image / Nano Banana).

    Unlike MiniMax ``image-01`` (whose ``file_list`` reference is ignored by this proxy),
    this endpoint actually preserves the face anchor: SFace cosine ~0.84 in the probe.
    """
    guard_network("flow2api.image_generation", f"character sheet {output_path.name}")
    if not reference_paths:
        raise SheetGenerationError("At least one identity reference is required")
    model = FLOW2API_MODELS.get(aspect_ratio)
    if model is None:
        raise SheetGenerationError(f"Unsupported aspect ratio {aspect_ratio!r} for Flow2API")

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for reference in reference_paths:
                suffix = reference.suffix.lower().lstrip(".") or "png"
                encoded = base64.b64encode(reference.read_bytes()).decode("ascii")
                content.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/{suffix};base64,{encoded}"}}
                )
            payload = {"model": model, "messages": [{"role": "user", "content": content}]}
            req = urllib.request.Request(
                f"{FLOW2API_BASE_URL}/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Authorization": f"Bearer {FLOW2API_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            with guarded_urlopen(req, operation="flow2api.image_generation", timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            message = (result.get("choices") or [{}])[0].get("message", {}).get("content", "")
            match = re.search(r"\((https?://[^)]+)\)", message) or re.search(r"https?://[^\s)\]\"<]+", message)
            if not match:
                raise SheetGenerationError(f"Flow2API returned no image URL: {message[:300]}")
            image_url = match.group(1) if match.groups() else match.group(0)
            size, watermark_pixels = _download_and_clean(
                image_url, output_path, operation="flow2api.image_download"
            )
            return {
                "provider": "flow2api",
                "model": model,
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "references": [str(p) for p in reference_paths],
                "image_url": image_url,
                "size": list(size),
                "watermark_pixels": watermark_pixels,
            }
        except OfflineNetworkError:
            raise
        except Exception as exc:
            last_error = exc
            transient = any(marker in str(exc).lower() for marker in _TRANSIENT_MARKERS) or isinstance(
                exc, (urllib.error.URLError, TimeoutError)
            )
            if not transient or attempt == MAX_ATTEMPTS:
                raise
            delay = RETRY_BACKOFF_SECONDS * attempt
            print(f"[Sheet] Transient Flow2API failure ({exc}); retrying in {delay}s ({attempt}/{MAX_ATTEMPTS})")
            time.sleep(delay)
    raise SheetGenerationError(f"Flow2API image generation failed: {last_error}")


# --------------------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------------------


def _background_colour(img: Image.Image) -> tuple[int, int, int]:
    rgb = img.convert("RGB")
    w, h = rgb.size
    samples = []
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        samples.append(rgb.getpixel((x, y)))
    samples.sort()
    return samples[len(samples) // 2]


def _border_background_mask(img: Image.Image, tolerance: int = 7) -> "np.ndarray":
    """Boolean mask of the flat studio background connected to the image border.

    Only border-connected pixels are replaced, so white garment areas inside the
    silhouette (the spa robe) stay untouched even when they are close to the backdrop.
    """
    rgb = img.convert("RGB")
    arr = np.asarray(rgb).astype(np.int16)
    bg = np.asarray(_background_colour(rgb), dtype=np.int16)
    close = (np.abs(arr - bg).max(axis=2) <= tolerance).astype(np.uint8)
    count, labels, _stats, _centroids = cv2.connectedComponentsWithStats(close, 8)
    border_labels = (
        set(labels[0, :].tolist())
        | set(labels[-1, :].tolist())
        | set(labels[:, 0].tolist())
        | set(labels[:, -1].tolist())
    )
    border_labels.discard(0)
    if not border_labels:
        return np.zeros(close.shape, dtype=bool)
    return np.isin(labels, list(border_labels))


def _replace_background(img: Image.Image, mask: "np.ndarray", target: tuple[int, int, int]) -> Image.Image:
    arr = np.asarray(img.convert("RGB")).copy()
    arr[mask] = target
    return Image.fromarray(arr)


def _trim_to_subject(img: Image.Image, bg_mask: "np.ndarray | None" = None, margin_ratio: float = 0.015) -> Image.Image:
    """Crop the flat studio background around the subject, keeping a small breathing margin."""
    rgb = img.convert("RGB")
    if bg_mask is None:
        bg_mask = _border_background_mask(rgb)
    foreground = (~bg_mask).astype(np.uint8)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(foreground, 8)
    min_area = max(1, int(foreground.size * 0.0005))
    boxes = [
        (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT])
        for i in range(1, count)
        if stats[i, cv2.CC_STAT_AREA] >= min_area
    ]
    if not boxes:
        return rgb
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    w, h = rgb.size
    margin_x = max(1, round((right - left) * margin_ratio))
    margin_y = max(1, round((bottom - top) * margin_ratio))
    return rgb.crop(
        (
            max(0, left - margin_x),
            max(0, top - margin_y),
            min(w, right + margin_x),
            min(h, bottom + margin_y),
        )
    )


def _quiet_runs(mask: "np.ndarray", min_width: int = 1) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        elif not value and start is not None:
            if index - start >= min_width:
                runs.append((start, index - 1))
            start = None
    if start is not None and len(mask) - start >= min_width:
        runs.append((start, len(mask) - 1))
    return runs


def _split_body_panels(img: Image.Image, count: int = 4) -> list[Image.Image]:
    """Split a turnaround row into equal figures using low-variance gutters.

    Column/row standard deviation is used instead of background-colour thresholding so
    that a white robe on a light backdrop still separates cleanly from the background.
    Each figure is tight-cropped to its active silhouette so horizontal centering in its
    column aligns with the facial portrait below.
    """
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    height, width = gray.shape
    col_std = gray.std(axis=0)
    gaps = [
        run
        for run in _quiet_runs(col_std < 4.0, min_width=max(2, int(width * 0.01)))
        if run[0] > 0 and run[1] < width - 1
    ]
    if len(gaps) < count - 1:
        return []
    selected = sorted(sorted(gaps, key=lambda run: run[1] - run[0], reverse=True)[: count - 1])
    boundaries = [0] + [(start + end) // 2 for start, end in selected] + [width]
    spans = [(boundaries[i], boundaries[i + 1] - 1) for i in range(count)]

    panels: list[Image.Image] = []
    for x0, x1 in spans:
        span_gray = gray[:, x0 : x1 + 1]
        col_s = span_gray.std(axis=0)
        row_s = span_gray.std(axis=1)
        active_cols = np.where(col_s > 4.0)[0]
        active_rows = np.where(row_s > 4.0)[0]
        if len(active_cols) == 0 or len(active_rows) == 0:
            return []
        cx0 = x0 + int(active_cols.min())
        cx1 = x0 + int(active_cols.max())
        cy0 = int(active_rows.min())
        cy1 = int(active_rows.max())
        panels.append(img.crop((cx0, cy0, cx1 + 1, cy1 + 1)))
    return panels


def _split_face_grid(grid: Image.Image) -> list[Image.Image]:
    """Split the 2x2 grid by trimming outer white frames and stripping middle gutters."""
    rgb = grid.convert("RGB")
    arr = np.asarray(rgb)
    gray = np.asarray(grid.convert("L"), dtype=np.float32)
    w, h = rgb.size

    col_std = gray.std(axis=0)
    row_std = gray.std(axis=1)

    # 1. Middle vertical gutter (look in middle 35% to 65%)
    mid_x = w // 2
    lo_x, hi_x = int(0.35 * w), int(0.65 * w)
    quiet_cols = col_std < 3.5
    runs_x = _quiet_runs(quiet_cols[lo_x:hi_x], min_width=1)
    runs_x = [(s + lo_x, e + lo_x) for s, e in runs_x]
    if runs_x:
        runs_x.sort(key=lambda r: abs((r[0] + r[1]) / 2 - mid_x))
        x_g_start, x_g_end = runs_x[0]
    else:
        x_g_start = x_g_end = mid_x

    # 2. Middle horizontal gutter (look in middle 35% to 65%)
    mid_y = h // 2
    lo_y, hi_y = int(0.35 * h), int(0.65 * h)
    quiet_rows = row_std < 3.5
    runs_y = _quiet_runs(quiet_rows[lo_y:hi_y], min_width=1)
    runs_y = [(s + lo_y, e + lo_y) for s, e in runs_y]
    if runs_y:
        runs_y.sort(key=lambda r: abs((r[0] + r[1]) / 2 - mid_y))
        y_g_start, y_g_end = runs_y[0]
    else:
        y_g_start = y_g_end = mid_y

    # 3. Outer border frame: trim quiet outer edges that are near white (>235)
    max_border = int(0.04 * min(w, h))
    left = 0
    for x in range(max_border):
        if arr[:, x, :3].mean() > 235:
            left = x + 1
        else:
            break

    right = w
    for x in range(w - 1, w - 1 - max_border, -1):
        if arr[:, x, :3].mean() > 235:
            right = x
        else:
            break

    top = 0
    for y in range(max_border):
        if arr[y, :, :3].mean() > 235:
            top = y + 1
        else:
            break

    bottom = h
    for y in range(h - 1, h - 1 - max_border, -1):
        if arr[y, :, :3].mean() > 235:
            bottom = y
        else:
            break

    boxes = [
        (left, top, x_g_start, y_g_start),
        (x_g_end + 1, top, right, y_g_start),
        (left, y_g_end + 1, x_g_start, bottom),
        (x_g_end + 1, y_g_end + 1, right, bottom),
    ]
    return [rgb.crop(box) for box in boxes]


def compose_character_sheet(
    body_path: Path,
    faces_path: Path,
    output_path: Path,
    background: tuple[int, int, int] | None = None,
) -> tuple[int, int]:
    """Compose the canonical 4-body-over-4-face layout at ``SHEET_WIDTH`` px."""
    with Image.open(body_path) as body_img, Image.open(faces_path) as faces_img:
        faces = _split_face_grid(faces_img)
        if background is None:
            p0_arr = np.asarray(faces[0])
            pw, ph = faces[0].size
            corner = p0_arr[: max(1, int(0.08 * ph)), : max(1, int(0.08 * pw)), :3]
            background = tuple(int(round(x)) for x in corner.mean(axis=(0, 1)))

        body_source = body_img.convert("RGB")
        body_bg = _border_background_mask(body_source)
        body = _replace_background(body_source, body_bg, background)
        body = _trim_to_subject(body, bg_mask=body_bg)

    panels = _split_body_panels(body)
    cell_w = SHEET_WIDTH // 4  # 629 px
    TARGET_SCALED_HEIGHT = 1260
    TARGET_COMMON_HEIGHT = round(TARGET_SCALED_HEIGHT * 0.92)  # 1159 px

    if len(panels) == 4:
        common_height = min(TARGET_COMMON_HEIGHT, min((cell_w * 0.90) * p.height / p.width for p in panels))
        scaled_height = TARGET_SCALED_HEIGHT
        body_row = Image.new("RGB", (SHEET_WIDTH, scaled_height), background)
        for index, panel in enumerate(panels):
            scale = common_height / panel.height
            new_w = max(1, round(panel.width * scale))
            new_h = max(1, round(panel.height * scale))
            resized = panel.resize((new_w, new_h), Image.LANCZOS)
            pos_x = index * cell_w + (cell_w - new_w) // 2
            pos_y = (scaled_height - new_h) // 2
            body_row.paste(resized, (pos_x, pos_y))
        body = body_row
    else:
        body_w, body_h = body.size
        scaled_height = max(1, round(body_h * SHEET_WIDTH / body_w))
        body = body.resize((SHEET_WIDTH, scaled_height), Image.LANCZOS)

    face_w, face_h = FACE_PANEL
    face_row = Image.new("RGB", (SHEET_WIDTH, face_h), background)
    for index, panel in enumerate(faces):
        face_row.paste(ImageOps.fit(panel, (face_w, face_h), Image.LANCZOS), (index * face_w, 0))

    sheet = Image.new(
        "RGB",
        (SHEET_WIDTH, TOP_BAND + scaled_height + PANEL_GAP + face_h + BOTTOM_BAND),
        background,
    )
    sheet.paste(body, (0, TOP_BAND))
    sheet.paste(face_row, (0, TOP_BAND + scaled_height + PANEL_GAP))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, "PNG", optimize=True)
    return sheet.size


# --------------------------------------------------------------------------------------
# Character registration
# --------------------------------------------------------------------------------------


def register_identity(
    character_path: Path,
    identity_id: str,
    identity_name: str,
    character_tag: str,
    outfit: WardrobeItem,
    sheet_rel_path: str,
) -> None:
    """Insert or replace one identity entry, preserving the default outfit and JSON order."""
    with open(character_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entry = {
        "identity_id": identity_id,
        "identity_name": identity_name,
        "character_tag": character_tag,
        "appearance_details": outfit.garment_description,
        "character_sheet": sheet_rel_path,
    }
    identities = data.setdefault("identities", [])
    for index, existing in enumerate(identities):
        if existing.get("identity_id") == identity_id:
            identities[index] = {**existing, **entry}
            break
    else:
        identities.append(entry)

    with open(character_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a per-outfit character sheet (Flow2API or MiniMax image-01)")
    parser.add_argument("--outfit-id", required=True, help="Folder under assets/characters/kol_main/outfits/")
    parser.add_argument("--wardrobe-id", help=f"Wardrobe catalog key: {', '.join(sorted(WARDROBE_CATALOG))}")
    parser.add_argument("--identity-id", help="character.json identity_id (default: kol_main_<outfit-id>)")
    parser.add_argument("--identity-name", help="Human-readable identity name (default: outfit name)")
    parser.add_argument("--character-tag", help="Prompt tag (default: [KOL_MAIN_<OUTFIT_ID>])")
    parser.add_argument("--reference", action="append", default=[], help="Identity reference (repeatable; default face_anchor)")
    parser.add_argument("--register", action="store_true", help="Write/replace the identity in character.json")
    parser.add_argument("--character-file", default=str(CHARACTER_FILE), help="character.json path")
    parser.add_argument("--force", action="store_true", help="Regenerate sources even if they already exist")
    parser.add_argument(
        "--provider",
        choices=["flow2api", "minimax"],
        default="flow2api",
        help="flow2api preserves the face anchor; minimax image-01 ignores file_list references in this proxy",
    )
    parser.add_argument(
        "--single-pass",
        action="store_true",
        help="One Flow2API call from the canonical sheet + face anchor; no body/face composition",
    )
    parser.add_argument(
        "--aspect-ratio",
        choices=["4:3", "1:1", "16:9", "3:4", "9:16"],
        default="4:3",
        help="Aspect ratio for --single-pass (default: 4:3 for the 4x2 sheet layout)",
    )
    parser.add_argument(
        "--from-images",
        nargs=2,
        metavar=("BODY", "FACES"),
        help="Skip generation and compose these existing images instead",
    )
    return parser.parse_args(argv)


def _run_single_pass(
    args: argparse.Namespace,
    outfit_dir: Path,
    source_dir: Path,
    sheet_path: Path,
) -> int:
    """Generate one sheet image directly from the canonical sheet + face anchor."""
    outfit = WARDROBE_CATALOG.get(args.wardrobe_id or "")
    if outfit is None:
        raise SystemExit(f"Unknown wardrobe id {args.wardrobe_id!r}. Choose from: {', '.join(sorted(WARDROBE_CATALOG))}")

    if args.reference:
        references = [Path(p) if Path(p).is_absolute() else BASE_DIR / p for p in args.reference]
    else:
        with open(args.character_file, "r", encoding="utf-8") as f:
            character = json.load(f)
        declared = [character.get("character_sheet"), character.get("face_anchor")]
        if not all(declared):
            raise SystemExit("character.json must declare character_sheet and face_anchor for --single-pass")
        references = [BASE_DIR / value for value in declared]
    for reference in references:
        if not reference.exists():
            raise SystemExit(f"Reference not found: {reference}")

    generate = generate_flow2api_image if args.provider == "flow2api" else generate_minimax_image
    metadata: dict[str, Any] = {
        "provider": args.provider,
        "mode": "single_pass",
        "aspect_ratio": args.aspect_ratio,
        "references": [str(path) for path in references],
    }
    if args.force or not sheet_path.exists():
        print(f"[Sheet] {args.provider} single-pass {args.aspect_ratio} sheet -> {sheet_path}")
        metadata["generation"] = generate(
            build_single_sheet_prompt(outfit),
            args.aspect_ratio,
            references,
            sheet_path,
        )
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "single_pass_sheet.png").write_bytes(sheet_path.read_bytes())
    else:
        print(f"[Sheet] Reusing existing {sheet_path} (use --force to regenerate)")
        existing_meta = source_dir / "generation.json"
        if existing_meta.exists():
            try:
                prior = json.loads(existing_meta.read_text(encoding="utf-8")).get("generation", {})
                if isinstance(prior, dict):
                    metadata = {**prior, **metadata}
            except (OSError, ValueError):
                pass

    with Image.open(sheet_path) as image:
        size = image.size
    print(f"[Sheet] Generated {size[0]}x{size[1]} -> {sheet_path}")

    sheet_rel = str(sheet_path.relative_to(BASE_DIR))
    identity_id = args.identity_id or f"kol_main_{args.outfit_id}"
    if args.register:
        register_identity(
            Path(args.character_file),
            identity_id=identity_id,
            identity_name=args.identity_name or outfit.name,
            character_tag=args.character_tag or f"[KOL_MAIN_{args.outfit_id.upper()}]",
            outfit=outfit,
            sheet_rel_path=sheet_rel,
        )
        print(f"[Sheet] Registered identity {identity_id!r} in {args.character_file}")

    source_dir.mkdir(parents=True, exist_ok=True)
    with open(source_dir / "generation.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "outfit_id": args.outfit_id,
                "wardrobe_id": args.wardrobe_id,
                "identity_id": identity_id,
                "sheet": sheet_rel,
                "sheet_size": list(size),
                "generation": metadata,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    outfit_dir = BASE_DIR / "assets" / "characters" / "kol_main" / "outfits" / args.outfit_id
    source_dir = outfit_dir / "_source"
    body_path = source_dir / "body_turnaround_16x9.png"
    faces_path = source_dir / "faces_grid_2x2.png"
    sheet_path = outfit_dir / "character_sheet.png"

    if args.single_pass:
        return _run_single_pass(args, outfit_dir, source_dir, sheet_path)

    if args.from_images:
        body_path, faces_path = Path(args.from_images[0]), Path(args.from_images[1])
        outfit = WARDROBE_CATALOG.get(args.wardrobe_id or "", None)
        if outfit is None:
            raise SystemExit("--wardrobe-id is required with --from-images (used for registration metadata)")
        metadata: dict[str, Any] = {"composed_from": [str(body_path), str(faces_path)]}
    else:
        if not args.wardrobe_id:
            raise SystemExit("--wardrobe-id is required unless --from-images is used")
        outfit = WARDROBE_CATALOG.get(args.wardrobe_id)
        if outfit is None:
            raise SystemExit(f"Unknown wardrobe id {args.wardrobe_id!r}. Choose from: {', '.join(sorted(WARDROBE_CATALOG))}")

        references = [Path(p) for p in (args.reference or [str(DEFAULT_REFERENCE)])]
        references = [p if p.is_absolute() else BASE_DIR / p for p in references]
        for reference in references:
            if not reference.exists():
                raise SystemExit(f"Reference not found: {reference}")

        generate = generate_flow2api_image if args.provider == "flow2api" else generate_minimax_image
        metadata = {"provider": args.provider}
        if args.force or not body_path.exists():
            print(f"[Sheet] {args.provider} body turnaround -> {body_path}")
            metadata["body"] = generate(build_body_prompt(outfit), "16:9", references, body_path)
        if args.force or not faces_path.exists():
            print(f"[Sheet] {args.provider} face grid -> {faces_path}")
            metadata["faces"] = generate(build_face_prompt(outfit), "1:1", references, faces_path)

    size = compose_character_sheet(body_path, faces_path, sheet_path)
    print(f"[Sheet] Composed {size[0]}x{size[1]} -> {sheet_path}")

    sheet_rel = str(sheet_path.relative_to(BASE_DIR))
    identity_id = args.identity_id or f"kol_main_{args.outfit_id}"
    if args.register:
        register_identity(
            Path(args.character_file),
            identity_id=identity_id,
            identity_name=args.identity_name or outfit.name,
            character_tag=args.character_tag or f"[KOL_MAIN_{args.outfit_id.upper()}]",
            outfit=outfit,
            sheet_rel_path=sheet_rel,
        )
        print(f"[Sheet] Registered identity {identity_id!r} in {args.character_file}")

    source_dir.mkdir(parents=True, exist_ok=True)
    with open(source_dir / "generation.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "outfit_id": args.outfit_id,
                "wardrobe_id": args.wardrobe_id,
                "identity_id": identity_id,
                "sheet": sheet_rel,
                "sheet_size": list(size),
                "generation": metadata,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
