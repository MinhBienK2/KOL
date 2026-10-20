"""Step 8: Independent Verification Gates & Commercial Release Packaging."""

from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from PIL import Image
from pipeline import telemetry
from pipeline.config import (
    ARTIFACTS_DIR,
    BASE_DIR,
    CHARACTER_PATH,
    OUTPUT_DIR,
)
from pipeline.schemas import (
    AssetManifestArtifact,
    GateVerificationResult,
    PublishLogArtifact,
    RenderReportArtifact,
    ScenePlanArtifact,
    ScriptArtifact,
)
from pipeline.workspace import ProjectWorkspace
from pipeline.slideshow_risk import score_slideshow_risk

STAGE_VERIFICATION = telemetry.stage_number("verification_publish")

# Media Quality Gate thresholds (ffmpeg blackdetect / freezedetect / ebur128).
MAX_BLACK_SECONDS = 1.0  # total black picture tolerated (fade in/out); longer is a render defect
MAX_FROZEN_SECONDS = 2.0  # one frozen hold this long means a static slide or stalled diffusion clip
MAX_FROZEN_SHARE = 0.20  # ...or this share of the runtime spent on short held still frames
FREEZE_NOISE_TOLERANCE = 0.003
TARGET_LUFS = -14.0  # the composer's delivery target for TikTok / Reels / Shorts
LUFS_TOLERANCE = 3.0
TRUE_PEAK_CEILING_DBTP = 0.0  # above this the master is clipping
SILENT_LUFS = -50.0
THUMBNAIL_MAX_TIMESTAMP = 18.0

#: Max disagreement between stage 7's audio_mix_report.json and the loudness re-measured on the master.
MIX_REPORT_LUFS_AGREEMENT = 1.0
#: A voice stem whose peak is at or below this is digital silence (a placeholder for failed TTS).
SILENT_STEM_MAX_DB = -60.0

#: Generation modes that mean "no real diffusion output" (matched case-insensitively).
PLACEHOLDER_MODES = frozenset({"LOCAL_FFMPEG", "FFMPEG", "PLACEHOLDER"})

#: ``overall_status`` values. DRAFT: a complete master that contains placeholders; watchable, never released.
STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_DRAFT = "DRAFT"
PLACEHOLDER_GATE_NAME = "prompt_ledger_audit_gate"

# technical, media quality, character sheet integrity, character consistency, continuity, slideshow risk,
# identity pre-flight audit, prompt ledger audit
VERIFICATION_GATE_COUNT = 8


def _ensure_stage_started(total: int) -> None:
    """Open the verification stage with its gate total, unless the director already did."""
    recorder = telemetry.current()
    if recorder is not None and recorder.snapshot().get("current_stage") == STAGE_VERIFICATION:
        return
    telemetry.start_stage(STAGE_VERIFICATION, total=total)


def verify_technical_gate(video_path: str | Path) -> GateVerificationResult:
    """Verifies format, codecs, resolution, and audio parameters via ffprobe."""
    v_path = Path(video_path)
    if not v_path.exists():
        return GateVerificationResult(
            gate_name="technical_integrity_gate",
            passed=False,
            details={},
            error_message=f"Video file does not exist: {v_path}",
        )

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,bit_rate:stream=codec_name,codec_type,width,height,sample_rate,channels",
        "-of",
        "json",
        str(v_path),
    ]

    try:
        raw = subprocess.check_output(cmd).decode("utf-8")
        info = json.loads(raw)
    except Exception as exc:
        return GateVerificationResult(
            gate_name="technical_integrity_gate",
            passed=False,
            details={},
            error_message=f"ffprobe execution failed: {exc}",
        )

    streams = info.get("streams", [])
    format_info = info.get("format", {})

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not v_stream:
        return GateVerificationResult(
            gate_name="technical_integrity_gate",
            passed=False,
            details={"streams": streams},
            error_message="Missing video stream in master MP4",
        )
    if not a_stream:
        return GateVerificationResult(
            gate_name="technical_integrity_gate",
            passed=False,
            details={"streams": streams},
            error_message="Missing audio stream in master MP4",
        )

    width = int(v_stream.get("width", 0))
    height = int(v_stream.get("height", 0))
    v_codec = v_stream.get("codec_name", "")
    a_codec = a_stream.get("codec_name", "")
    sample_rate = int(a_stream.get("sample_rate", 0))
    duration = float(format_info.get("duration", 0.0))
    size_bytes = int(format_info.get("size", 0))

    passed = True
    errors = []

    if (width, height) != (1080, 1920):
        passed = False
        errors.append(f"Expected 1080x1920 (9:16), found {width}x{height}")

    if v_codec != "h264":
        passed = False
        errors.append(f"Expected h264 video codec, found {v_codec}")

    if a_codec != "aac":
        passed = False
        errors.append(f"Expected aac audio codec, found {a_codec}")

    if sample_rate < 44100:
        passed = False
        errors.append(f"Expected audio sample rate >= 44100Hz, found {sample_rate}Hz")

    if duration < 15.0:
        passed = False
        errors.append(f"Expected video duration >= 15s, found {duration:.1f}s")

    details = {
        "width": width,
        "height": height,
        "video_codec": v_codec,
        "audio_codec": a_codec,
        "sample_rate": sample_rate,
        "duration_seconds": duration,
        "size_bytes": size_bytes,
    }

    return GateVerificationResult(
        gate_name="technical_integrity_gate",
        passed=passed,
        details=details,
        error_message="; ".join(errors) if errors else None,
    )

def _parse_media_quality_log(stderr: str) -> dict[str, Any]:
    """Extract black intervals, frozen intervals and the ebur128 summary from an ffmpeg log."""
    black = [
        float(m.group(1))
        for m in re.finditer(r"black_start:\S+\s+black_end:\S+\s+black_duration:([\d.]+)", stderr)
    ]
    freeze_starts = [float(m.group(1)) for m in re.finditer(r"lavfi\.freezedetect\.freeze_start:\s*([\d.]+)", stderr)]
    freeze_durations = [float(m.group(1)) for m in re.finditer(r"lavfi\.freezedetect\.freeze_duration:\s*([\d.]+)", stderr)]
    summary = stderr.rsplit("Summary:", 1)[-1] if "Summary:" in stderr else ""
    integrated = re.search(r"^\s*I:\s+(-?[\d.]+|-inf)\s+LUFS", summary, re.MULTILINE)
    peak = re.search(r"^\s*Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary, re.MULTILINE)

    def _num(match: Optional[re.Match]) -> Optional[float]:
        if match is None:
            return None
        return -120.0 if match.group(1) == "-inf" else float(match.group(1))

    return {
        "black_intervals": black,
        "freeze_starts": freeze_starts,
        "freeze_durations": freeze_durations,
        "integrated_lufs": _num(integrated),
        "true_peak_dbtp": _num(peak),
    }


def _load_fresh_mix_report(mix_report_path: str | Path | None, video_path: Path) -> Optional[Dict[str, Any]]:
    """Stage 7's ``audio_mix_report.json`` if it exists, parses and was written after the master."""
    if mix_report_path is None:
        return None
    path = Path(mix_report_path)
    try:
        if not path.is_file() or path.stat().st_mtime + 1.0 < video_path.stat().st_mtime:
            return None  # absent, or older than the master: it describes a previous render
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "compliant" not in data or not isinstance(data.get("output_lufs"), (int, float)):
        return None
    return data


def verify_media_quality_gate(
    video_path: str | Path, mix_report_path: str | Path | None = None
) -> GateVerificationResult:
    """Perceptual defect scan of the master: black frames, frozen frames and loudness.

    When stage 7's ``audio_mix_report.json`` is present (and not older than the master) its ``compliant``
    verdict is the loudness authority; the master is still measured so a report that does not describe
    this file (> 1 LU apart) is rejected. Without a report the +/- 3 LUFS delivery window applies.

    One ffmpeg pass runs ``blackdetect`` and ``freezedetect`` on the picture and ``ebur128``
    (ITU-R BS.1770 integrated loudness and true peak) on the audio. The Technical Integrity Gate only
    proves the container is well formed; this gate proves the film is not black, not a slideshow that
    stalled, and not silent or off-level.
    """
    v_path = Path(video_path)
    gate_name = "media_quality_gate"
    if not v_path.exists():
        return GateVerificationResult(
            gate_name=gate_name,
            passed=False,
            details={},
            error_message=f"Video file does not exist: {v_path}",
        )

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(v_path),
        "-vf",
        f"blackdetect=d=0.2:pix_th=0.10,freezedetect=n={FREEZE_NOISE_TOLERANCE}:d=1",
        "-af",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    except Exception as exc:
        return GateVerificationResult(
            gate_name=gate_name,
            passed=False,
            details={},
            error_message=f"ffmpeg media analysis failed: {exc}",
        )
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        return GateVerificationResult(
            gate_name=gate_name,
            passed=False,
            details={},
            error_message=f"ffmpeg media analysis exited {proc.returncode}: {stderr.strip()[-200:]}",
        )

    parsed = _parse_media_quality_log(stderr)
    black_seconds = round(sum(parsed["black_intervals"]), 3)

    # freezedetect reports freeze_duration when a freeze ends; a freeze that runs to end of file only
    # reports freeze_start, so its length is the remaining runtime.
    duration_probe = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    total = (
        int(duration_probe.group(1)) * 3600 + int(duration_probe.group(2)) * 60 + float(duration_probe.group(3))
        if duration_probe
        else 0.0
    )
    freeze_intervals = list(parsed["freeze_durations"])
    if len(parsed["freeze_starts"]) > len(parsed["freeze_durations"]) and total:
        freeze_intervals.append(max(0.0, total - parsed["freeze_starts"][-1]))
    frozen_seconds = round(sum(freeze_intervals), 3)
    longest_frozen = round(max(freeze_intervals, default=0.0), 3)
    frozen_share = round(frozen_seconds / total, 3) if total else 0.0

    lufs = parsed["integrated_lufs"]
    peak = parsed["true_peak_dbtp"]
    mix_report = _load_fresh_mix_report(mix_report_path, v_path)
    details: dict[str, Any] = {
        "black_seconds": black_seconds,
        "frozen_seconds": frozen_seconds,
        "longest_frozen_seconds": longest_frozen,
        "frozen_share": frozen_share,
        "frozen_intervals": len(freeze_intervals),
        "integrated_lufs": lufs,
        "true_peak_dbtp": peak,
        "target_lufs": TARGET_LUFS,
        "loudness_source": "audio_mix_report" if mix_report is not None else "measured",
    }
    if mix_report is not None:
        details["mix_report_output_lufs"] = mix_report["output_lufs"]
        details["mix_report_compliant"] = bool(mix_report["compliant"])

    errors: List[str] = []
    if black_seconds > MAX_BLACK_SECONDS:
        errors.append(f"Black picture for {black_seconds:.1f}s (limit {MAX_BLACK_SECONDS:.1f}s)")
    if longest_frozen >= MAX_FROZEN_SECONDS:
        errors.append(
            f"Frozen picture for {longest_frozen:.1f}s in one hold (limit {MAX_FROZEN_SECONDS:.1f}s): "
            "static slide or stalled clip"
        )
    elif frozen_share > MAX_FROZEN_SHARE:
        errors.append(
            f"Frozen picture covers {frozen_share:.0%} of the runtime (limit {MAX_FROZEN_SHARE:.0%}): "
            "clips are being held on a still frame"
        )
    if lufs is None:
        errors.append("Loudness measurement unavailable (no audio stream analysed)")
    elif lufs <= SILENT_LUFS:
        errors.append(f"Loudness {lufs:.1f} LUFS: master is silent")
    elif mix_report is not None:
        if abs(lufs - mix_report["output_lufs"]) > MIX_REPORT_LUFS_AGREEMENT:
            errors.append(
                f"audio_mix_report.json ({mix_report['output_lufs']:.1f} LUFS) does not describe this master "
                f"(measured {lufs:.1f} LUFS)"
            )
        elif not mix_report["compliant"]:
            errors.append(
                f"audio_mix_report.json: mix not compliant ({mix_report['output_lufs']:.1f} LUFS "
                f"vs {TARGET_LUFS:.0f} LUFS target)"
            )
    elif abs(lufs - TARGET_LUFS) > LUFS_TOLERANCE:
        errors.append(
            f"Loudness {lufs:.1f} LUFS outside {TARGET_LUFS:.0f} +/- {LUFS_TOLERANCE:.0f} LUFS delivery target"
        )
    if peak is not None and peak > TRUE_PEAK_CEILING_DBTP:
        errors.append(f"True peak {peak:.1f} dBTP exceeds {TRUE_PEAK_CEILING_DBTP:.0f} dBTP: audio is clipping")

    return GateVerificationResult(
        gate_name=gate_name,
        passed=not errors,
        details=details,
        error_message="; ".join(errors) if errors else None,
    )


def verify_character_sheet_integrity_gate(
    character_file: str | Path = CHARACTER_PATH,
    min_resolution: int = 512,
) -> GateVerificationResult:
    """Tier-1 Pre-flight Gate: Verifies that Character Sheet and Face Anchor meet quality and resolution standards."""
    char_path = Path(character_file)
    if not char_path.is_absolute():
        char_path = BASE_DIR / char_path
    if not char_path.exists():
        return GateVerificationResult(
            gate_name="character_sheet_integrity_gate",
            passed=False,
            details={},
            error_message=f"Character profile not found at {char_path}",
        )

    with open(char_path, "r", encoding="utf-8") as f:
        char_data = json.load(f)

    face_ref = char_data.get("face_anchor") or char_data.get("portrait_image")
    face_path = BASE_DIR / face_ref if face_ref else None
    errors: List[str] = []
    details: dict[str, Any] = {
        "character_name": char_data.get("name"),
        "character_tag": char_data.get("character_tag"),
        "has_face_anchor": False,
        "identities_verified": 0,
        "total_identities": len(char_data.get("identities", [])),
    }

    if not face_path or not face_path.exists():
        errors.append(f"Face anchor image missing: {face_ref}")
    else:
        try:
            with Image.open(face_path) as img:
                fw, fh = img.size
                details["face_anchor_resolution"] = f"{fw}x{fh}"
                details["has_face_anchor"] = True
                if fw < min_resolution or fh < min_resolution:
                    errors.append(f"Face anchor resolution ({fw}x{fh}) below required minimum {min_resolution}px")
        except Exception as exc:
            errors.append(f"Failed to read face anchor image: {exc}")

    verified_identities = 0
    for ident in char_data.get("identities", []):
        sheet_rel = ident.get("character_sheet") or ident.get("reference_sheet") or char_data.get("character_sheet")
        sheet_p = BASE_DIR / sheet_rel if sheet_rel else None
        if not sheet_p or not sheet_p.exists():
            errors.append(f"Identity '{ident.get('identity_id')}' missing character sheet: {sheet_rel}")
            continue
        try:
            with Image.open(sheet_p) as img:
                sw, sh = img.size
                if max(sw, sh) < min_resolution:
                    errors.append(f"Character sheet for '{ident.get('identity_id')}' resolution ({sw}x{sh}) below required {min_resolution}px")
                else:
                    verified_identities += 1
        except Exception as exc:
            errors.append(f"Invalid character sheet image for '{ident.get('identity_id')}': {exc}")

    details["identities_verified"] = verified_identities
    passed = len(errors) == 0 and verified_identities > 0

    return GateVerificationResult(
        gate_name="character_sheet_integrity_gate",
        passed=passed,
        details=details,
        error_message="; ".join(errors) if errors else None,
    )


def verify_character_consistency_gate(
    manifest_path: str | Path,
    character_file: str | Path = CHARACTER_PATH,
) -> GateVerificationResult:
    """Verifies that generated keyframes strictly preserve character identity anchors (Tier-2 Post-flight Audit)."""
    # Tier-1 Character Sheet Integrity Pre-flight check
    tier1 = verify_character_sheet_integrity_gate(character_file)
    if not tier1.passed:
        return GateVerificationResult(
            gate_name="character_consistency_gate",
            passed=False,
            details={"tier1_preflight": tier1.details},
            error_message=f"Pre-flight Character Sheet Integrity Gate FAILED: {tier1.error_message}",
        )

    char_path = Path(character_file)
    if not char_path.is_absolute():
        char_path = BASE_DIR / char_path
    with open(char_path, "r", encoding="utf-8") as f:
        char_data = json.load(f)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    keyframes = manifest_data.get("keyframes", [])
    if not keyframes:
        return GateVerificationResult(
            gate_name="character_consistency_gate",
            passed=False,
            details={"tier1_preflight": tier1.details},
            error_message="No keyframes found in manifest",
        )

    all_exist = True
    watermark_cleaned = True
    generation_modes: dict[str, int] = {}
    for kf in keyframes:
        cleaned_p_str = kf.get("cleaned_image_path")
        if not cleaned_p_str:
            # Product-only shot rendered via direct T2V diffusion (character portrait not applicable)
            continue
        p = Path(cleaned_p_str)
        if not p.exists() or p.stat().st_size == 0:
            all_exist = False
        if not kf.get("watermark_removed", False):
            watermark_cleaned = False
        mode = kf.get("generation_mode", "i2v")
        generation_modes[mode] = generation_modes.get(mode, 0) + 1

    details = {
        "character_name": char_data.get("name"),
        "character_tag": char_data.get("character_tag"),
        "total_keyframes": len(keyframes),
        "all_files_exist": all_exist,
        "watermark_cleaned": watermark_cleaned,
        "generation_modes": generation_modes,
        "character_sheet_integrity": tier1.details,
    }

    passed = all_exist and watermark_cleaned
    return GateVerificationResult(
        gate_name="character_consistency_gate",
        passed=passed,
        details=details,
        error_message=None if passed else "Missing keyframe files or uncleared watermarks",
    )


def verify_continuity_gate(script_path: str | Path, manifest_path: str | Path) -> GateVerificationResult:
    """Verifies scene continuity and timing alignment across all beats."""
    with open(script_path, "r", encoding="utf-8") as f:
        script_data = json.load(f)
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    beats_count = len(script_data.get("beats", []))
    synced_clips = manifest_data.get("synced_video_clips", [])

    passed = (beats_count == len(synced_clips)) and beats_count > 0
    details = {
        "expected_beats": beats_count,
        "actual_synced_clips": len(synced_clips),
    }

    return GateVerificationResult(
        gate_name="continuity_gate",
        passed=passed,
        details=details,
        error_message=None if passed else f"Mismatch: {beats_count} beats vs {len(synced_clips)} synced clips",
    )

def verify_slideshow_risk_gate(scene_plan_path: str | Path) -> GateVerificationResult:
    """Verifies that the scene plan avoids static slideshow risk via OpenMontage 6-dimension scorer."""
    path = Path(scene_plan_path)
    if not path.exists():
        return GateVerificationResult(
            gate_name="slideshow_risk_gate",
            passed=False,
            details={},
            error_message=f"Scene plan artifact not found at {path}",
        )
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    report = score_slideshow_risk(data)

    details = {
        "average_score": report.average_score,
        "verdict": report.verdict,
        "dimensions": {k: {"score": v.score, "reason": v.reason} for k, v in report.dimensions.items()},
        "hard_reject_reasons": report.hard_reject_reasons,
        "recommendations": report.recommendations,
    }

    return GateVerificationResult(
        gate_name="slideshow_risk_gate",
        passed=report.passed,
        details=details,
        error_message=None if report.passed else "; ".join(report.hard_reject_reasons or [f"Slideshow risk score {report.average_score} exceeds threshold."]),
    )


def verify_identity_preflight_gate(preflight_path: str | Path) -> GateVerificationResult:
    """Audit stage 4's ``identity_preflight.json``: fail on unusable identity assets, warn on weak ones.

    A missing report passes with a warning (runs recorded before the pre-flight existed); an unreadable
    one fails. ``warnings`` (low-resolution references) are surfaced in ``details`` but do not fail.
    """
    gate_name = "identity_preflight_gate"
    path = Path(preflight_path)
    if not path.is_file():
        return GateVerificationResult(
            gate_name=gate_name,
            passed=True,
            details={"found": False, "warnings": [f"identity_preflight.json not found at {path}"]},
        )
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return GateVerificationResult(
            gate_name=gate_name,
            passed=False,
            details={"found": True},
            error_message=f"identity_preflight.json unreadable: {exc}",
        )

    def _label(entry: Any) -> str:
        if isinstance(entry, dict):
            return f"{entry.get('asset', '?')}: {entry.get('issue', 'issue')}"
        return str(entry)

    errors = [_label(e) for e in report.get("errors") or []]
    warnings = [_label(w) for w in report.get("warnings") or []]
    ok = bool(report.get("ok", not errors)) and not errors
    details = {
        "found": True,
        "ok": ok,
        "assets": sorted((report.get("assets") or {}).keys()),
        "warnings": warnings,
        "errors": errors,
    }
    return GateVerificationResult(
        gate_name=gate_name,
        passed=ok,
        details=details,
        error_message=None if ok else ("Identity pre-flight failed: " + "; ".join(errors or ["ok=false"])),
    )


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def load_run_ledger(artifacts_dir: Path, workspace: Optional[ProjectWorkspace] = None) -> Dict[str, Any]:
    """Prompt Ledger entries by shot id: ``prompt_ledger.json`` overlaid with the live telemetry snapshot.

    The director only persists ``prompt_ledger.json`` after stage 8 succeeds, so at verification time the
    live recorder is the authority and the file covers standalone re-verification of a finished run.
    """
    candidates = [Path(artifacts_dir).parent / "prompt_ledger.json", Path(artifacts_dir) / "prompt_ledger.json"]
    if workspace is not None:
        candidates.insert(0, workspace.prompt_ledger_path)
    ledger: Dict[str, Any] = {}
    for candidate in candidates:
        data = _load_json_file(candidate)
        if isinstance(data, dict):
            ledger.update({k: v for k, v in data.items() if isinstance(v, dict)})
            break
        if isinstance(data, list):
            ledger.update({str(e.get("shot_id")): e for e in data if isinstance(e, dict) and e.get("shot_id")})
            break
    recorder = telemetry.current()
    if recorder is not None:
        try:
            ledger.update(recorder.snapshot().get("prompts") or {})
        except Exception:
            pass
    return ledger


def _audio_stage_tts_fallback_shots() -> List[str]:
    """Shots stage 6 flagged ``tts_fallback`` in the live telemetry (best effort)."""
    recorder = telemetry.current()
    if recorder is None:
        return []
    try:
        stages = recorder.snapshot().get("stages") or []
        stage = next(st for st in stages if st.get("stage") == telemetry.stage_number("audio_lip_sync"))
        return [str(i.get("id")) for i in stage.get("items") or [] if i.get("tts_fallback")]
    except Exception:
        return []


def silent_voice_stems(script_path: Path, manifest_path: Path) -> List[str]:
    """Shots with spoken text whose voice stem is digital silence (failed TTS written as a placeholder)."""
    script = _load_json_file(script_path) or {}
    manifest = _load_json_file(manifest_path) or {}
    stems = manifest.get("audio_stems") or []
    silent: List[str] = []
    for idx, beat in enumerate(script.get("beats") or []):
        if not (beat.get("spoken_text") or "").strip() or idx >= len(stems):
            continue
        stem = Path(stems[idx])
        if not stem.is_file():
            continue
        res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(stem), "-af", "volumedetect", "-f", "null", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", res.stderr.decode("utf-8", "replace"))
        if peak is None or peak.group(1) == "-inf" or float(peak.group(1)) <= SILENT_STEM_MAX_DB:
            silent.append(f"shot_{idx + 1:02d}")
    return silent


def verify_prompt_ledger_gate(
    ledger: Mapping[str, Any], tts_fallback_shots: Iterable[str] = ()
) -> GateVerificationResult:
    """Prompt Ledger audit: a master containing placeholders must not be released as PASSED.

    Flags every shot whose ledger entry carries ``degraded_from`` (e.g. R2V degraded to a first frame),
    a placeholder ``mode`` (LOCAL_FFMPEG / PLACEHOLDER), or ``tts_fallback``; plus any shot in
    ``tts_fallback_shots`` (stage 6 telemetry / silent stems). ``run_all_verification_gates`` turns a
    failure of this gate alone into ``overall_status == "DRAFT"``.
    """
    flagged: Dict[str, List[str]] = {}

    def _flag(shot: str, reason: str) -> None:
        flagged.setdefault(shot, [])
        if reason not in flagged[shot]:
            flagged[shot].append(reason)

    for shot_id, entry in sorted(ledger.items()):
        entry = entry if isinstance(entry, Mapping) else {}
        if entry.get("degraded_from"):
            _flag(shot_id, f"degraded_from={entry['degraded_from']}")
        mode = str(entry.get("mode") or "")
        if mode.upper() in PLACEHOLDER_MODES:
            _flag(shot_id, f"mode={mode}")
        if entry.get("tts_fallback"):
            _flag(shot_id, "tts_fallback")
    for shot_id in tts_fallback_shots:
        _flag(str(shot_id), "tts_fallback")

    details = {"shots_audited": len(ledger), "flagged_shots": flagged, "placeholder_count": len(flagged)}
    passed = not flagged
    return GateVerificationResult(
        gate_name=PLACEHOLDER_GATE_NAME,
        passed=passed,
        details=details,
        error_message=None
        if passed
        else "Master contains placeholder/degraded content: "
        + "; ".join(f"{shot} ({', '.join(reasons)})" for shot, reasons in flagged.items()),
    )


def publish_thumbnail_timestamp(duration: float) -> float:
    """Poster-frame time: one second before the end, capped at 18s, never negative."""
    return max(0.0, min(duration - 1.0, THUMBNAIL_MAX_TIMESTAMP))


def generate_commercial_thumbnail(
    video_path: str | Path,
    output_thumbnail_path: str | Path,
    timestamp: float = 18.0,
) -> str:
    """Extracts high-resolution poster frame from video master for commercial publishing."""
    v_path = Path(video_path)
    out_path = Path(output_thumbnail_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(timestamp),
        "-i",
        str(v_path),
        "-vframes",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return str(out_path)


def run_all_verification_gates(
    master_video_path: str | Path | None = None,
    artifacts_dir: Path | None = None,
    workspace: Optional[ProjectWorkspace] = None,
) -> RenderReportArtifact:
    """Executes all quality gates and writes render_report.json and publish_log.json."""
    target_artifacts_dir = workspace.artifacts_dir if workspace is not None else (artifacts_dir or ARTIFACTS_DIR)
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)

    if master_video_path is not None:
        video_path = Path(master_video_path)
    elif workspace is not None:
        video_path = workspace.master_video_path
    else:
        video_path = Path(OUTPUT_DIR / "final_commercial_master.mp4")
    script_path = target_artifacts_dir / "script.json"
    manifest_path = target_artifacts_dir / "asset_manifest.json"
    scene_plan_path = target_artifacts_dir / "scene_plan.json"

    # Run the independent verification gates (including Two-Tier Character Sheet Integrity)
    gate_runners = (
        lambda: verify_technical_gate(video_path),
        lambda: verify_media_quality_gate(video_path, target_artifacts_dir / "audio_mix_report.json"),
        lambda: verify_character_sheet_integrity_gate(),
        lambda: verify_character_consistency_gate(manifest_path),
        lambda: verify_continuity_gate(script_path, manifest_path),
        lambda: verify_slideshow_risk_gate(scene_plan_path),
        lambda: verify_identity_preflight_gate(target_artifacts_dir / "identity_preflight.json"),
        lambda: verify_prompt_ledger_gate(
            load_run_ledger(target_artifacts_dir, workspace),
            sorted(set(_audio_stage_tts_fallback_shots()) | set(silent_voice_stems(script_path, manifest_path))),
        ),
    )

    all_gates: List[GateVerificationResult] = []
    for index, run_gate in enumerate(gate_runners, start=1):
        gate = run_gate()
        all_gates.append(gate)
        telemetry.stage_progress(
            STAGE_VERIFICATION,
            index,
            len(gate_runners),
            unit="gates",
            label=gate.gate_name,
            item={
                "id": gate.gate_name,
                "status": "passed" if gate.passed else "failed",
                "error": gate.error_message,
                "details": gate.details,
            },
        )
    # DRAFT = every real quality gate passed but the master contains placeholders (ADR 0004).
    hard_failures = [g for g in all_gates if not g.passed and g.gate_name != PLACEHOLDER_GATE_NAME]
    if hard_failures:
        overall_status = STATUS_FAILED
    elif any(not g.passed for g in all_gates):
        overall_status = STATUS_DRAFT
    else:
        overall_status = STATUS_PASSED
    tech_gate = all_gates[0]

    file_size = video_path.stat().st_size if video_path.exists() else 0
    duration = tech_gate.details.get("duration_seconds", 0.0)
    width = tech_gate.details.get("width", 1080)
    height = tech_gate.details.get("height", 1920)

    campaign_id = "campaign_default"
    product_name = "Commercial Product"
    if script_path.exists():
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                s_data = json.load(f)
                campaign_id = s_data.get("campaign_id", campaign_id)
                product_name = s_data.get("product_name", product_name)
        except Exception:
            pass

    report = RenderReportArtifact(
        campaign_id=campaign_id,
        master_video_path=str(video_path),
        file_size_bytes=file_size,
        duration_seconds=duration,
        video_codec=tech_gate.details.get("video_codec", "h264"),
        audio_codec=tech_gate.details.get("audio_codec", "aac"),
        width=width,
        height=height,
        aspect_ratio="9:16",
        verification_gates=all_gates,
        overall_status=overall_status,
    )

    report_file = target_artifacts_dir / "render_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, ensure_ascii=False, indent=2)
    telemetry.register_artifact(report_file, stage=STAGE_VERIFICATION, label="Render report")

    publish_file = target_artifacts_dir / "publish_log.json"
    if overall_status != STATUS_PASSED:
        # ADR 0004: a master that failed a gate must never reach the publication catalog, and a
        # publish_log.json left by an earlier PASSED run no longer describes this master.
        publish_file.unlink(missing_ok=True)
        failed_gates = "; ".join(
            f"{gate.gate_name}: {gate.error_message or 'failed'}" for gate in all_gates if not gate.passed
        )
        telemetry.fail_stage(STAGE_VERIFICATION, f"Overall: {report.overall_status} ({failed_gates})")
        return report

    # Generate thumbnail and publish_log.json
    if workspace is not None:
        thumb_path = workspace.thumbnail_path
    else:
        thumb_path = video_path.parent / f"thumbnail_{video_path.stem}.jpg"
    generate_commercial_thumbnail(video_path, thumb_path, timestamp=publish_thumbnail_timestamp(duration))
    telemetry.register_artifact(thumb_path, stage=STAGE_VERIFICATION, label="Publish thumbnail")

    clean_tag = "".join(product_name.title().split())
    publish_log = PublishLogArtifact(
        campaign_id=campaign_id,
        product_name=product_name,
        master_video_path=str(video_path),
        thumbnail_path=str(thumb_path),
        title=f"Viral Commercial: {product_name}",
        description=f"Khám phá siêu phẩm {product_name} với thiết kế chuẩn điện ảnh và hiệu năng vượt trội. Link đặt hàng độc quyền tại bio!",
        hashtags=[f"#{clean_tag}", "#TikTokShopVN", "#AICommercial", "#Trending", "#ViralVideo"],
        published_at=datetime.datetime.utcnow().isoformat() + "Z",
    )

    with open(publish_file, "w", encoding="utf-8") as f:
        json.dump(publish_log.model_dump(), f, ensure_ascii=False, indent=2)
    telemetry.register_artifact(publish_file, stage=STAGE_VERIFICATION, label="Publish log")
    telemetry.complete_stage(STAGE_VERIFICATION, message=f"Overall: {report.overall_status}")

    return report
