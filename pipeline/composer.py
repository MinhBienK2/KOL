"""Step 7: Final Video Composition & Multi-Track Audio Ducking (FFmpeg).

The render is driven by the Edit Decision List: the requested ``transitions`` become real
``xfade`` / ``acrossfade`` joins, caption windows follow the (overlapped) timeline, and the
resulting EDL records exactly what was rendered. Audio is mixed voice-over + sidechain-ducked
BGM and normalised with a two-pass (linear) ``loudnorm`` to the streaming target.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from pipeline import telemetry
from pipeline.config import (
    ARTIFACTS_DIR,
    BASE_DIR,
    OUTPUT_DIR,
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
#: Nominal depth the BGM dips under speech; ``DUCKING_FILTER`` is verified in tests to deliver >= 10 dB.
BGM_DUCKING_ATTENUATION_DB = -14.0
TARGET_LUFS = -14.0  # integrated loudness shared by TikTok / Reels / YouTube Shorts
TARGET_TRUE_PEAK_DB = -1.5  # dBTP headroom so lossy platform re-encodes do not clip
TARGET_LRA = 11.0
BGM_BED_GAIN_DB = -12.0  # music bed level relative to the stem before ducking
BGM_FADE_IN_SECONDS = 0.5
BGM_FADE_OUT_SECONDS = 1.5

#: Sidechain-compress the BGM with the voice-over as the key. ``ratio=20`` is a hard duck (the old
#: ``ratio=4, mix=0.75, attack=200ms`` setting only dipped the music ~2.5 dB); the 30ms attack makes
#: the music yield before the first syllable lands and the 500ms release ramps it back smoothly.
DUCKING_FILTER = "sidechaincompress=threshold=0.01:ratio=20:attack=30:release=500:makeup=1"

#: Transition vocabulary an agent may request in the EDL (``cut`` or an FFmpeg ``xfade`` name).
SUPPORTED_TRANSITIONS = (
    "cut",
    "fade",
    "dissolve",
    "fadeblack",
    "fadewhite",
    "wipeleft",
    "wiperight",
    "wipeup",
    "slideleft",
    "slideright",
    "slideup",
    "smoothleft",
    "smoothright",
    "circleopen",
    "zoomin",
    "pixelize",
    "radial",
)
DEFAULT_TRANSITION_SECONDS = 0.3
MIN_TRANSITION_SECONDS = 0.05
TIMELINE_FPS = 30


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


def _probe_video_geometry(file_path: str | Path) -> Tuple[int, int, bool]:
    """Returns (width, height, has_audio) of a clip."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,width,height",
        "-of",
        "json",
        str(file_path),
    ]
    streams = json.loads(subprocess.check_output(cmd).decode("utf-8"))["streams"]
    width, height = TARGET_RESOLUTION
    has_audio = False
    for s in streams:
        if s.get("codec_type") == "video" and s.get("width"):
            width, height = int(s["width"]), int(s["height"])
        elif s.get("codec_type") == "audio":
            has_audio = True
    return width, height, has_audio


# -- Transitions & timeline -------------------------------------------------------------------


def normalize_transitions(transitions: Optional[Sequence[dict]], clip_durations: Sequence[float]) -> List[dict]:
    """Validates and completes the requested joins between consecutive clips.

    Returns one ``{"from", "to", "type", "duration"}`` entry per cut point. Missing entries default
    to a hard cut; an overlapping transition is clamped to half of the shorter adjacent clip so the
    two joins around a clip can never consume more than the clip itself.
    """
    out: List[dict] = []
    requested = list(transitions or [])
    for i in range(max(0, len(clip_durations) - 1)):
        spec = requested[i] if i < len(requested) and requested[i] else {}
        t_type = str(spec.get("type", "cut")).lower()
        if t_type not in SUPPORTED_TRANSITIONS:
            raise ValueError(f"Unsupported transition '{t_type}'. Supported: {', '.join(SUPPORTED_TRANSITIONS)}")
        duration = 0.0
        if t_type != "cut":
            duration = float(spec.get("duration", DEFAULT_TRANSITION_SECONDS))
            duration = min(duration, 0.5 * min(clip_durations[i], clip_durations[i + 1]))
            if duration < MIN_TRANSITION_SECONDS:
                t_type, duration = "cut", 0.0
        out.append({"from": i, "to": i + 1, "type": t_type, "duration": round(duration, 3)})
    return out


def compute_timecodes(clip_durations: Sequence[float], transitions: Sequence[dict]) -> List[Tuple[float, float]]:
    """(start, end) of every clip on the output timeline, accounting for transition overlaps."""
    timecodes: List[Tuple[float, float]] = []
    start = 0.0
    for i, dur in enumerate(clip_durations):
        timecodes.append((start, start + dur))
        overlap = transitions[i]["duration"] if i < len(transitions) else 0.0
        start = start + dur - overlap
    return timecodes


# -- Captions ---------------------------------------------------------------------------------


class CaptionLayout(BaseModel):
    font_size: int
    margin_x: int
    bottom_margin: int
    box_border: int
    line_spacing: int
    max_text_width: int


def caption_layout(width: int, height: int) -> CaptionLayout:
    """Burned-in caption geometry that stays clear of TikTok / Reels UI chrome.

    On a 1080x1920 canvas the platform UI covers ~320-480px at the bottom and ~120px at the sides,
    so captions are bottom-anchored 25% up the frame with an 11% side margin (the stricter TikTok
    numbers; they are not official specs, so we design for the worst case).
    """
    margin_x = round(width * 0.11)
    box_border = round(width * 0.016)
    return CaptionLayout(
        font_size=round(width * 0.047),
        margin_x=margin_x,
        bottom_margin=round(height * 0.25),
        box_border=box_border,
        line_spacing=round(width * 0.008),
        max_text_width=width - 2 * margin_x - 2 * box_border,
    )


def _font_measurer(font_path: str, font_size: int):
    try:
        from PIL import ImageFont

        font = ImageFont.truetype(font_path, font_size)
        return lambda s: font.getlength(s)
    except Exception:  # PIL or the font is unavailable: coarse average-glyph estimate
        return lambda s: 0.62 * font_size * len(s)


def wrap_caption(text: str, max_width: float, font_size: int, font_path: str) -> List[str]:
    """Greedy word-wrap so that no rendered line exceeds ``max_width`` pixels."""
    words = (text or "").split()
    if not words:
        return []
    measure = _font_measurer(font_path, font_size)

    lines: List[str] = []
    current = ""
    for word in words:
        # A single over-long token is hard-split by characters rather than overflowing the frame.
        while measure(word) > max_width and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and measure(word[:cut]) > max_width:
                cut -= 1
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:cut])
            word = word[cut:]
        candidate = f"{current} {word}".strip()
        if current and measure(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _fit_caption(text: str, layout: CaptionLayout, font_path: str, max_lines: int = 3) -> Tuple[List[str], int]:
    """Wraps ``text``; shrinks the font (down to 70%) until it fits within ``max_lines``."""
    size = layout.font_size
    lines = wrap_caption(text, layout.max_text_width, size, font_path)
    while len(lines) > max_lines and size > layout.font_size * 0.7:
        size -= 2
        lines = wrap_caption(text, layout.max_text_width, size, font_path)
    return lines, size


def _filter_quote(value: str) -> str:
    """Escapes a value for use inside single quotes in an FFmpeg filtergraph option."""
    return value.replace("\\", "\\\\").replace("'", r"'\''").replace(":", r"\:")


# -- Audio mix --------------------------------------------------------------------------------


def build_audio_mix_filter(
    duration: float,
    *,
    with_bgm: bool = True,
    measured: Optional[Dict[str, float]] = None,
    print_json: bool = False,
) -> str:
    """Filtergraph: input 0 = voice timeline, input 1 = BGM (looped). Output label ``[out]``.

    With ``measured`` (the first-pass loudnorm stats) the final pass runs ``linear=true`` so one
    constant gain reaches the target without pumping the dynamics.
    """
    norm = f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK_DB}:LRA={TARGET_LRA}"
    if measured is not None:
        norm += (
            f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true"
        )
    if print_json:
        norm += ":print_format=json"

    voice = f"[0:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={duration:.3f},atrim=end={duration:.3f}"
    if not with_bgm:
        return f"{voice},{norm},aresample=48000[out]"

    fade_out = min(BGM_FADE_OUT_SECONDS, duration / 2)
    return ";".join(
        [
            f"{voice},asplit=2[vm][vk]",
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={BGM_BED_GAIN_DB}dB,"
            f"atrim=end={duration:.3f},afade=t=in:d={BGM_FADE_IN_SECONDS},"
            f"afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f}[bgm]",
            f"[bgm][vk]{DUCKING_FILTER}[duck]",
            "[vm][duck]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[mix]",
            f"[mix]{norm},aresample=48000[out]",
        ]
    )


_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def _parse_loudnorm_json(stderr: str) -> Dict[str, float]:
    blocks = _LOUDNORM_JSON.findall(stderr)
    if not blocks:
        raise RuntimeError("loudnorm produced no measurement JSON")
    return {k: float(v) for k, v in json.loads(blocks[-1]).items() if k != "normalization_type"}


def measure_loudness(path: str | Path) -> Dict[str, float]:
    """Integrated loudness (LUFS), true peak (dBTP) and LRA of a file's audio."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-vn",
        "-af",
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK_DB}:LRA={TARGET_LRA}:print_format=json",
        "-f",
        "null",
        "-",
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    stats = _parse_loudnorm_json(res.stderr.decode("utf-8", "replace"))
    return {
        "integrated_lufs": stats["input_i"],
        "true_peak_db": stats["input_tp"],
        "lra": stats["input_lra"],
    }


# -- Per-shot timing --------------------------------------------------------------------------


class TimedEditDecisionsArtifact(EditDecisionsArtifact):
    """EditDecisionsArtifact plus the per-shot in/out/slow-down decisions (backward-compatible superset)."""

    shots: List[Dict[str, Any]] = Field(default_factory=list)
    total_duration_seconds: float = 0.0


def _match_by_shot(paths: Sequence[str], shot_id: str, idx: int) -> Optional[Path]:
    for raw in paths:
        if shot_id in Path(raw).name:
            return Path(raw)
    return Path(paths[idx]) if idx < len(paths) else None


def resolve_shot_sources(
    script: ScriptArtifact, manifest: AssetManifestArtifact
) -> Optional[Tuple[List[Path], List[Path]]]:
    """(raw clip, voice stem) for every beat, or None unless each beat has both on disk."""
    if not manifest.raw_video_clips or not manifest.audio_stems:
        return None
    clips: List[Path] = []
    stems: List[Path] = []
    for idx in range(len(script.beats)):
        shot_id = f"shot_{idx + 1:02d}"
        clip = _match_by_shot(manifest.raw_video_clips, shot_id, idx)
        stem = _match_by_shot(manifest.audio_stems, shot_id, idx)
        if clip is None or stem is None or not clip.exists() or not stem.exists():
            return None
        clips.append(clip)
        stems.append(stem)
    return (clips, stems) if clips else None


def render_shot_segment(raw_clip: Path, stem: Path, plan: ShotTimingPlan, out_path: Path) -> Path:
    """Render one shot: cut/slow the generated clip per ``plan`` and fit the voice stem to its length.

    Segments are lossless-audio mkv so per-shot AAC priming cannot accumulate drift across the join.
    """
    width, height = TARGET_RESOLUTION
    vf = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={TIMELINE_FPS}"
    )
    if plan.slowdown_factor != 1.0:
        vf += f",setpts={plan.slowdown_factor:.6f}*(PTS-STARTPTS),fps={TIMELINE_FPS}"
    if plan.held_tail_seconds > 0:
        vf += f",tpad=stop_mode=clone:stop_duration={plan.held_tail_seconds:.3f}"
    vf += f",trim=end={plan.target_seconds:.3f},setpts=PTS-STARTPTS,format=yuv420p[v]"
    af = (
        "[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,"
        f"atrim=end={plan.target_seconds:.3f},asetpts=PTS-STARTPTS[a]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{plan.in_point:.3f}", "-t", f"{plan.out_point - plan.in_point:.3f}", "-i", str(raw_clip),
        "-i", str(stem),
        "-filter_complex", f"{vf};{af}",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "14",
        "-c:a", "pcm_s16le", "-ar", "48000",
        str(out_path),
    ]
    _run_ffmpeg(cmd, f"shot segment {plan.shot_id}")
    return out_path


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
    transitions: Optional[Sequence[dict]] = None,
) -> EditDecisionsArtifact:
    """Assembles all synchronized shots, captions, and multi-track audio ducking into final master MP4.

    ``transitions`` is the directed part of the Edit Decision List: one ``{"type", "duration"}`` per cut
    point (``cut`` or an xfade name from ``SUPPORTED_TRANSITIONS``). Omitted entries are hard cuts.
    """
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

    # Per-shot timing. Generated clips are a fixed 6s/10s while beats last 1.5-6s, and the pre-muxed synced
    # clip freezes its last frame whenever the voice outlasts the footage. So when every beat has its raw
    # clip and voice stem, each shot is re-cut here: duration = max(beat estimate, voice), taken from real
    # motion, slowed gently only when the clip is genuinely short. Otherwise the synced clips are used as-is.
    sources = resolve_shot_sources(script, manifest)
    segments_dir = target_artifacts_dir / "_segments"
    shot_plans: List[Optional[ShotTimingPlan]] = []
    if sources is not None:
        raw_clips, stems = sources
        segments_dir.mkdir(parents=True, exist_ok=True)
        synced_clips = []
        for idx, beat in enumerate(script.beats):
            shot_id = f"shot_{idx + 1:02d}"
            plan = plan_shot_timing(
                shot_id,
                beat_estimated=float(beat.estimated_duration),
                voice_seconds=get_clip_duration(stems[idx]),
                clip_seconds=get_clip_duration(raw_clips[idx]),
            )
            synced_clips.append(render_shot_segment(raw_clips[idx], stems[idx], plan, segments_dir / f"{shot_id}.mkv"))
            shot_plans.append(plan)
            if plan.action in ("slowdown", "slowdown_and_hold"):
                telemetry.note(
                    f"[{shot_id}] generated clip {plan.clip_seconds:.2f}s is shorter than the {plan.target_seconds:.2f}s "
                    f"shot: {plan.action} x{plan.slowdown_factor:.2f}, held tail {plan.held_tail_seconds:.2f}s",
                    shot_id=shot_id,
                    action=plan.action,
                    slowdown_factor=plan.slowdown_factor,
                    held_tail_seconds=plan.held_tail_seconds,
                )
        source_clips = [str(c) for c in raw_clips]
    else:
        synced_clips = [Path(p) for p in manifest.synced_video_clips]
        if not synced_clips:
            raise ValueError("No synchronized video clips found in asset_manifest.json")
        source_clips = [str(c) for c in synced_clips]

    bgm = Path(bgm_path or (BASE_DIR / "assets" / "audio" / "music" / "commercial_bgm.mp3"))
    pop_sfx = Path(pop_sfx_path or (BASE_DIR / "assets" / "audio" / "sfx" / "pop.mp3"))
    chime_sfx = Path(chime_sfx_path or (BASE_DIR / "assets" / "audio" / "sfx" / "chime.mp3"))
    with_bgm = bgm.exists()
    if not with_bgm:
        telemetry.log(f"BGM not found at {bgm}; mixing voice-over only", level="warn", stage=STAGE_COMPOSITION)

    # Step A: Measure durations, resolve the EDL transitions and the overlapped timeline
    clip_durations = [get_clip_duration(c) for c in synced_clips]
    edl_transitions = normalize_transitions(transitions, clip_durations)
    timecodes = compute_timecodes(clip_durations, edl_transitions)
    total_timeline_duration = timecodes[-1][1]
    width, height, _ = _probe_video_geometry(synced_clips[0])

    # Step B: Caption filters (textfile + expansion=none: no escaping hazards for ' : % \ " etc.)
    layout = caption_layout(width, height)
    caption_files: List[Path] = []
    caption_filters: List[str] = []
    captions_manifest: List[dict] = []
    if include_captions:
        for idx, (start_t, end_t) in enumerate(timecodes):
            if idx >= len(script.beats):
                break
            caption_text = script.beats[idx].on_screen_text
            lines, font_size = _fit_caption(caption_text or "", layout, font_path)
            if not lines:
                continue
            # The caption leaves with its clip: when a transition follows it, it ends as the next clip starts.
            visible_end = end_t - (edl_transitions[idx]["duration"] if idx < len(edl_transitions) else 0.0)
            text_file = target_artifacts_dir / f".caption_{idx:02d}.txt"
            text_file.write_text("\n".join(lines), encoding="utf-8")
            caption_files.append(text_file)
            caption_filters.append(
                f"drawtext=fontfile='{_filter_quote(font_path)}':textfile='{_filter_quote(str(text_file))}':"
                f"expansion=none:fontcolor=white:fontsize={font_size}:line_spacing={layout.line_spacing}:"
                f"box=1:boxcolor=black@0.65:boxborderw={layout.box_border}:"
                f"x=(w-text_w)/2:y=h-{layout.bottom_margin}-text_h-{layout.box_border}:"
                f"enable='between(t,{start_t:.3f},{visible_end:.3f})'"
            )
            captions_manifest.append(
                {
                    "text": caption_text,
                    "lines": lines,
                    "font_size": font_size,
                    "start": round(start_t, 2),
                    "end": round(visible_end, 2),
                }
            )

    # Step C: Video + voice timeline in one decode: per-clip normalisation, EDL joins, captions
    inputs: List[str] = []
    graph: List[str] = []
    for i, clip in enumerate(synced_clips):
        inputs += ["-i", str(clip)]
        _, _, has_audio = _probe_video_geometry(clip)
        dur = clip_durations[i]
        graph.append(
            f"[{i}:v]settb=AVTB,fps={TIMELINE_FPS},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[v{i}]"
        )
        src = f"[{i}:a]aresample=48000," if has_audio else "anullsrc=r=48000:cl=stereo,"
        graph.append(
            f"{src}aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=end={dur:.3f},"
            f"apad=whole_dur={dur:.3f},asetpts=N/SR/TB[a{i}]"
        )

    cur_v, cur_a, timeline_len = "v0", "a0", clip_durations[0]
    for i in range(1, len(synced_clips)):
        trans = edl_transitions[i - 1]
        nxt_v, nxt_a = f"cv{i}", f"ca{i}"
        if trans["type"] == "cut":
            graph.append(f"[{cur_v}][v{i}]concat=n=2:v=1:a=0[{nxt_v}]")
            graph.append(f"[{cur_a}][a{i}]concat=n=2:v=0:a=1[{nxt_a}]")
            timeline_len += clip_durations[i]
        else:
            d = trans["duration"]
            graph.append(
                f"[{cur_v}][v{i}]xfade=transition={trans['type']}:duration={d}:offset={timeline_len - d:.3f}[{nxt_v}]"
            )
            graph.append(f"[{cur_a}][a{i}]acrossfade=d={d}:c1=tri:c2=tri[{nxt_a}]")
            timeline_len += clip_durations[i] - d
        cur_v, cur_a = nxt_v, nxt_a
    graph.append(f"[{cur_v}]{','.join(caption_filters) if caption_filters else 'null'}[vout]")

    temp_video = out_master.with_name(".temp_video.mp4")
    temp_voice = out_master.with_name(".temp_voice.wav")
    cmd_timeline = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(graph),
        "-map", "[vout]", "-r", str(TIMELINE_FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", str(temp_video),
        "-map", f"[{cur_a}]", "-c:a", "pcm_s16le", "-ar", "48000", str(temp_voice),
    ]
    print("[Composer] Rendering EDL timeline (transitions + safe-zone captions)...")
    telemetry.log(
        f"Rendering {len(synced_clips)} clips into a {total_timeline_duration:.2f}s timeline "
        f"({sum(1 for t in edl_transitions if t['type'] != 'cut')} transitions, {len(caption_filters)} captions)",
        stage=STAGE_COMPOSITION,
    )
    try:
        _run_ffmpeg(cmd_timeline, "timeline render")

        # Step D: Two-pass loudness: measure the mixed bus, then apply one linear gain to hit the target.
        duration = get_clip_duration(temp_voice)
        mix_inputs = ["-i", str(temp_voice)] + (["-stream_loop", "-1", "-i", str(bgm)] if with_bgm else [])
        measure_cmd = [
            "ffmpeg", "-hide_banner", "-nostats", *mix_inputs,
            "-filter_complex", build_audio_mix_filter(duration, with_bgm=with_bgm, print_json=True),
            "-map", "[out]", "-f", "null", "-",
        ]
        res = subprocess.run(measure_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            raise RuntimeError(f"Loudness measurement failed: {res.stderr.decode('utf-8', 'replace')[-800:]}")
        measured = _parse_loudnorm_json(res.stderr.decode("utf-8", "replace"))
        two_pass = measured["input_i"] > -70.0  # a silent bus cannot be gain-matched
        if not two_pass:
            measured = None  # fall back to plain single-pass loudnorm

        cmd_master = [
            "ffmpeg", "-y", *mix_inputs, "-i", str(temp_video),
            "-filter_complex",
            build_audio_mix_filter(duration, with_bgm=with_bgm, measured=measured if two_pass else None),
            "-map", f"{2 if with_bgm else 1}:v", "-map", "[out]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart",
            str(out_master),
        ]
        print(
            f"[Composer] Mixing voice + sidechain-ducked BGM, two-pass loudnorm to {TARGET_LUFS:.0f} LUFS "
            f"/ {TARGET_TRUE_PEAK_DB} dBTP..."
        )
        _run_ffmpeg(cmd_master, "master mix")
    finally:
        temp_video.unlink(missing_ok=True)
        temp_voice.unlink(missing_ok=True)
        for f in caption_files:
            f.unlink(missing_ok=True)
        shutil.rmtree(segments_dir, ignore_errors=True)

    output = measure_loudness(out_master)
    compliant = abs(output["integrated_lufs"] - TARGET_LUFS) <= 1.0 and output["true_peak_db"] <= -1.0
    mix_report = {
        "target_lufs": TARGET_LUFS,
        "target_true_peak_db": TARGET_TRUE_PEAK_DB,
        "two_pass": two_pass,
        "bgm_used": with_bgm,
        "bgm_bed_gain_db": BGM_BED_GAIN_DB,
        "ducking_filter": DUCKING_FILTER,
        "nominal_ducking_db": BGM_DUCKING_ATTENUATION_DB,
        "premix_lufs": round(measured["input_i"], 2) if two_pass else None,
        "output_lufs": round(output["integrated_lufs"], 2),
        "output_true_peak_db": round(output["true_peak_db"], 2),
        "output_lra": round(output["lra"], 2),
        "compliant": compliant,
    }
    report_file = target_artifacts_dir / "audio_mix_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(mix_report, f, ensure_ascii=False, indent=2)
    telemetry.register_artifact(report_file, stage=STAGE_COMPOSITION, label="Audio mix report")
    telemetry.note(
        f"Audio mix: BGM ducking ~{BGM_DUCKING_ATTENUATION_DB:.0f}dB, output {output['integrated_lufs']:.1f} LUFS / "
        f"{output['true_peak_db']:.1f} dBTP (target {TARGET_LUFS:.0f} LUFS), "
        f"{len(captions_manifest)} captions over {len(synced_clips)} clips",
        ducking_attenuation_db=BGM_DUCKING_ATTENUATION_DB,
        target_lufs=TARGET_LUFS,
        output_lufs=mix_report["output_lufs"],
        output_true_peak_db=mix_report["output_true_peak_db"],
        loudness_compliant=compliant,
        caption_count=len(captions_manifest),
        timeline_clips=len(synced_clips),
        total_duration_seconds=round(total_timeline_duration, 2),
    )
    telemetry.register_artifact(out_master, stage=STAGE_COMPOSITION, label="Final commercial master")

    # Per-shot in/out decisions (timeline positions already account for transition overlaps)
    shot_decisions: List[Dict[str, Any]] = []
    for idx, (start_t, end_t) in enumerate(timecodes):
        plan = shot_plans[idx] if idx < len(shot_plans) else None
        if plan is not None:
            decision = plan.model_dump()
            decision.update(source="raw_clip+voice_stem", clip=source_clips[idx])
        else:
            decision = {
                "shot_id": f"shot_{idx + 1:02d}",
                "source": "synced_clip",
                "clip": source_clips[idx],
                "action": "passthrough",
                "target_seconds": round(clip_durations[idx], 3),
                "clip_seconds": round(clip_durations[idx], 3),
                "in_point": 0.0,
                "out_point": round(clip_durations[idx], 3),
                "slowdown_factor": 1.0,
                "held_tail_seconds": 0.0,
            }
        decision.update(timeline_start=round(start_t, 3), timeline_end=round(end_t, 3))
        shot_decisions.append(decision)

    # Emit edit_decisions.json
    edit_decisions = TimedEditDecisionsArtifact(
        campaign_id=script.campaign_id,
        render_runtime="ffmpeg",
        target_aspect_ratio="9:16",
        timeline_clips=source_clips,
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
        transitions=edl_transitions,
        captions=captions_manifest,
        output_master_path=str(out_master),
        shots=shot_decisions,
        total_duration_seconds=round(total_timeline_duration, 3),
    )

    out_file = target_artifacts_dir / "edit_decisions.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(edit_decisions.model_dump(), f, ensure_ascii=False, indent=2)
    telemetry.register_artifact(out_file, stage=STAGE_COMPOSITION, label="Edit decisions")

    print(f"[Composer] SUCCESS: Final Commercial Master rendered to {out_master}")
    return edit_decisions


def _run_ffmpeg(cmd: List[str], what: str) -> None:
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg {what} failed: {res.stderr.decode('utf-8', 'replace')[-1200:]}")
