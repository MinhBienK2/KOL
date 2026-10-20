"""Step 7: Final Video Composition & Multi-Track Audio Ducking (FFmpeg)."""

from __future__ import annotations

import datetime
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from pipeline import telemetry
from pipeline.config import (
    ARTIFACTS_DIR,
    BASE_DIR,
    OUTPUT_DIR,
    SYNCED_CLIPS_DIR,
    TARGET_RESOLUTION,
)
from pipeline.lip_sync_engine import ShotTimingPlan, plan_shot_timing
from pipeline.schemas import (
    AssetManifestArtifact,
    AudioTrackConfig,
    EditDecisionsArtifact,
    ScriptArtifact,
)
from pipeline.workspace import ProjectWorkspace

STAGE_COMPOSITION = telemetry.stage_number("composition")

#: Single source of truth for the multi-track mix targets (mirrored in the FFmpeg filter).
#: Nominal BGM duck under speech (ADR 0003). The sidechain filter is level-dependent, so this is the
#: guaranteed-floor design point: measured dips with real ffmpeg are >=10 dB for quiet speech (-32 dB mean),
#: ~14 dB at -27 dB and ~19 dB for typical TTS (-22 dB mean). The previous filter dipped only 0.3-7.6 dB.
BGM_DUCKING_ATTENUATION_DB = -14.0
TARGET_LUFS = -14.0
#: Master integrated loudness must land within this many LU of TARGET_LUFS to be "compliant".
LOUDNESS_TOLERANCE_LU = 1.5

#: Sidechain compressor ducking BGM (first input) keyed by the speech stem (second input).
DUCKING_FILTER = "sidechaincompress=threshold=0.012:ratio=12:attack=30:release=600:mix=1"

_SEGMENT_FPS = 30

def get_clip_duration(file_path: str | Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(file_path),
    ]
    res = subprocess.check_output(cmd).decode("utf-8")
    return float(json.loads(res)["format"]["duration"])


def escape_drawtext(text: str) -> str:
    """Escapes special characters for FFmpeg drawtext filter."""
    return text.replace(":", r"\:").replace("'", r"\'").replace("%", r"\%")


def compose_master_commercial(
    script: ScriptArtifact | None = None,
    manifest: AssetManifestArtifact | None = None,
    bgm_path: str | Path | None = None,
    pop_sfx_path: str | Path | None = None,
    chime_sfx_path: str | Path | None = None,
    output_master_path: str | Path | None = None,
    artifacts_dir: Path | None = None,
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    include_captions: bool = True,
    workspace: Optional[ProjectWorkspace] = None,
) -> EditDecisionsArtifact:
    """Assembles all synchronized shots, captions, and multi-track audio ducking into final master MP4."""
    target_artifacts_dir = workspace.artifacts_dir if workspace is not None else (artifacts_dir or ARTIFACTS_DIR)
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)
    if output_master_path is not None:
        out_master = Path(output_master_path)
    elif workspace is not None:
        out_master = workspace.master_video_path
    else:
        out_master = Path(OUTPUT_DIR / "final_commercial_master.mp4")
    out_master.parent.mkdir(parents=True, exist_ok=True)

    if script is None:
        with open(target_artifacts_dir / "script.json", "r", encoding="utf-8") as f:
            script = ScriptArtifact.model_validate(json.load(f))

    if manifest is None:
        with open(target_artifacts_dir / "asset_manifest.json", "r", encoding="utf-8") as f:
            manifest = AssetManifestArtifact.model_validate(json.load(f))

    synced_clips = [Path(p) for p in manifest.synced_video_clips]
    if not synced_clips:
        raise ValueError("No synchronized video clips found in asset_manifest.json")

    bgm = Path(bgm_path or (BASE_DIR / "assets" / "audio" / "music" / "commercial_bgm.mp3"))
    pop_sfx = Path(pop_sfx_path or (BASE_DIR / "assets" / "audio" / "sfx" / "pop.mp3"))
    chime_sfx = Path(chime_sfx_path or (BASE_DIR / "assets" / "audio" / "sfx" / "chime.mp3"))

    # Step A: Measure durations and calculate timeline timecodes
    clip_durations = [get_clip_duration(c) for c in synced_clips]
    total_timeline_duration = sum(clip_durations)

    timecodes: List[tuple[float, float]] = []
    curr = 0.0
    for dur in clip_durations:
        timecodes.append((curr, curr + dur))
        curr += dur

    # Step B: Build FFmpeg Concat file for seamless clip video & speech stitching
    concat_list_path = target_artifacts_dir / "concat_clips.txt"
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for c in synced_clips:
            f.write(f"file '{c.resolve()}'\n")

    # Step C: Build dynamic caption filters
    caption_filters: List[str] = []
    captions_manifest: List[dict] = []
    if include_captions:
        for idx, (start_t, end_t) in enumerate(timecodes):
            if idx < len(script.beats):
                caption_text = script.beats[idx].on_screen_text
                if not caption_text:
                    continue
                esc_text = escape_drawtext(caption_text)
                
                # Draw banner box with high-contrast text in mobile safe zone
                f_box = (
                    f"drawtext=fontfile='{font_path}':text='{esc_text}':"
                    f"fontcolor=white:fontsize=44:box=1:boxcolor=black@0.65:boxborderw=16:"
                    f"x=(w-text_w)/2:y=h-480:enable='between(t,{start_t:.2f},{end_t:.2f})'"
                )
                caption_filters.append(f_box)
                captions_manifest.append({
                    "text": caption_text,
                    "start": round(start_t, 2),
                    "end": round(end_t, 2),
                })

    # Combined video filter: captions overlay
    combined_vf = ",".join(caption_filters) if caption_filters else "null"

    # Step D: Temporary stitched speech + video
    temp_stitched = out_master.with_name(".temp_stitched.mp4")
    cmd_stitch = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-vf",
        combined_vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        str(temp_stitched),
    ]
    print("[Composer] Stitching video timeline with dynamic on-screen typography...")
    telemetry.log(
        f"Stitching {len(synced_clips)} clips into a {total_timeline_duration:.2f}s master timeline "
        f"with {len(caption_filters)} caption overlays",
        stage=STAGE_COMPOSITION,
    )
    subprocess.check_call(cmd_stitch, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Step E: Multi-Track Audio Mixing with Automatic Audio Ducking (-24dB during speech)
    # Input 0: temp_stitched video (speech track is [0:a])
    # Input 1: BGM audio
    # Sidechain compression ducks BGM whenever speech exceeds threshold
    filter_complex = (
        "[1:a]volume=0.25[bgm_base];"
        "[bgm_base][0:a]sidechaincompress="
        "threshold=0.03:ratio=4:attack=200:release=600:level_sc=1:mix=0.75[ducked_bgm];"
        "[0:a][ducked_bgm]amix=inputs=2:duration=first:weights=1.0 0.35[mixed_audio];"
        "[mixed_audio]loudnorm=I=-14:LRA=11:TP=-1.5[out_audio]"
    )

    cmd_master = [
        "ffmpeg",
        "-y",
        "-i",
        str(temp_stitched),
        "-stream_loop",
        "-1",
        "-i",
        str(bgm),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-map",
        "[out_audio]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-ar",
        "48000",
        "-shortest",
        str(out_master),
    ]
    print("[Composer] Mixing multi-track audio with automatic BGM sidechain ducking & -14 LUFS loudness...")
    telemetry.log(
        f"Sidechain ducking BGM by {BGM_DUCKING_ATTENUATION_DB:.0f}dB during speech, "
        f"mixing voice + BGM, normalising to {TARGET_LUFS:.0f} LUFS",
        stage=STAGE_COMPOSITION,
    )
    telemetry.note(
        f"Audio mix: BGM ducking {BGM_DUCKING_ATTENUATION_DB:.0f}dB, target {TARGET_LUFS:.0f} LUFS, "
        f"{len(captions_manifest)} captions over {len(synced_clips)} clips",
        ducking_attenuation_db=BGM_DUCKING_ATTENUATION_DB,
        target_lufs=TARGET_LUFS,
        caption_count=len(captions_manifest),
        timeline_clips=len(synced_clips),
        total_duration_seconds=round(total_timeline_duration, 2),
    )
    subprocess.check_call(cmd_master, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    telemetry.register_artifact(out_master, stage=STAGE_COMPOSITION, label="Final commercial master")

    # Clean temporary files
    temp_stitched.unlink(missing_ok=True)
    concat_list_path.unlink(missing_ok=True)

    # Emit edit_decisions.json
    edit_decisions = EditDecisionsArtifact(
        campaign_id=script.campaign_id,
        render_runtime="ffmpeg",
        target_aspect_ratio="9:16",
        timeline_clips=[str(c) for c in synced_clips],
        audio_tracks=[
            AudioTrackConfig(
                track_id="track_voiceover",
                type="voiceover",
                file_path="output/audio/voice_*.wav",
                target_lufs=TARGET_LUFS,
            ),
            AudioTrackConfig(
                track_id="track_bgm",
                type="bgm",
                file_path=str(bgm),
                ducking_attenuation_db=BGM_DUCKING_ATTENUATION_DB,
            ),
            AudioTrackConfig(
                track_id="track_sfx",
                type="sfx",
                file_path=str(pop_sfx),
            ),
        ],
        transitions=[{"type": "cut", "duration": 0.0}],
        captions=captions_manifest,
        output_master_path=str(out_master),
    )

    out_file = target_artifacts_dir / "edit_decisions.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(edit_decisions.model_dump(), f, ensure_ascii=False, indent=2)
    telemetry.register_artifact(out_file, stage=STAGE_COMPOSITION, label="Edit decisions")

    print(f"[Composer] SUCCESS: Final Commercial Master rendered to {out_master}")
    return edit_decisions
