"""Stage 5 video provider: the Comfy Colab Kit gateway running Pika H3 Flex on MiniMax H3.

The pipeline used to render shots with MiniMax Hailuo-2.3 over HTTP. It now renders them on
the Colab L4 GPU behind the Comfy Colab Kit gateway, which serves three official Comfy-Org
workflows for the ``minimax-h3-g4`` profile:

===========  ==============================  ==================================================
flow         ComfyUI workflow                used for
===========  ==============================  ==================================================
``t2v``      ``pika-h3-flex-t2v``            shots without any image (pure text-to-video)
``fl2va``    ``pika-h3-flex-fl2va``          image-to-video (first frame) and first+last frame
``ref2va``   ``pika-h3-flex-ref2va``         reference-to-video (identity anchor as ``<Picture 1>``)
===========  ==============================  ==================================================

The templates are UI workflows with subgraphs, so they are converted to API-format graphs
(``pipeline.comfy_ui2api``) before being queued on ``POST /prompt``. Clips come back with a
native stereo audio track (MiniMax H3 renders video *and* ambience in one pass).

The gateway sits behind Cloudflare Access: requests need the agent token *and* the CF Access
service-token headers, otherwise Cloudflare answers with its sign-in page.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pipeline import telemetry
from pipeline.comfy_ui2api import (
    add_load_image,
    convert,
    drop_input,
    link_target,
    nodes_by_class,
    set_linked_image,
)
from pipeline.config import (
    COMFY_GATEWAY_TOKEN,
    COMFY_GATEWAY_URL,
    ConfigurationError,
)
from pipeline.offline import guard_network, guarded_urlopen

#: The three gateway workflows this provider drives.
FLOW_T2V = "t2v"
FLOW_FL2VA = "fl2va"
FLOW_REF2VA = "ref2va"

#: Gateway-side template file names (``GET /api/userdata/workflows/<file>``).
FLOW_TEMPLATE_FILES = {
    FLOW_T2V: "pika-h3-flex-t2v.json",
    FLOW_FL2VA: "pika-h3-flex-fl2va.json",
    FLOW_REF2VA: "pika-h3-flex-ref2va.json",
}

#: Node classes that carry the text prompt (t2v/fl2va literal, ref2va via a string node).
PROMPT_NODE_CLASSES = ("MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo")

#: Pika's frame grid: 5s -> 124 frames (~5.17s). ``length`` is a frame count, not seconds.
PIKA_FPS = 24
PIKA_MIN_SECONDS = 5
PIKA_MAX_SECONDS = 15
#: Frame count is aligned to a 17-frame grid (``max(5, round(a*24)) + (5 - (... % 17)) % 17``).
PIKA_FRAME_GRID = 17

#: Target pixel budget for one clip (~1 MP) and the size multiple the model wants.
DEFAULT_TARGET_MEGAPIXELS = float(os.environ.get("KOL_VIDEO_MEGAPIXELS", "0.98"))
DEFAULT_SIZE_MULTIPLE = int(os.environ.get("KOL_VIDEO_SIZE_MULTIPLE", "32"))

#: Where templates and node schemas are cached between runs.
CACHE_DIR = Path(os.path.expanduser("~/.cache/kol/comfy"))

#: Human-readable model label recorded in the Prompt Ledger.
PIKA_MODEL_LABEL = os.environ.get("KOL_VIDEO_MODEL", "Pika-H3-Flex-MiniMax-H3")

#: Version of the prompt binding (the text prepended to the KOL prompt before it is sent).
#: It is part of the clip fingerprint, so changing the binding re-renders the cached clips
#: instead of leaving artifacts that no longer match the code.
PROMPT_BINDING_VERSION = 2

#: Resolution tiers the pipeline asks for, mapped onto the provider's pixel budget.
RESOLUTION_MEGAPIXELS = {"768P": 0.98, "1080P": 2.07}


def resolution_megapixels(resolution: Optional[str]) -> float:
    """Pixel budget for a resolution tier (``768P`` -> ~1 MP, ``1080P`` -> ~2 MP)."""
    return RESOLUTION_MEGAPIXELS.get(str(resolution or "").upper(), RESOLUTION_MEGAPIXELS["768P"])


def normalize_duration(duration: float, resolution: Optional[str] = None) -> int:
    """Map a requested duration onto Pika's contract: whole seconds between 5 and 15."""
    seconds = int(round(float(duration)))
    return max(PIKA_MIN_SECONDS, min(PIKA_MAX_SECONDS, seconds))


def is_retryable_error(exc: BaseException) -> bool:
    """True when another (paid) attempt is worth it: transient faults only."""
    from pipeline.config import ConfigurationError  # local import: avoids a cycle at import time
    from pipeline.offline import OfflineNetworkError

    if isinstance(exc, (OfflineNetworkError, ConfigurationError)):
        return False
    if isinstance(exc, ComfyAuthError):
        return False  # the credentials are wrong: a retry cannot fix that
    if isinstance(exc, ComfyValidationError):
        return False  # the graph is wrong: a retry cannot fix that
    if isinstance(exc, (FileNotFoundError, PermissionError, ValueError)):
        return False
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 425, 429) or exc.code >= 500
    return True


class ComfyVideoError(RuntimeError):
    """A gateway failure that prevented a clip from being produced."""


class ComfyValidationError(ComfyVideoError):
    """The gateway rejected the graph (invalid prompt, missing input): retrying cannot help."""


class ComfyAuthError(ComfyVideoError):
    """The gateway refused the credentials (401/403): retrying cannot help."""


class ComfyAccessError(ComfyVideoError):
    """Cloudflare Access answered with its sign-in page instead of the gateway.

    Usually a transient edge hiccup (or a missing service-token header), so the shot may be
    retried; the headers are re-read from the environment on every attempt.
    """


# --------------------------------------------------------------------------- credentials

def _read_dotenv(path: Path) -> Dict[str, str]:
    """Parse ``KEY=VALUE`` lines from a dotenv-style file."""
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("'\"")
    except OSError:
        return values
    return values


def _agent_env() -> Dict[str, str]:
    """``~/.agents/.env`` (the shared agent environment) as a dict."""
    return _read_dotenv(Path(os.path.expanduser("~/.agents/.env")))


def _ckit_config() -> Dict[str, Any]:
    path = Path(os.path.expanduser("~/.config/ckit/config.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def gateway_url() -> str:
    """Base URL of the Comfy Colab Kit gateway."""
    env = _agent_env()
    cfg = _ckit_config()
    url = (
        os.environ.get("COMFY_GATEWAY_URL")
        or env.get("COMFY_GATEWAY_URL")
        or os.environ.get("CKIT_URL")
        or env.get("CKIT_URL")
        or cfg.get("default_endpoint")
        or COMFY_GATEWAY_URL
    )
    return str(url).rstrip("/")


def gateway_token() -> str:
    """Agent token for the gateway (``ConfigurationError`` when unset)."""
    env = _agent_env()
    cfg = _ckit_config()
    token = (
        os.environ.get("COMFY_GATEWAY_TOKEN")
        or env.get("COMFY_GATEWAY_TOKEN")
        or os.environ.get("CKIT_TOKEN")
        or env.get("CKIT_TOKEN")
        or cfg.get("token")
        or COMFY_GATEWAY_TOKEN
    )
    if not token:
        raise ConfigurationError(
            "COMFY_GATEWAY_TOKEN is not set. Export it, put it in .env, or in ~/.config/ckit/config.json."
        )
    return str(token)


def has_gateway_token() -> bool:
    """True when a gateway token is configured (without raising)."""
    env = _agent_env()
    cfg = _ckit_config()
    token = (
        os.environ.get("COMFY_GATEWAY_TOKEN")
        or env.get("COMFY_GATEWAY_TOKEN")
        or os.environ.get("CKIT_TOKEN")
        or env.get("CKIT_TOKEN")
        or cfg.get("token")
    )
    return bool(token)


def gateway_headers() -> Dict[str, str]:
    """Request headers: agent token + Cloudflare Access service token."""
    env = _agent_env()
    headers = {
        "User-Agent": "kol-comfy-video/1.0",
        "Authorization": f"Bearer {gateway_token()}",
    }
    client_id = os.environ.get("CF_ACCESS_CLIENT_ID") or env.get("CF_ACCESS_CLIENT_ID") or ""
    secret = os.environ.get("CF_ACCESS_CLIENT_SECRET") or env.get("CF_ACCESS_CLIENT_SECRET") or ""
    secret_file = os.environ.get("CF_ACCESS_CLIENT_SECRET_FILE") or env.get("CF_ACCESS_CLIENT_SECRET_FILE") or ""
    if secret_file and not secret:
        path = Path(os.path.expandvars(os.path.expanduser(secret_file)))
        if path.is_file():
            secret = path.read_text(encoding="utf-8").strip()
    if client_id and secret:
        headers["CF-Access-Client-Id"] = client_id
        headers["CF-Access-Client-Secret"] = secret
    return headers


# --------------------------------------------------------------------------- transport

def _request(
    path: str,
    *,
    method: str = "GET",
    body: Optional[bytes] = None,
    content_type: Optional[str] = None,
    timeout: int = 120,
    operation: str = "comfy.request",
) -> Tuple[int, bytes]:
    """One HTTP call against the gateway; returns ``(status, raw_body)``."""
    guard_network(operation, path)
    headers = gateway_headers()
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(gateway_url() + path, data=body, headers=headers, method=method)
    try:
        with guarded_urlopen(req, operation=operation, timeout=timeout) as resp:
            return getattr(resp, "status", 200), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json_request(
    path: str,
    *,
    method: str = "GET",
    payload: Optional[dict] = None,
    timeout: int = 120,
    operation: str = "comfy.request",
) -> Tuple[int, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    status, raw = _request(
        path,
        method=method,
        body=body,
        content_type="application/json" if body is not None else None,
        timeout=timeout,
        operation=operation,
    )
    text = raw.decode("utf-8", "replace")
    if not text.strip():
        return status, {}
    try:
        return status, json.loads(text)
    except ValueError:
        if "text/html" in text[:200] or "Cloudflare" in text[:400]:
            raise ComfyAccessError(
                "Cloudflare Access intercepted the request (sign-in page returned). "
                "Set CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET_FILE for the gateway."
            ) from None
        return status, {"raw": text[:500]}


# --------------------------------------------------------------------------- templates

def _cached_json(name: str, fetch) -> Dict[str, Any]:
    """Fetch a JSON document once and cache it under ``~/.cache/kol/comfy``."""
    path = CACHE_DIR / name
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    data = fetch()
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return data


def load_object_info() -> Dict[str, Any]:
    """Node schemas (``/object_info``), cached between runs."""
    def _fetch() -> Dict[str, Any]:
        status, data = _json_request("/object_info", timeout=180, operation="comfy.object_info")
        if status != 200 or not isinstance(data, dict):
            raise ComfyVideoError(f"GET /object_info failed ({status})")
        return data

    return _cached_json("object_info.json", _fetch)


def fetch_template(flow: str) -> Dict[str, Any]:
    """The gateway's UI workflow template for ``flow`` (cached between runs)."""
    filename = FLOW_TEMPLATE_FILES.get(flow)
    if filename is None:
        raise ComfyVideoError(f"Unknown flow '{flow}'. Known: {sorted(FLOW_TEMPLATE_FILES)}")

    def _fetch() -> Dict[str, Any]:
        status, data = _json_request(
            f"/api/userdata/workflows/{filename}", timeout=120, operation="comfy.fetch_template"
        )
        if status != 200 or not isinstance(data, dict) or "nodes" not in data:
            raise ComfyVideoError(f"GET workflow {filename} failed ({status})")
        return data

    return _cached_json(f"workflow_{filename}", _fetch)


# --------------------------------------------------------------------------- uploads

def upload_image(image_path: str | Path) -> str:
    """Upload a local image to the ComfyUI input dir; returns its stored file name."""
    path = Path(image_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        raise FileNotFoundError(f"Image file not found: {path}")
    boundary = f"----kolComfyBoundary{uuid.uuid4().hex}"
    blob = path.read_bytes()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            blob,
            f"\r\n--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n',
            f"--{boundary}--\r\n".encode(),
        ]
    )
    status, raw = _request(
        "/upload/image",
        method="POST",
        body=body,
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout=180,
        operation="comfy.upload_image",
    )
    text = raw.decode("utf-8", "replace")
    if status >= 400:
        raise ComfyVideoError(f"Upload failed ({status}): {text[:300]}")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ComfyVideoError(f"Upload returned non-JSON: {text[:200]}") from exc
    name = data.get("name")
    if not name:
        raise ComfyVideoError(f"Upload response has no file name: {text[:200]}")
    subfolder = data.get("subfolder") or ""
    return f"{subfolder}/{name}" if subfolder else str(name)


# --------------------------------------------------------------------------- geometry

def frames_for_duration(seconds: float) -> int:
    """Pika's frame grid: seconds -> frame count (``5s`` -> ``124`` frames ~= ``5.17s``)."""
    base = max(PIKA_MIN_SECONDS, int(round(float(seconds) * PIKA_FPS)))
    return base + (5 - (base % PIKA_FRAME_GRID)) % PIKA_FRAME_GRID


def fit_resolution(
    aspect_ratio: str = "9:16",
    *,
    megapixels: float = DEFAULT_TARGET_MEGAPIXELS,
    multiple: int = DEFAULT_SIZE_MULTIPLE,
    reference_size: Optional[Tuple[int, int]] = None,
) -> Tuple[int, int]:
    """Pixel size for one clip: the shot's aspect ratio, ~``megapixels`` big, ``multiple``-aligned.

    ``reference_size`` (the first frame's own size) wins over ``aspect_ratio`` when given, so
    an image-to-video clip keeps the keyframe's framing instead of being re-framed.
    """
    if reference_size and reference_size[0] > 0 and reference_size[1] > 0:
        ratio = reference_size[0] / reference_size[1]
    else:
        try:
            num, den = str(aspect_ratio).split(":")
            ratio = float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            ratio = 9 / 16
    area = max(0.05, megapixels) * 1_000_000
    width = (area * ratio) ** 0.5
    height = (area / ratio) ** 0.5
    aligned_w = max(multiple, int(round(width / multiple)) * multiple)
    aligned_h = max(multiple, int(round(height / multiple)) * multiple)
    return aligned_w, aligned_h


def image_size(image_path: Optional[str | Path]) -> Optional[Tuple[int, int]]:
    """``(width, height)`` of a local image, or ``None`` when it cannot be read."""
    if not image_path:
        return None
    path = Path(image_path)
    try:
        from PIL import Image  # noqa: PLC0415  (optional dependency)

        with Image.open(path) as img:
            return int(img.width), int(img.height)
    except Exception:
        return None


# --------------------------------------------------------------------------- prompts

def compose_prompt(
    flow: str,
    prompt: str,
    *,
    references: int = 0,
    has_last_frame: bool = False,
) -> str:
    """Bind the KOL prompt to the flow's own contract.

    - ``t2v``: the spatial prompt as is.
    - ``fl2va``: states that the clip continues the provided first frame (and, when a last
      frame is supplied, that it ends exactly on it).
    - ``ref2va``: declares the identity anchor as ``<Picture 1>`` (the model's own reference
      syntax) so the anchor actually conditions the render.
    """
    text = (prompt or "").strip()
    if flow == FLOW_REF2VA and references > 0:
        binding = (
            "subject_definitions:\n"
            "<Subject 1> is the person shown in <Picture 1>. Reference role: identity anchor. "
            "Follow their face, hairstyle and skin tone exactly as shown in <Picture 1>.\n"
        )
        if references > 1:
            binding += (
                "<Subject 2> is the styling shown in <Picture 2>. Reference role: wardrobe anchor. "
                "Keep the clothing, colours and styling exactly as shown in <Picture 2>.\n"
            )
        return binding + "\n" + text
    if flow == FLOW_FL2VA:
        if has_last_frame:
            binding = (
                "The clip starts exactly on the provided first frame and ends exactly on the "
                "provided last frame. Keep the framing, wardrobe and identity of both frames "
                "unchanged.\n\n"
            )
        else:
            binding = (
                "The clip starts exactly on the provided first frame and continues that same "
                "framing, wardrobe and identity.\n\n"
            )
        return binding + text
    return text


# --------------------------------------------------------------------------- graph building

def build_graph(
    flow: str,
    prompt: str,
    *,
    first_frame: Optional[str] = None,
    last_frame: Optional[str] = None,
    references: Sequence[str] = (),
    width: int,
    height: int,
    length: int,
    seed: Optional[int] = None,
    filename_prefix: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Build the API-format graph for one shot.

    ``first_frame``/``last_frame`` are ComfyUI input file names; ``references`` are the
    reference image file names (identity anchors) for ``ref2va``.
    """
    template = fetch_template(flow)
    oi = load_object_info()
    graph = convert(template, oi)

    prompt_node_id = None
    for node_id in nodes_by_class(graph, "MiniMaxH3ImageToVideo"):
        prompt_node_id = node_id
        break
    if prompt_node_id is None:
        for node_id in nodes_by_class(graph, "MiniMaxH3ReferenceToVideo"):
            prompt_node_id = node_id
            break
    if prompt_node_id is None:
        raise ComfyVideoError(f"Template {flow} has no MiniMax H3 prompt node")

    # -- prompt: literal on the model node, or the string node it is linked to
    # (``prompt`` is the exact text to send; the caller composes the reference binding).
    text = prompt
    prompt_value = graph[prompt_node_id]["inputs"].get("prompt")
    if isinstance(prompt_value, list) and prompt_value:
        target = str(prompt_value[0])
        target_node = graph.get(target)
        if target_node is None:
            raise ComfyVideoError(f"Prompt link target '{target}' missing from the {flow} graph")
        target_node["inputs"]["value"] = text
    else:
        graph[prompt_node_id]["inputs"]["prompt"] = text

    # -- geometry and length become literals (the template computes them from widgets)
    graph[prompt_node_id]["inputs"]["width"] = int(width)
    graph[prompt_node_id]["inputs"]["height"] = int(height)
    graph[prompt_node_id]["inputs"]["length"] = int(length)

    # -- seed
    for node in graph.values():
        if node["class_type"] == "RandomNoise":
            node["inputs"]["noise_seed"] = int(seed) if seed is not None else node["inputs"].get("noise_seed", 0)

    # -- images
    if flow == FLOW_FL2VA:
        if first_frame:
            if not set_linked_image(graph, prompt_node_id, "first_frame", first_frame):
                raise ComfyVideoError("fl2va graph has no first_frame LoadImage to point at")
        if last_frame:
            if not set_linked_image(graph, prompt_node_id, "last_frame", last_frame):
                raise ComfyVideoError("fl2va graph has no last_frame LoadImage to point at")
        else:
            drop_input(graph, prompt_node_id, "last_frame")
    elif flow == FLOW_REF2VA:
        if not references:
            raise ComfyVideoError("ref2va needs at least one reference image")
        for index, filename in enumerate(references[:9]):
            key = f"ref_images.ref_image_{index}"
            if not set_linked_image(graph, prompt_node_id, key, filename):
                # more references than the template wires: add the loader and the link
                loader_id = f"ref{index + 1}"
                add_load_image(graph, filename, loader_id)
                graph[prompt_node_id]["inputs"][key] = [loader_id, 0]
        for index in range(len(references), 9):
            drop_input(graph, prompt_node_id, f"ref_images.ref_image_{index}")

    # -- output naming
    for node in graph.values():
        if node["class_type"] == "SaveVideo" and filename_prefix:
            node["inputs"]["filename_prefix"] = filename_prefix

    return graph


# --------------------------------------------------------------------------- run

def submit_graph(graph: Dict[str, Dict[str, Any]]) -> str:
    """Queue an API-format graph; returns the ComfyUI ``prompt_id``."""
    started = time.monotonic()
    status, data = _json_request(
        "/prompt", method="POST", payload={"prompt": graph}, timeout=180, operation="comfy.submit"
    )
    error = None
    prompt_id = None
    if status >= 400:
        error = f"HTTP {status}: {json.dumps(data, ensure_ascii=False)[:600]}"
        details = data.get("error") if isinstance(data, dict) else {}
        kind = (details or {}).get("type") if isinstance(details, dict) else None
        if kind in {"prompt_outputs_failed_validation", "prompt_no_outputs", "prompt_invalid_inputs"}:
            raise ComfyValidationError(error)
        if status in (401, 403):
            raise ComfyAuthError(error)
        raise ComfyVideoError(error)
    prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
    if not prompt_id:
        raise ComfyVideoError(f"Gateway accepted the graph but returned no prompt_id: {str(data)[:300]}")
    telemetry.record_api_call(
        "comfy.submit",
        endpoint=f"{gateway_url()}/prompt",
        method="POST",
        request={"nodes": len(graph)},
        response={"prompt_id": prompt_id},
        status=status,
        ok=True,
        duration_seconds=time.monotonic() - started,
    )
    return str(prompt_id)


def poll_and_download_video(
    prompt_id: str,
    output_path: str | Path,
    timeout_seconds: int = 900,
    poll_interval: float = 5.0,
    *,
    shot_id: Optional[str] = None,
) -> str:
    """Wait for a queued graph to finish and download the rendered clip atomically."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    polls = 0
    last_status = "queued"
    while time.time() - started < timeout_seconds:
        time.sleep(poll_interval)
        polls += 1
        status, data = _json_request(
            f"/history/{prompt_id}", timeout=60, operation="comfy.poll"
        )
        if status != 200:
            continue
        item = (data or {}).get(prompt_id)
        if not item:
            continue
        state = item.get("status") or {}
        last_status = str(state.get("status_str") or "running")
        if not state.get("completed"):
            continue
        if last_status != "success":
            messages = state.get("messages") or []
            raise ComfyVideoError(
                f"Graph execution failed: {json.dumps(messages, ensure_ascii=False)[:600]}"
            )
        files = _output_files(item)
        if not files:
            raise ComfyVideoError("Graph finished but produced no video file")
        file_info = files[0]
        _download_output(file_info, out_path)
        telemetry.record_api_call(
            "comfy.poll",
            endpoint=f"{gateway_url()}/history/{prompt_id}",
            method="GET",
            request={"prompt_id": prompt_id, "timeout_seconds": timeout_seconds},
            response={"output": str(out_path), "polls": polls, "metadata": file_info.get("metadata")},
            status="ok",
            ok=True,
            duration_seconds=time.time() - started,
            stage=5,
            shot_id=shot_id,
        )
        return str(out_path)
    telemetry.record_api_call(
        "comfy.poll",
        endpoint=f"{gateway_url()}/history/{prompt_id}",
        method="GET",
        request={"prompt_id": prompt_id, "timeout_seconds": timeout_seconds},
        response={"status": last_status, "polls": polls},
        status="timeout",
        ok=False,
        duration_seconds=time.time() - started,
        stage=5,
        shot_id=shot_id,
    )
    raise TimeoutError(f"Video generation timed out after {timeout_seconds} seconds ({prompt_id}).")


def _output_files(history: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The media files a finished run produced (video first)."""
    files: List[Dict[str, Any]] = []
    for node_out in (history.get("outputs") or {}).values():
        for key in ("videos", "gifs", "images"):
            for item in node_out.get(key) or []:
                if item.get("filename"):
                    files.append(item)
        for item in node_out.get("files") or []:
            if item.get("filename"):
                files.append(item)
    return files


def _download_output(file_info: Dict[str, Any], out_path: Path) -> None:
    """Download one rendered file to ``out_path`` (write to ``.part`` then rename)."""
    query = urllib.parse.urlencode(
        {
            "filename": file_info.get("filename", ""),
            "subfolder": file_info.get("subfolder", ""),
            "type": file_info.get("type", "output"),
        }
    )
    part = out_path.with_name(out_path.name + ".part")
    guard_network("comfy.download", query)
    req = urllib.request.Request(f"{gateway_url()}/view?{query}", headers=gateway_headers())
    try:
        with guarded_urlopen(req, operation="comfy.download", timeout=600) as resp:
            part.write_bytes(resp.read())
        os.replace(part, out_path)
    finally:
        if part.exists():
            part.unlink()


def render_clip(
    flow: str,
    prompt: str,
    output_path: str | Path,
    *,
    first_frame: Optional[str | Path] = None,
    last_frame: Optional[str | Path] = None,
    references: Sequence[str | Path] = (),
    duration: float = 6.0,
    aspect_ratio: str = "9:16",
    seed: Optional[int] = None,
    filename_prefix: Optional[str] = None,
    timeout_seconds: int = 900,
    poll_interval: float = 5.0,
    shot_id: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Render one clip end to end: upload, build the graph, queue it, wait, download.

    Returns ``(prompt_id, info)`` where ``info`` carries the resolution, frame count and the
    uploaded file names that were sent.
    """
    first_name = upload_image(first_frame) if first_frame else None
    last_name = upload_image(last_frame) if last_frame else None
    reference_names = [upload_image(ref) for ref in references]

    size = image_size(first_frame)
    width, height = fit_resolution(aspect_ratio, reference_size=size)
    length = frames_for_duration(duration)

    graph = build_graph(
        flow,
        compose_prompt(flow, prompt, references=len(reference_names)),
        first_frame=first_name,
        last_frame=last_name,
        references=reference_names,
        width=width,
        height=height,
        length=length,
        seed=seed,
        filename_prefix=filename_prefix or f"kol/{shot_id or 'clip'}",
    )
    prompt_id = submit_graph(graph)
    poll_and_download_video(
        prompt_id,
        output_path,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
        shot_id=shot_id,
    )
    info = {
        "prompt_id": prompt_id,
        "flow": flow,
        "width": width,
        "height": height,
        "length": length,
        "fps": PIKA_FPS,
        "duration_seconds": round(length / PIKA_FPS, 3),
        "first_frame": first_name,
        "last_frame": last_name,
        "references": reference_names,
        "nodes": len(graph),
    }
    return prompt_id, info
