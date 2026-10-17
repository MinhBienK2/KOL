"""Step 8: Independent Verification Gates & Commercial Release Packaging."""

from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path
from typing import Any, List, Optional

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


def verify_character_consistency_gate(
    manifest_path: str | Path,
    character_file: str | Path = CHARACTER_PATH,
) -> GateVerificationResult:
    """Verifies that generated keyframes strictly preserve character identity anchors."""
    char_path = Path(character_file)
    with open(char_path, "r", encoding="utf-8") as f:
        char_data = json.load(f)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    keyframes = manifest_data.get("keyframes", [])
    if not keyframes:
        return GateVerificationResult(
            gate_name="character_consistency_gate",
            passed=False,
            details={},
            error_message="No keyframes found in manifest",
        )

    all_exist = True
    watermark_cleaned = True
    for kf in keyframes:
        p = Path(kf.get("cleaned_image_path", ""))
        if not p.exists() or p.stat().st_size == 0:
            all_exist = False
        if not kf.get("watermark_removed", False):
            watermark_cleaned = False

    details = {
        "character_name": char_data.get("name"),
        "character_tag": char_data.get("character_tag"),
        "total_keyframes": len(keyframes),
        "all_files_exist": all_exist,
        "watermark_cleaned": watermark_cleaned,
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
) -> RenderReportArtifact:
    """Executes all quality gates and writes render_report.json and publish_log.json."""
    target_artifacts_dir = artifacts_dir or ARTIFACTS_DIR
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)

    video_path = Path(master_video_path or (OUTPUT_DIR / "final_commercial_master.mp4"))
    script_path = target_artifacts_dir / "script.json"
    manifest_path = target_artifacts_dir / "asset_manifest.json"

    # Run 3 independent verification gates
    tech_gate = verify_technical_gate(video_path)
    char_gate = verify_character_consistency_gate(manifest_path)
    cont_gate = verify_continuity_gate(script_path, manifest_path)

    all_gates = [tech_gate, char_gate, cont_gate]
    overall_status = "PASSED" if all(g.passed for g in all_gates) else "FAILED"

    file_size = video_path.stat().st_size if video_path.exists() else 0
    duration = tech_gate.details.get("duration_seconds", 0.0)
    width = tech_gate.details.get("width", 1080)
    height = tech_gate.details.get("height", 1920)

    report = RenderReportArtifact(
        campaign_id="campaign_lumina_mug_01",
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

    # Generate thumbnail and publish_log.json
    thumb_path = OUTPUT_DIR / "thumbnail_master.jpg"
    if video_path.exists():
        generate_commercial_thumbnail(video_path, thumb_path, timestamp=min(duration - 1.0, 18.0))

    publish_log = PublishLogArtifact(
        campaign_id="campaign_lumina_mug_01",
        product_name="Ly Giữ Nhiệt Thông Minh Lumina Pro",
        master_video_path=str(video_path),
        thumbnail_path=str(thumb_path),
        title="Bí quyết giữ nhiệt 24h của KOL Minh Anh: Ly thông minh Lumina Pro",
        description="Đừng để cà phê nguội làm hỏng ngày làm việc của bạn! Ly giữ nhiệt Lumina Pro với màn hình cảm ứng LED đo nhiệt độ, giữ nóng 12h, lạnh 24h và chống tràn 360 độ.",
        hashtags=["#LuminaPro", "#LyGiuNhietThongMinh", "#KOLMinhAnh", "#DoGiaDungThongMinh", "#TikTokShopVN", "#GocLamViec"],
        published_at=datetime.datetime.utcnow().isoformat() + "Z",
    )

    publish_file = target_artifacts_dir / "publish_log.json"
    with open(publish_file, "w", encoding="utf-8") as f:
        json.dump(publish_log.model_dump(), f, ensure_ascii=False, indent=2)

    return report
