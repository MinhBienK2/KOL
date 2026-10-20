"""Speech Intelligibility: automatic speech recognition (ASR) round-trip for voice stems.

Stage 6 synthesises the Vietnamese voiceover with a neural TTS endpoint but nothing proves the
result is intelligible or says what the script says. :func:`transcribe` sends a stem to the
OpenAI-compatible ``/v1/audio/transcriptions`` endpoint (``whisper-1``) of the same gateway, and
:func:`speech_match` scores the transcript against the scripted text.

Metric choice. Vietnamese is written with spaces between *syllables*, and Whisper regularly
splits/merges syllables and drops tone marks differently from the script, so word error rate
(WER) over-penalises harmless variation. Character error rate (CER, computed on the normalised
text with whitespace removed) is the **primary** metric. WER and an accent-insensitive CER
(``cer_unaccented``, diacritics stripped, ``đ`` -> ``d``) are reported as secondary diagnostics:
a stem whose ``cer`` is bad but ``cer_unaccented`` is good is understandable but mis-toned.

Threshold: ``ok`` means ``cer <= SPEECH_CER_THRESHOLD`` (0.35). Clean neural TTS round-tripped
through Whisper typically lands at 0.05-0.20 CER on Vietnamese; 0.35 tolerates ASR tone-mark
errors and numerals/brand names, while garbled, wrong-language or empty audio scores >= 0.6.
"""

from __future__ import annotations

import json
import mimetypes
import re
import subprocess
import tempfile
import unicodedata
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Sequence

from pipeline import config
from pipeline.offline import OfflineNetworkError, guarded_urlopen

__all__ = [
    "ASRError",
    "ASR_MODEL",
    "SPEECH_CER_THRESHOLD",
    "normalize_text",
    "speech_match",
    "transcribe",
]

ASR_MODEL = "whisper-1"
#: Transport failures (timeouts, resets) are retried; HTTP error responses are not.
UPLOAD_ATTEMPTS = 2
#: Maximum character error rate (primary metric) for a voice stem to count as intelligible.
SPEECH_CER_THRESHOLD = 0.35


class ASRError(RuntimeError):
    """The transcription endpoint failed or returned something unusable."""


def transcribe(audio_path: str | Path, language: str = "vi", *, timeout: float = 60.0) -> str:
    """Transcribe ``audio_path`` with ``whisper-1`` and return the text.

    Raises :class:`OfflineNetworkError` while offline and :class:`ASRError` for transport,
    HTTP or response-format failures (callers decide whether that is fatal).
    """
    path = Path(audio_path)
    if not path.is_file():
        raise ASRError(f"audio file not found: {path}")
    url = f"{config.MINIMAX_BASE_URL}/v1/audio/transcriptions"
    with tempfile.TemporaryDirectory() as tmp:
        # 48kHz stereo WAV stems are ~10x larger than needed and time out on upload; Whisper wants 16kHz mono.
        upload = _compact_for_upload(path, Path(tmp))
        boundary = f"----kol{uuid.uuid4().hex}"
        body = _multipart(
            boundary,
            fields={"model": ASR_MODEL, "language": language, "response_format": "json"},
            file_field="file",
            file_path=upload,
        )
    raw = b""
    last_exc: Exception | None = None
    for _attempt in range(UPLOAD_ATTEMPTS):
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {config.MINIMAX_API_KEY}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "Mozilla/5.0",
            },
        )
        try:
            with guarded_urlopen(req, operation="asr.transcribe", timeout=timeout) as resp:
                raw = resp.read()
            last_exc = None
            break
        except OfflineNetworkError:
            raise
        except urllib.error.HTTPError as exc:  # the server answered: retrying will not help
            raise ASRError(f"transcription request failed: {exc}") from exc
        except Exception as exc:
            last_exc = exc
    if last_exc is not None:
        raise ASRError(f"transcription request failed: {last_exc}") from last_exc
    try:
        text = json.loads(raw.decode("utf-8")).get("text")
    except (ValueError, AttributeError, UnicodeDecodeError) as exc:
        raise ASRError(f"unexpected transcription response: {exc}") from exc
    if not isinstance(text, str):
        raise ASRError("transcription response has no 'text' field")
    return text.strip()



def _compact_for_upload(path: Path, tmp_dir: Path) -> Path:
    """Re-encode to 16kHz mono MP3 for upload; fall back to the original file if ffmpeg fails."""
    out = tmp_dir / f"{path.stem}.mp3"
    res = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-b:a", "48k", str(out)],
        capture_output=True,
    )
    return out if res.returncode == 0 and out.is_file() and out.stat().st_size > 0 else path

def _multipart(boundary: str, fields: Dict[str, str], file_field: str, file_path: Path) -> bytes:
    parts: list[bytes] = []
    for name, value in fields.items():
        parts += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"'.encode(),
            b"",
            str(value).encode("utf-8"),
        ]
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts += [
        f"--{boundary}".encode(),
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"'.encode(),
        f"Content-Type: {ctype}".encode(),
        b"",
        file_path.read_bytes(),
        f"--{boundary}--".encode(),
        b"",
    ]
    return b"\r\n".join(parts)


def normalize_text(text: str, *, strip_accents: bool = False) -> str:
    """Lowercase, NFC, drop punctuation/symbols, collapse whitespace.

    ``strip_accents`` additionally removes all diacritics (tone and vowel marks) and maps
    ``đ`` -> ``d`` for the accent-insensitive secondary score.
    """
    text = unicodedata.normalize("NFC", text or "").lower()
    if strip_accents:
        text = unicodedata.normalize("NFD", text).replace("đ", "d")
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        text = unicodedata.normalize("NFC", text)
    text = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def _edit_distance(a: Sequence[Any], b: Sequence[Any]) -> int:
    if not a:
        return len(b)
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def _error_rate(ref: Sequence[Any], hyp: Sequence[Any]) -> float:
    if not ref:
        return 0.0 if not hyp else 1.0
    return _edit_distance(ref, hyp) / len(ref)


def speech_match(expected: str, transcript: str, threshold: float = SPEECH_CER_THRESHOLD) -> Dict[str, Any]:
    """Score ``transcript`` against the scripted ``expected`` text.

    Returns ``{"wer", "cer", "cer_unaccented", "ok"}``. ``ok`` is ``cer <= threshold``;
    CER ignores spaces so syllable splitting differences are not penalised.
    """
    exp, hyp = normalize_text(expected), normalize_text(transcript)
    exp_a = normalize_text(expected, strip_accents=True)
    hyp_a = normalize_text(transcript, strip_accents=True)
    cer = _error_rate(exp.replace(" ", ""), hyp.replace(" ", ""))
    return {
        "wer": round(_error_rate(exp.split(), hyp.split()), 4),
        "cer": round(cer, 4),
        "cer_unaccented": round(_error_rate(exp_a.replace(" ", ""), hyp_a.replace(" ", "")), 4),
        "ok": cer <= threshold,
    }
