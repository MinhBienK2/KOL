"""Step 6: Neural TTS Audio Production & Lip-Sync Match."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import BaseModel

from pipeline import telemetry
from pipeline.config import (
    AUDIO_DIR,
    ARTIFACTS_DIR,
    BASE_DIR,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    MINIMAX_API_KEY,
    MINIMAX_BASE_URL,
    RAW_CLIPS_DIR,
    SYNCED_CLIPS_DIR,
)
from pipeline.archetypes import AudioStrategy, CharacterRole
from pipeline.lip_sync_engine import analyze_speech_energy, determine_lip_sync_strategy
from pipeline.offline import OfflineNetworkError, guard_network, guarded_urlopen, is_offline, offline_mode
from pipeline.schemas import AssetManifestArtifact, ScriptArtifact
from pipeline.workspace import ProjectWorkspace

STAGE_AUDIO_LIP_SYNC = telemetry.stage_number("audio_lip_sync")


def _ensure_stage_started(total: int) -> None:
    """Open the audio/lip-sync stage with its beat total, unless the director already did."""
    recorder = telemetry.current()
    if recorder is not None and recorder.snapshot().get("current_stage") == STAGE_AUDIO_LIP_SYNC:
        return
    telemetry.start_stage(STAGE_AUDIO_LIP_SYNC, total=total)


def probe_audio_duration(file_path: str | Path) -> float:
    """Probes media duration using ffprobe."""
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
    data = json.loads(res)
    return float(data["format"]["duration"])


class TTSUnavailableError(RuntimeError):
    """Neural TTS could not produce speech and the caller asked for strict behaviour."""


class VoiceStemResult(BaseModel):
    """A rendered voice stem plus whether it is genuine speech or a degraded placeholder.

    ``engine``: ``api`` (neural TTS), ``silence`` (silent stem) or ``espeak`` (local robotic
    speech). ``placeholder`` is True whenever a beat with spoken text did NOT get neural
    speech. ``fallback`` is True only when the neural TTS was wanted but failed (``api`` mode).
    """

    path: str
    duration: float
    fallback: bool = False  # True when TTS failed and the stem is a silent placeholder
    engine: str = "api"
    placeholder: bool = False


#: Floor for a silent (music/SFX-only) stem; never stretch a short beat to a long one.
MIN_SILENT_STEM_SECONDS = 0.5


def _write_silence(out_path: Path, duration: float) -> None:
    cmd_silence = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-t",
        f"{duration:.3f}",
        "-ar",
        "48000",
        str(out_path),
    ]
    subprocess.check_call(cmd_silence, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _synthesize_local_stem(text: str, out_path: Path, target_duration: float) -> VoiceStemResult:
    """Deterministic, network-free stem for a beat with spoken text.

    espeak-ng speech (Vietnamese voice) when installed, otherwise digital silence of the
    beat's duration. Never a tone: a sine wave passed off as speech is indistinguishable from
    a working voice track downstream, whereas silence is honest and trivially detectable.
    """
    duration = max(2.0, float(target_duration or 0.0))
    espeak = shutil.which("espeak-ng")
    if espeak:
        raw = out_path.with_suffix(".espeak.wav")
        try:
            subprocess.check_call(
                [espeak, "-v", "vi", "-s", "150", "-w", str(raw), text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.check_call(
                [
                    "ffmpeg", "-y", "-i", str(raw), "-af", f"apad=whole_dur={duration:.3f}",
                    "-t", f"{duration:.3f}", "-ar", "48000", "-ac", "2", str(out_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return VoiceStemResult(
                path=str(out_path), duration=probe_audio_duration(out_path), engine="espeak", placeholder=True
            )
        except (subprocess.SubprocessError, OSError):
            pass  # fall through to silence
        finally:
            raw.unlink(missing_ok=True)
    _write_silence(out_path, duration)
    return VoiceStemResult(
        path=str(out_path), duration=probe_audio_duration(out_path), engine="silence", placeholder=True
    )


def synthesize_voice_stem(
    text: str,
    output_wav_path: str | Path,
    voice: str = "nova",
    model: str = "tts-1",
    target_duration: float = 4.0,
    strict: bool = False,
    mode: str = "api",
) -> VoiceStemResult:
    """Generates a voiceover stem (neural TTS, or a local placeholder when ``mode="local"``).

    Empty text (music/SFX-only beats) yields clean 48kHz stereo silence of ``target_duration``.
    ``mode="local"`` never touches the network (espeak-ng or silence; flagged ``placeholder``).
    ``mode="api"`` is refused with ``OfflineNetworkError`` while offline. If the TTS endpoint
    fails, ``strict`` raises :class:`TTSUnavailableError`; otherwise a *silent* placeholder of
    the estimated spoken length is written and ``fallback`` is flagged so the
    director/telemetry can surface it (a beep must never ship as a voiceover).
    """
    if mode not in ("api", "local"):
        raise ValueError(f"Unknown TTS mode {mode!r}; expected 'api' or 'local'")
    out_path = Path(output_wav_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not text or not text.strip():
        duration = max(MIN_SILENT_STEM_SECONDS, target_duration)
        _write_silence(out_path, duration)
        return VoiceStemResult(path=str(out_path), duration=duration, engine="silence")

    if mode == "local":
        return _synthesize_local_stem(text, out_path, target_duration)

    url = f"{MINIMAX_BASE_URL}/v1/audio/speech"
    guard_network("tts.speech", url)
    temp_mp3 = out_path.with_suffix(".temp.mp3")
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
    }

    success = False
    failure = ""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        with guarded_urlopen(req, operation="tts.speech", timeout=30) as resp:
            temp_mp3.write_bytes(resp.read())
            success = True
    except OfflineNetworkError:
        raise
    except Exception as exc:
        failure = str(exc)

    if not success or not temp_mp3.exists() or temp_mp3.stat().st_size == 0:
        temp_mp3.unlink(missing_ok=True)
        if strict:
            raise TTSUnavailableError(f"Neural TTS failed ({failure or 'empty response'})")
        print(f"[TTS] Neural TTS API call failed ({failure or 'empty response'}); writing SILENT placeholder stem.")
        est_duration = max(2.5, min(12.0, len(text) * 0.08))
        _write_silence(out_path, est_duration)
        return VoiceStemResult(
            path=str(out_path), duration=est_duration, fallback=True, engine="silence", placeholder=True
        )

    # Convert to standard 48kHz broadcast WAV stem
    cmd_convert = [
        "ffmpeg",
        "-y",
        "-i",
        str(temp_mp3),
        "-ar",
        "48000",
        "-ac",
        "2",
        str(out_path),
    ]
    subprocess.check_call(cmd_convert, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    temp_mp3.unlink(missing_ok=True)

    return VoiceStemResult(path=str(out_path), duration=probe_audio_duration(out_path))


def synthesize_tts_stem(
    text: str,
    output_wav_path: str | Path,
    voice: str = "nova",
    model: str = "tts-1",
    target_duration: float = 4.0,
    mode: str = "api",
) -> Tuple[str, float]:
    """Backwards-compatible tuple wrapper around :func:`synthesize_voice_stem`."""
    res = synthesize_voice_stem(
        text, output_wav_path, voice=voice, model=model, target_duration=target_duration, mode=mode
    )
    return res.path, res.duration


def align_lip_sync_clip(
    raw_video_path: str | Path,
    audio_stem_path: str | Path,
    output_synced_path: str | Path,
) -> str:
    """Synchronizes video timing and muxes audio stem with zero phase offset (<50ms)."""
    raw_p = Path(raw_video_path)
    audio_p = Path(audio_stem_path)
    out_p = Path(output_synced_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if not raw_p.exists():
        raise FileNotFoundError(f"Raw video clip not found: {raw_p}")
    if not audio_p.exists():
        raise FileNotFoundError(f"Audio stem not found: {audio_p}")

    v_dur = probe_audio_duration(raw_p)
    a_dur = probe_audio_duration(audio_p)

    # Natural cinematic 1.0x playback speed (never distort motion with extreme setpts acceleration)
    target_dur = a_dur
    if v_dur < target_dur:
        pad_needed = target_dur - v_dur + 0.1
        vf = f"[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration={pad_needed:.2f}[v]"
    else:
        vf = f"[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(raw_p),
        "-i",
        str(audio_p),
        "-filter_complex",
        vf,
        "-map",
        "[v]",
        "-map",
        "1:a",
        "-t",
        f"{target_dur:.2f}",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        str(out_p),
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(f"Lip-sync alignment failed: {res.stderr.decode('utf-8')}")

    return str(out_p)


def _flag_ledger_tts_fallback(shot_id: str, stem: VoiceStemResult) -> None:
    """Record ``tts_fallback`` on the shot's Prompt Ledger entry so verification sees it.

    ``record_prompt`` replaces the entry's prompt/stage, so the existing ones are passed back.
    """
    recorder = telemetry.current()
    if recorder is None:
        return
    existing = (recorder.snapshot().get("prompts") or {}).get(shot_id) or {}
    telemetry.record_prompt(
        shot_id,
        existing.get("prompt") or "",
        stage=int(existing.get("stage") or 5),
        tts_fallback=True,
        tts_engine=stem.engine,
        tts_placeholder=True,
    )


def produce_all_audio_and_lip_sync(
    script: ScriptArtifact | None = None,
    manifest: AssetManifestArtifact | None = None,
    artifacts_dir: Path | None = None,
    audio_dir: Path | None = None,
    synced_clips_dir: Path | None = None,
    workspace: Optional[ProjectWorkspace] = None,
    strict_tts: bool = False,
    offline: Optional[bool] = None,
    tts_mode: str = "auto",
) -> Tuple[List[str], List[str]]:
    """Generates all audio stems and synchronizes each shot's video with its speech.

    ``offline`` defaults to :func:`pipeline.offline.is_offline`. ``tts_mode`` is ``"auto"``
    (local when offline, else API), ``"api"`` or ``"local"``. Local stems are silent (or
    espeak-ng speech when installed), deterministic, never touch the network and are flagged
    ``placeholder`` / ``tts_fallback`` in telemetry. ``tts_mode="api"`` while offline raises
    ``OfflineNetworkError``.
    """
    if tts_mode not in ("auto", "api", "local"):
        raise ValueError(f"Unknown tts_mode {tts_mode!r}; expected 'auto', 'api' or 'local'")
    is_off = is_offline() if offline is None else bool(offline)
    resolved_tts = "local" if (tts_mode == "local" or (tts_mode == "auto" and is_off)) else "api"
    if resolved_tts == "api" and is_off:
        raise OfflineNetworkError(
            "Offline mode: tts_mode='api' would call the paid TTS service; use tts_mode='local' or 'auto'."
        )
    target_artifacts_dir = workspace.artifacts_dir if workspace is not None else (artifacts_dir or ARTIFACTS_DIR)
    target_audio_dir = workspace.audio_dir if workspace is not None else (audio_dir or AUDIO_DIR)
    target_audio_dir.mkdir(parents=True, exist_ok=True)
    target_synced_dir = workspace.synced_clips_dir if workspace is not None else (synced_clips_dir or SYNCED_CLIPS_DIR)
    target_synced_dir.mkdir(parents=True, exist_ok=True)

    if script is None:
        with open(target_artifacts_dir / "script.json", "r", encoding="utf-8") as f:
            script = ScriptArtifact.model_validate(json.load(f))

    if manifest is None:
        with open(target_artifacts_dir / "asset_manifest.json", "r", encoding="utf-8") as f:
            manifest = AssetManifestArtifact.model_validate(json.load(f))

    audio_stems: List[str] = []
    synced_clips: List[str] = []

    # Map raw clips by shot_id or index
    raw_clips = list(manifest.raw_video_clips)

    n_beats = len(script.beats)
    _ensure_stage_started(n_beats)

    for idx, beat in enumerate(script.beats):
        shot_id = f"shot_{idx + 1:02d}"
        stem_path = target_audio_dir / f"voice_{shot_id}.wav"

        lip_dec = determine_lip_sync_strategy(
            shot_id=shot_id,
            character_role=getattr(beat, "character_role", CharacterRole.MODEL),
            audio_strategy=getattr(beat, "audio_strategy", AudioStrategy.OFF_CAMERA_VO),
            spoken_text=beat.spoken_text,
        )
        print(f"[AudioEngine] [{shot_id}] Speech Mode: {lip_dec.voiceover_mix_mode} | Spoken text: '{beat.spoken_text[:30]}...'")
        # Local TTS also scopes the global guard so nothing below can reach the network.
        with offline_mode(True) if resolved_tts == "local" else contextlib.nullcontext():
            stem = synthesize_voice_stem(
                text=beat.spoken_text,
                output_wav_path=stem_path,
                voice="nova",
                target_duration=beat.estimated_duration,
                strict=strict_tts,
                mode=resolved_tts,
            )
        stem_duration = stem.duration
        # Local placeholders are a deliberate offline fallback: flag them like a failed TTS.
        tts_fallback = stem.fallback or (stem.placeholder and resolved_tts == "local")
        if stem.fallback:
            telemetry.note(
                f"[{shot_id}] TTS unavailable: silent placeholder stem written; re-run stage 6 once TTS recovers",
                shot_id=shot_id,
                tts_fallback=True,
            )
        elif stem.placeholder:
            telemetry.note(
                f"[{shot_id}] offline: voice stem is a LOCAL PLACEHOLDER ({stem.engine}), not neural speech",
                shot_id=shot_id,
                tts_fallback=True,
                tts_engine=stem.engine,
                placeholder=True,
            )
        if tts_fallback:
            _flag_ledger_tts_fallback(shot_id, stem)
        audio_stems.append(str(stem_path))
        recorder = telemetry.current()
        stem_record = (
            recorder.register_artifact(stem_path, stage=STAGE_AUDIO_LIP_SYNC, label=f"{shot_id} voice stem")
            if recorder is not None
            else None
        )
        telemetry.stage_progress(
            STAGE_AUDIO_LIP_SYNC,
            idx + 1,
            n_beats,
            unit="beats",
            label=f"{shot_id} TTS",
            item={
                "id": shot_id,
                "status": "tts_fallback_silent" if tts_fallback else "tts_synthesized",
                "tts_fallback": tts_fallback,
                "tts_engine": stem.engine,
                "placeholder": stem.placeholder,
                "stem": (stem_record or {}).get("rel_path") or str(stem_path),
                "duration_seconds": round(stem_duration, 2),
                "has_speech": bool(beat.spoken_text and beat.spoken_text.strip()),
                "mix_mode": lip_dec.voiceover_mix_mode,
            },
        )
        try:
            energy_prof = analyze_speech_energy(stem_path)
            print(f"[LipSync] [{shot_id}] Audio Profile: {energy_prof.duration_seconds}s | Speaking ratio: {energy_prof.speaking_duration_ratio*100:.0f}% | Bursts: {len(energy_prof.speech_bursts)}")
            telemetry.note(
                f"[{shot_id}] speech energy: {energy_prof.duration_seconds:.2f}s, "
                f"speaking {energy_prof.speaking_duration_ratio * 100:.0f}%, {len(energy_prof.speech_bursts)} bursts",
                shot_id=shot_id,
                duration_seconds=energy_prof.duration_seconds,
                speaking_duration_ratio=energy_prof.speaking_duration_ratio,
                rms_peak=energy_prof.rms_peak,
                silence_pauses=energy_prof.silence_pauses_count,
                speech_bursts=len(energy_prof.speech_bursts),
            )
        except Exception:
            pass

        # Find matching raw video clip
        matching_raw = None
        for raw_c in raw_clips:
            if shot_id in Path(raw_c).name:
                matching_raw = raw_c
                break
        if not matching_raw and idx < len(raw_clips):
            matching_raw = raw_clips[idx]

        if matching_raw:
            synced_path = target_synced_dir / f"{shot_id}.mp4"
            print(f"[LipSync] Aligning video & audio for {shot_id} -> {synced_path}...")
            align_lip_sync_clip(
                raw_video_path=matching_raw,
                audio_stem_path=stem_path,
                output_synced_path=synced_path,
            )
            synced_clips.append(str(synced_path))
            recorder = telemetry.current()
            synced_record = (
                recorder.register_artifact(
                    synced_path, stage=STAGE_AUDIO_LIP_SYNC, label=f"{shot_id} lip-synced clip"
                )
                if recorder is not None
                else None
            )
            telemetry.stage_progress(
                STAGE_AUDIO_LIP_SYNC,
                idx + 1,
                n_beats,
                unit="beats",
                label=f"{shot_id} lip-sync",
                item={
                    "id": shot_id,
                    "status": "lip_sync_aligned",
                    "synced": (synced_record or {}).get("rel_path") or str(synced_path),
                    "mix_mode": lip_dec.voiceover_mix_mode,
                    "needs_mouth_articulation": bool(lip_dec.needs_mouth_articulation),
                    "placeholder_video": Path(f"{matching_raw}.placeholder.json").exists(),
                    "placeholder_audio": stem.placeholder,
                    # Same id as the TTS item above: progress items are keyed by id, so the
                    # fallback flag must be repeated here or it is overwritten.
                    "tts_fallback": tts_fallback,
                    "tts_engine": stem.engine,
                    "duration_seconds": round(stem_duration, 2),
                },
            )
        else:
            telemetry.stage_progress(
                STAGE_AUDIO_LIP_SYNC,
                idx + 1,
                n_beats,
                unit="beats",
                label=f"{shot_id} skipped",
                item={
                    "id": shot_id,
                    "status": "skipped_off_camera",
                    "reason": "no rendered raw clip matched this beat",
                    "mix_mode": lip_dec.voiceover_mix_mode,
                },
            )

    # Update manifest
    manifest.audio_stems = audio_stems
    manifest.synced_video_clips = synced_clips
    with open(target_artifacts_dir / "asset_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)

    return audio_stems, synced_clips
