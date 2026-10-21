"""Face identity measurement against the Face Anchor (ADR 0004, Face Identity Gate).

Uses OpenCV's built-in DNN face stack, no insightface:

* **YuNet** (``cv2.FaceDetectorYN``) finds faces and their five landmarks.
* **SFace** (``cv2.FaceRecognizerSF``) turns an aligned face crop into a 128-d embedding;
  identity similarity is the cosine of two embeddings.

Both ONNX models come from the public ``opencv/opencv_zoo`` repository (Git LFS, served by
``media.githubusercontent.com``). They are downloaded on demand into a cache directory
(``$KOL_MODEL_DIR`` or ``~/.cache/kol/models``) and verified by size + SHA-256. Downloads go
through :mod:`pipeline.offline`: offline with the models missing raises
:class:`FaceModelsUnavailable`, which the gate reports as ``unverified`` instead of crashing.

Threshold (:data:`FACE_SIMILARITY_THRESHOLD` = 0.363)
-----------------------------------------------------
0.363 is the cosine threshold the OpenCV SFace demo/documentation uses (tuned on LFW for real
photographs). Calibration on this repository's own personas (see ADR 0004): the same persona
across portrait vs. turnaround-sheet face scores 0.54-0.73, different personas score 0.14-0.33.
That gap straddles 0.363 and the documented value sits in it, so we keep it rather than invent a
looser number: a looser threshold (e.g. 0.30) would let a different persona (0.33) pass, which
is the exact failure the gate exists to catch. Generated faces drift more than photos, so for
video clips the gate takes the *best* similarity over several sampled frames (a head turn or
blink in one frame must not fail a clip whose other frames match). Override with
``KOL_FACE_SIMILARITY_THRESHOLD`` for a given deployment.
"""

from __future__ import annotations

import functools
import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence

import cv2
import numpy as np

from pipeline import offline

#: OpenCV's documented SFace cosine-similarity decision threshold (same identity at or above).
DEFAULT_FACE_SIMILARITY_THRESHOLD = 0.363
#: Minimum YuNet confidence for a detection to count as a face.
DETECTION_SCORE_THRESHOLD = 0.6
#: Frames sampled from a clip by default.
DEFAULT_SAMPLE_FRAMES = 10
#: Share of face-bearing frames that must clear the threshold. A clip whose identity drifts after
#: the I2V first frame must fail, so neither the best frame nor a single good frame is enough.
MIN_PASSING_FRAME_RATIO = 0.8

_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"


@dataclass(frozen=True)
class ModelSpec:
    filename: str
    url: str
    size: int
    sha256: str


DETECTOR_MODEL = ModelSpec(
    "face_detection_yunet_2023mar.onnx",
    f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    232589,
    "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
)
RECOGNIZER_MODEL = ModelSpec(
    "face_recognition_sface_2021dec.onnx",
    f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    38696353,
    "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
)


class FaceModelsUnavailable(RuntimeError):
    """The YuNet/SFace models are missing and cannot be downloaded (offline or network error)."""


def face_similarity_threshold() -> float:
    raw = os.environ.get("KOL_FACE_SIMILARITY_THRESHOLD", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return DEFAULT_FACE_SIMILARITY_THRESHOLD


def model_cache_dir() -> Path:
    override = os.environ.get("KOL_MODEL_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".cache" / "kol" / "models"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_valid(path: Path, spec: ModelSpec) -> bool:
    # Size first: cheap, and it rejects the tiny Git LFS pointer text a raw.githubusercontent URL returns.
    return path.is_file() and path.stat().st_size == spec.size and _sha256(path) == spec.sha256


def ensure_model(spec: ModelSpec, cache_dir: Optional[Path] = None) -> Path:
    """Path to a verified model file, downloading it on first use.

    Raises :class:`FaceModelsUnavailable` when it is absent/corrupt and cannot be fetched.
    """
    directory = Path(cache_dir) if cache_dir is not None else model_cache_dir()
    target = directory / spec.filename
    if _is_valid(target, spec):
        return target
    try:
        directory.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        offline.guarded_urlretrieve(spec.url, partial, operation=f"face model download ({spec.filename})")
        if not _is_valid(partial, spec):
            partial.unlink(missing_ok=True)
            raise FaceModelsUnavailable(f"{spec.filename}: downloaded file failed size/SHA-256 check")
        partial.replace(target)
    except FaceModelsUnavailable:
        raise
    except Exception as exc:  # OfflineNetworkError, URLError, OSError ...
        raise FaceModelsUnavailable(f"{spec.filename} unavailable ({type(exc).__name__}: {exc})") from exc
    return target


def models_available(cache_dir: Optional[Path] = None) -> bool:
    """True when both models are cached and valid (never downloads)."""
    directory = Path(cache_dir) if cache_dir is not None else model_cache_dir()
    return all(_is_valid(directory / s.filename, s) for s in (DETECTOR_MODEL, RECOGNIZER_MODEL))


_lock = threading.Lock()


@functools.lru_cache(maxsize=1)
def _recognizer(cache_key: str) -> Any:
    return cv2.FaceRecognizerSF.create(str(ensure_model(RECOGNIZER_MODEL)), "")


def _detect_faces(image_bgr: np.ndarray) -> np.ndarray:
    """YuNet detections (N x 15) for the image, largest face first; empty array when none."""
    height, width = image_bgr.shape[:2]
    detector = cv2.FaceDetectorYN.create(
        str(ensure_model(DETECTOR_MODEL)), "", (width, height), DETECTION_SCORE_THRESHOLD
    )
    _, faces = detector.detect(image_bgr)
    if faces is None or len(faces) == 0:
        return np.empty((0, 15), dtype=np.float32)
    return faces[np.argsort(-(faces[:, 2] * faces[:, 3]))]


def embed_face(image_bgr: np.ndarray) -> Optional[np.ndarray]:
    """SFace embedding (1 x 128) of the largest face in a BGR image, or None when no face is found.

    Raises :class:`FaceModelsUnavailable` if the models cannot be obtained.
    """
    if image_bgr is None or image_bgr.size == 0:
        return None
    with _lock:
        faces = _detect_faces(image_bgr)
        if len(faces) == 0:
            return None
        recognizer = _recognizer(str(model_cache_dir()))
        return recognizer.feature(recognizer.alignCrop(image_bgr, faces[0]))


def face_yaw(face: np.ndarray) -> float:
    """Head-turn proxy from a YuNet row: nose offset from the eye midpoint over the eye distance.

    About 0 for a frontal face, 0.3+ for a three-quarter turn, near 1 in profile.
    """
    right_eye, left_eye, nose = face[4:6], face[6:8], face[8:10]
    eye_distance = max(1.0, abs(float(left_eye[0] - right_eye[0])))
    return abs(float(nose[0] - (right_eye[0] + left_eye[0]) / 2)) / eye_distance


def embed_face_with_yaw(image_bgr: np.ndarray) -> Optional[tuple[np.ndarray, float]]:
    """``(embedding, yaw)`` of the largest face, or None when no face is found."""
    if image_bgr is None or image_bgr.size == 0:
        return None
    with _lock:
        faces = _detect_faces(image_bgr)
        if len(faces) == 0:
            return None
        recognizer = _recognizer(str(model_cache_dir()))
        return recognizer.feature(recognizer.alignCrop(image_bgr, faces[0])), face_yaw(faces[0])


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    va, vb = np.asarray(a, dtype=np.float64).ravel(), np.asarray(b, dtype=np.float64).ravel()
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom else 0.0


def read_image(path: str | Path) -> Optional[np.ndarray]:
    return cv2.imread(str(path), cv2.IMREAD_COLOR)


def identity_similarity(anchor_path: str | Path, image_path: str | Path) -> Optional[float]:
    """Cosine similarity of the faces in two image files, or None if either has no detectable face."""
    anchor = embed_face(read_image(anchor_path))
    other = embed_face(read_image(image_path))
    if anchor is None or other is None:
        return None
    return cosine_similarity(anchor, other)


def sample_video_frames(video: str | Path, n: int = DEFAULT_SAMPLE_FRAMES) -> List[np.ndarray]:
    """Up to ``n`` BGR frames evenly spread over the clip (at 1/(n+1)..n/(n+1) of its length)."""
    capture = cv2.VideoCapture(str(video))
    frames: List[np.ndarray] = []
    try:
        if not capture.isOpened() or n <= 0:
            return frames
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0:
            ok, frame = capture.read()
            return [frame] if ok else frames
        for k in range(1, n + 1):
            capture.set(cv2.CAP_PROP_POS_FRAMES, min(total - 1, int(total * k / (n + 1))))
            ok, frame = capture.read()
            if ok and frame is not None:
                frames.append(frame)
    finally:
        capture.release()
    return frames


def verify_shot_identity(
    anchor: str | Path | np.ndarray,
    media: str | Path,
    *,
    n_frames: int = DEFAULT_SAMPLE_FRAMES,
    threshold: Optional[float] = None,
) -> dict[str, Any]:
    """Compare the face(s) in an image or video against the Face Anchor.

    ``anchor`` is an image path or a precomputed embedding. For a video the *median* similarity over
    ``n_frames`` sampled frames is reported, and the clip passes only when at least
    ``MIN_PASSING_FRAME_RATIO`` of the face-bearing frames clear the threshold. Returns
    ``{"similarity", "min_similarity", "passing_ratio", "face_found", "passed", "frames_checked",
    "frames_with_face", "threshold"}``; ``similarity`` is None when no face was found. Raises :class:`FaceModelsUnavailable` if the models cannot be obtained.
    """
    limit = face_similarity_threshold() if threshold is None else threshold
    anchor_emb = anchor if isinstance(anchor, np.ndarray) else embed_face(read_image(anchor))
    if anchor_emb is None:
        raise ValueError(f"No face detected in the Face Anchor: {anchor}")

    path = Path(media)
    if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}:
        frames: Sequence[np.ndarray] = sample_video_frames(path, n_frames)
    else:
        image = read_image(path)
        frames = [] if image is None else [image]

    scores: List[float] = []
    for frame in frames:
        embedding = embed_face(frame)
        if embedding is not None:
            scores.append(cosine_similarity(anchor_emb, embedding))
    median = float(np.median(scores)) if scores else None
    passing_ratio = (sum(score >= limit for score in scores) / len(scores)) if scores else 0.0
    return {
        "similarity": None if median is None else round(median, 4),
        "min_similarity": round(min(scores), 4) if scores else None,
        "passing_ratio": round(passing_ratio, 3),
        "face_found": median is not None,
        "passed": median is not None and passing_ratio >= MIN_PASSING_FRAME_RATIO,
        "frames_checked": len(frames),
        "frames_with_face": len(scores),
        "threshold": limit,
    }
