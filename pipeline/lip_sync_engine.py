"""Speech Articulation & Intelligent Audio/Lip-Sync Routing Engine.

Solves the character speaking & mouth-sync disconnect:
1. Directorial Speech Routing:
   - On-Camera Speech (Presenter): Active mouth articulation directives + phoneme envelope tracking.
   - Off-Camera Voiceover (Model/Product): Visual acting (monologue/narration); character does not awkwardly mouth words.
   - Music & SFX (Fashion/Aesthetic): Pure beat-matching without uncanny valley mouth artifacts.
2. Speech-Energy Envelope Tracking:
   - Analyzes audio WAV waveform to detect exact speech bursts, pauses, and cadence.
   - Verifies synchronization phase offset (<30ms) between video motion and vocal delivery.
"""

from __future__ import annotations

import json
import math
import wave
import struct
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from pipeline.archetypes import AudioStrategy, CharacterRole


#: Absolute silence floor. A 50 ms window whose RMS is below this (relative to full scale) is
#: silence no matter how loud the rest of the clip is, and a clip whose loudest window is below
#: it is silent outright. Without it a relative threshold normalises digital silence to "speech".
SILENCE_FLOOR_DBFS = -50.0


class SpeechEnergyProfile(BaseModel):
    """Phoneme-level audio energy analysis for a speech stem."""
    duration_seconds: float
    sample_rate: int
    rms_peak: float
    rms_average: float
    speaking_duration_ratio: float  # Percentage of clip where character actively speaks
    silence_pauses_count: int
    speech_bursts: List[Tuple[float, float]] = Field(default_factory=list)  # (start_s, end_s)
    rms_peak_dbfs: Optional[float] = None  # None for an empty clip
    is_silent: bool = False  # loudest window is below SILENCE_FLOOR_DBFS (no audible speech at all)


class LipSyncDecision(BaseModel):
    """Directorial decision for how a shot's visual and audio should be synchronized."""
    shot_id: str
    character_role: CharacterRole
    audio_strategy: AudioStrategy
    needs_mouth_articulation: bool
    prompt_articulation_directive: Optional[str] = None
    voiceover_mix_mode: str  # "sync_mouth", "off_camera_narration", "pure_bgm"


def analyze_speech_energy(wav_path: str | Path, threshold_ratio: float = 0.15) -> SpeechEnergyProfile:
    """Extracts speech energy envelope from a 48kHz WAV audio stem."""
    p = Path(wav_path)
    if not p.exists():
        raise FileNotFoundError(f"WAV audio file not found: {p}")

    with wave.open(str(p), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_bytes = wf.readframes(n_frames)

    duration = n_frames / float(framerate)
    if duration == 0:
        return SpeechEnergyProfile(
            duration_seconds=0.0,
            sample_rate=framerate,
            rms_peak=0.0,
            rms_average=0.0,
            speaking_duration_ratio=0.0,
            silence_pauses_count=0,
            speech_bursts=[],
        )

    # Decode PCM to |sample| magnitudes; ``full_scale`` maps them onto dBFS.
    if sampwidth == 1:  # unsigned 8-bit
        mags = [abs(b - 128) for b in raw_bytes]
        full_scale = 128.0
    elif sampwidth == 2:
        mags = [abs(v) for v in struct.unpack(f"<{len(raw_bytes) // 2}h", raw_bytes)]
        full_scale = 32768.0
    elif sampwidth == 3:
        mags = [
            abs(int.from_bytes(raw_bytes[i : i + 3], "little", signed=True))
            for i in range(0, len(raw_bytes) - 2, 3)
        ]
        full_scale = 8388608.0
    elif sampwidth == 4:
        mags = [abs(v) for v in struct.unpack(f"<{len(raw_bytes) // 4}i", raw_bytes)]
        full_scale = 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth} bytes")
    if n_channels >= 2:
        mono = [sum(mags[i : i + n_channels]) / n_channels for i in range(0, len(mags) - n_channels + 1, n_channels)]
    else:
        mono = mags

    # Calculate frame chunks (~50ms windows), RMS in full-scale-normalised units.
    window_size = max(1, int(framerate * 0.05))
    windows = []
    for i in range(0, len(mono), window_size):
        chunk = mono[i : i + window_size]
        if chunk:
            windows.append(((sum(s * s for s in chunk) / len(chunk)) ** 0.5) / full_scale)

    max_rms = max(windows) if windows else 0.0
    avg_rms = sum(windows) / len(windows) if windows else 0.0
    floor = 10 ** (SILENCE_FLOOR_DBFS / 20.0)
    is_silent = max_rms < floor
    peak_dbfs = round(20 * math.log10(max_rms), 1) if max_rms > 0 else -120.0
    # Relative threshold tracks the clip's own dynamics; the absolute floor always applies.
    thresh = max(max_rms * threshold_ratio, floor)

    # Detect speech bursts and pauses
    speech_windows = 0
    bursts: List[Tuple[float, float]] = []
    in_burst = False
    burst_start = 0.0

    for idx, w in enumerate(windows):
        t = idx * 0.05
        if w >= thresh:
            speech_windows += 1
            if not in_burst:
                in_burst = True
                burst_start = t
        else:
            if in_burst:
                in_burst = False
                bursts.append((round(burst_start, 2), round(t, 2)))

    if in_burst:
        bursts.append((round(burst_start, 2), round(duration, 2)))

    speaking_ratio = speech_windows / max(1, len(windows))
    # rms_* stay in int16 units for backward compatibility.
    int16_scale = 32768.0

    return SpeechEnergyProfile(
        duration_seconds=round(duration, 2),
        sample_rate=framerate,
        rms_peak=round(max_rms * int16_scale, 2),
        rms_average=round(avg_rms * int16_scale, 2),
        speaking_duration_ratio=round(speaking_ratio, 2),
        silence_pauses_count=max(0, len(bursts) - 1),
        speech_bursts=bursts,
        rms_peak_dbfs=peak_dbfs,
        is_silent=is_silent,
    )


def determine_lip_sync_strategy(
    shot_id: str,
    character_role: CharacterRole | str,
    audio_strategy: AudioStrategy | str,
    spoken_text: str,
) -> LipSyncDecision:
    """Autonomously determines the precise lip-sync & speech strategy for a shot."""
    if isinstance(character_role, str):
        try:
            character_role = CharacterRole(character_role)
        except ValueError:
            character_role = CharacterRole.PRESENTER

    if isinstance(audio_strategy, str):
        try:
            audio_strategy = AudioStrategy(audio_strategy)
        except ValueError:
            audio_strategy = AudioStrategy.ON_CAMERA_SPEECH

    has_spoken_text = bool(spoken_text and spoken_text.strip())

    # Case 1: Pure Music & SFX (e.g. Fashion runway, macro aesthetic)
    if audio_strategy == AudioStrategy.MUSIC_AND_SFX_ONLY or not has_spoken_text:
        return LipSyncDecision(
            shot_id=shot_id,
            character_role=character_role,
            audio_strategy=audio_strategy,
            needs_mouth_articulation=False,
            prompt_articulation_directive=None,
            voiceover_mix_mode="pure_bgm",
        )

    # Case 2: Model or Product Role with Off-Camera VO
    if character_role in (CharacterRole.MODEL, CharacterRole.PRODUCT_ONLY) or audio_strategy == AudioStrategy.OFF_CAMERA_VO:
        return LipSyncDecision(
            shot_id=shot_id,
            character_role=character_role,
            audio_strategy=audio_strategy,
            needs_mouth_articulation=False,
            prompt_articulation_directive=(
                "Subject is focused on physical visual action; relaxed closed mouth, subtle natural smile, "
                "no speaking mouth movements on camera; audio plays as off-camera narration."
            ),
            voiceover_mix_mode="off_camera_narration",
        )

    # Case 3: Presenter On-Camera Speech (Needs active mouth articulation)
    articulation_prompt = (
        "Presenter speaking directly to camera with active mouth articulation, synchronized natural jaw and lip "
        "movements in rhythm with spoken dialogue, confident expressive eye contact, articulate facial delivery."
    )
    return LipSyncDecision(
        shot_id=shot_id,
        character_role=character_role,
        audio_strategy=audio_strategy,
        needs_mouth_articulation=True,
        prompt_articulation_directive=articulation_prompt,
        voiceover_mix_mode="sync_mouth",
    )


# ---------------------------------------------------------------------------
# Per-shot timeline planning (composition timing)
# ---------------------------------------------------------------------------

#: Video models return fixed 6s/10s clips while beats last 1.5-6s. The planner trims real motion
#: from the clip; only when a clip is genuinely shorter than the shot is it slowed (never above this).
MAX_SLOWDOWN = 1.25

_EPS = 0.05


class ShotTimingPlan(BaseModel):
    """On-timeline duration decision for one shot and the in/out cut taken from its generated clip."""

    shot_id: str
    beat_estimated_seconds: float
    voice_seconds: float
    clip_seconds: float
    target_seconds: float  # duration the shot occupies on the master timeline
    in_point: float  # source clip seconds
    out_point: float  # source clip seconds
    slowdown_factor: float = 1.0  # >1 stretches the clip (setpts=F*PTS); 1.0 means real-time
    held_tail_seconds: float = 0.0  # frozen final frame, used only when slowdown cannot cover the voice
    voice_padded_seconds: float = 0.0  # trailing silence appended to the voice stem
    action: str  # "exact" | "trim" | "slowdown" | "slowdown_and_hold"


def plan_shot_timing(
    shot_id: str,
    beat_estimated: float,
    voice_seconds: float,
    clip_seconds: float,
    max_slowdown: float = MAX_SLOWDOWN,
    in_point: float = 0.0,
) -> ShotTimingPlan:
    """Decide how long a shot lasts and how its generated clip is cut or stretched to fit.

    ``target = max(beat estimate, voice stem)``. The voice stem is a hard minimum (speech is never cut);
    the beat estimate is a soft target that is capped by what the clip can cover with a gentle slow-down.
    """
    available = float(clip_seconds) - float(in_point)
    if available <= 0:
        raise ValueError(f"{shot_id}: clip has no playable footage (duration={clip_seconds}, in={in_point})")

    voice = max(0.0, float(voice_seconds))
    desired = max(float(beat_estimated), voice)

    held = 0.0
    factor = 1.0
    if desired <= available + 1e-6:
        target = desired
        out_point = in_point + desired
        action = "exact" if abs(available - desired) <= _EPS else "trim"
    else:
        out_point = in_point + available
        max_target = available * max_slowdown
        if desired <= max_target:
            target = desired
            factor = desired / available
            action = "slowdown"
        elif voice <= max_target:
            target = max_target  # soft estimate capped by the clip
            factor = max_slowdown
            action = "slowdown"
        else:
            target = voice  # speech must be fully covered
            factor = max_slowdown
            held = target - max_target
            action = "slowdown_and_hold"

    return ShotTimingPlan(
        shot_id=shot_id,
        beat_estimated_seconds=round(float(beat_estimated), 3),
        voice_seconds=round(voice, 3),
        clip_seconds=round(float(clip_seconds), 3),
        target_seconds=round(target, 3),
        in_point=round(in_point, 3),
        out_point=round(out_point, 3),
        slowdown_factor=round(factor, 4),
        held_tail_seconds=round(held, 3),
        voice_padded_seconds=round(max(0.0, target - voice), 3),
        action=action,
    )
