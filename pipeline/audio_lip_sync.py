"""Step 6: Neural TTS Audio Production & Lip-Sync Match."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

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


@dataclass(frozen=True)
class TTSResult:
    """Outcome of one voice-stem synthesis, including how the stem was produced.

    ``engine`` is one of ``api`` (neural TTS), ``silence`` (no speech needed or local
    silent placeholder) or ``espeak`` (local robotic placeholder). ``placeholder`` is True
    whenever the stem is NOT real neural speech for a beat that has spoken text, and
    ``tts_fallback`` is True when the network TTS was wanted but failed.
    """

    path: str
    duration: float
    engine: str
    placeholder: bool = False
    tts_fallback: bool = False
    has_speech: bool = False
    error: Optional[str] = None


def _write_silence(out_path: Path, duration: float) -> None:
    subprocess.check_call(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-t", f"{duration:.3f}", "-ar", "48000", "-ac", "2", str(out_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _synthesize_local_stem(text: str, out_path: Path, target_duration: float) -> TTSResult:
    """Deterministic, network-free stem: espeak-ng speech if installed, else silence.

    Never emits a tone: a sine wave passed off as speech would be indistinguishable from a
    working voice track in downstream gates. Silence is honest and trivially detectable.
    """
    has_text = bool(text and text.strip())
    duration = max(2.0, float(target_duration or 0.0))
    espeak = shutil.which("espeak-ng") if has_text else None
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
            return TTSResult(
                str(out_path), probe_audio_duration(out_path), "espeak",
                placeholder=True, has_speech=True,
            )
        except (subprocess.SubprocessError, OSError):
            pass  # fall through to silence
        finally:
            raw.unlink(missing_ok=True)
    _write_silence(out_path, duration)
    return TTSResult(
        str(out_path), probe_audio_duration(out_path), "silence",
        placeholder=has_text, has_speech=False,
    )


def synthesize_tts_stem_ex(
    text: str,
    output_wav_path: str | Path,
    voice: str = "nova",
    model: str = "tts-1",
    target_duration: float = 4.0,
    mode: str = "api",
) -> TTSResult:
    """Voice stem synthesis with provenance.

    ``mode="api"`` calls the neural TTS (refused with ``OfflineNetworkError`` while offline);
    if the API call fails the stem falls back to the local placeholder and is flagged
    ``tts_fallback``. ``mode="local"`` never touches the network.
    """
    if mode not in ("api", "local"):
        raise ValueError(f"Unknown TTS mode {mode!r}; expected 'api' or 'local'")
    out_path = Path(output_wav_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not text or not text.strip():
        est_duration = max(3.0, target_duration)
        _write_silence(out_path, est_duration)
        return TTSResult(str(out_path), est_duration, "silence")

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
    payload = {"model": model, "input": text, "voice": voice}

    error: Optional[str] = None
    started = time.monotonic()
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with guarded_urlopen(req, operation="tts.speech", timeout=30) as resp:
            temp_mp3.write_bytes(resp.read())
    except OfflineNetworkError:
        raise
    except Exception as exc:
        error = str(exc)
    telemetry.record_api_call(
        "tts.speech",
        endpoint=url,
        request={"model": model, "voice": voice, "input_chars": len(text)},
        response={"error": error} if error else {"size_bytes": temp_mp3.stat().st_size if temp_mp3.exists() else None},
        status="error" if error else "ok",
        ok=error is None,
        duration_seconds=time.monotonic() - started,
        stage=STAGE_AUDIO_LIP_SYNC,
    )

    if error is not None or not temp_mp3.exists() or temp_mp3.stat().st_size == 0:
        temp_mp3.unlink(missing_ok=True)
        reason = error or "empty TTS response"
        print(f"[TTS] Neural TTS API call failed ({reason}); using LOCAL PLACEHOLDER stem (tts_fallback).")
        local = _synthesize_local_stem(text, out_path, target_duration)
        return TTSResult(
            local.path, local.duration, local.engine,
            placeholder=True, tts_fallback=True, has_speech=local.has_speech, error=reason,
        )

    # Convert to standard 48kHz broadcast WAV stem
    subprocess.check_call(
        ["ffmpeg", "-y", "-i", str(temp_mp3), "-ar", "48000", "-ac", "2", str(out_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    temp_mp3.unlink(missing_ok=True)
    return TTSResult(str(out_path), probe_audio_duration(out_path), "api", has_speech=True)


def synthesize_tts_stem(
    text: str,
    output_wav_path: str | Path,
    voice: str = "nova",
    model: str = "tts-1",
    target_duration: float = 4.0,
    mode: str = "api",
) -> Tuple[str, float]:
    """Generates a voiceover stem; returns ``(path, duration)``.

    Thin wrapper over :func:`synthesize_tts_stem_ex` (use that to learn whether the stem is
    a placeholder). Empty text yields clean 48 kHz stereo silence.
    """
    result = synthesize_tts_stem_ex(text, output_wav_path, voice, model, target_duration, mode)
    return result.path, result.duration


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


def produce_all_audio_and_lip_sync(
    script: ScriptArtifact | None = None,
    manifest: AssetManifestArtifact | None = None,
    artifacts_dir: Path | None = None,
    audio_dir: Path | None = None,
    synced_clips_dir: Path | None = None,
    workspace: Optional[ProjectWorkspace] = None,
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
            tts = synthesize_tts_stem_ex(
                text=beat.spoken_text,
                output_wav_path=stem_path,
                voice="nova",
                target_duration=beat.estimated_duration,
                mode=resolved_tts,
            )
        stem_duration = tts.duration
        if tts.placeholder:
            telemetry.note(
                f"[{shot_id}] voice stem is a LOCAL PLACEHOLDER ({tts.engine}), not neural speech",
                shot_id=shot_id,
                tts_engine=tts.engine,
                tts_fallback=tts.tts_fallback,
                placeholder=True,
            )
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
                "status": "tts_synthesized",
                "stem": (stem_record or {}).get("rel_path") or str(stem_path),
                "duration_seconds": round(stem_duration, 2),
                "has_speech": bool(beat.spoken_text and beat.spoken_text.strip()),
                "mix_mode": lip_dec.voiceover_mix_mode,
                "tts_engine": tts.engine,
                "placeholder": tts.placeholder,
                "tts_fallback": tts.tts_fallback or (tts.placeholder and resolved_tts == "local"),
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
                    "placeholder_audio": tts.placeholder,
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
