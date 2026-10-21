"""Edit the chained clips into the master: seam trims, colour match, voice-over, music, captions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from pipeline.composer import measure_loudness, wrap_caption
from pipeline.continuity import media
from pipeline.continuity.bible import ShotBible
from pipeline.continuity.chain import CHAIN_HEAD_DROP_FRAMES

OUT_W, OUT_H, FPS = 1080, 1920, 24
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
#: Chained clips are pulled this far toward the anchor keyframe's colour statistics (LAB mean/std).
COLOR_MATCH_STRENGTH = 0.6
VO_LEAD_IN = 0.3
VO_GAP = 0.2
MUSIC_GAIN_DB = -20


def _run(cmd: List[str]) -> None:
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])}...\n{res.stderr.decode('utf-8', 'replace')[-1500:]}")


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.decode().strip())


def lab_stats(img: np.ndarray) -> tuple:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    return lab.reshape(-1, 3).mean(0), lab.reshape(-1, 3).std(0) + 1e-6


def color_matched_segment(clip: Path, out: Path, start_frame: int, end_frame: int, ref_stats: Optional[tuple]) -> int:
    """Write frames [start, end] scaled to 1080x1920, pulled toward ``ref_stats``; returns frame count."""
    cap = cv2.VideoCapture(str(clip))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    frames = []
    for _ in range(start_frame, end_frame + 1):
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    if ref_stats is not None and frames:
        # One transfer for the whole segment (computed on its own mean stats) so it cannot flicker.
        mean, std = lab_stats(np.concatenate([cv2.resize(f, (135, 240)) for f in frames[:: max(1, len(frames) // 12)]]))
        r_mean, r_std = ref_stats
        k = COLOR_MATCH_STRENGTH
        scale = 1 + k * (r_std / std - 1)
        shift = k * (r_mean - mean)
    writer = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{OUT_W}x{OUT_H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", str(out)],
        stdin=subprocess.PIPE,
    )
    for frame in frames:
        frame = cv2.resize(frame, (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
        if ref_stats is not None:
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
            lab = (lab - mean) * scale + mean + shift
            frame = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
        writer.stdin.write(frame.tobytes())
    writer.stdin.close()
    writer.wait()
    return len(frames)


def build_voice(bible: ShotBible, work: Path, timeline: List[dict]) -> List[dict]:
    """TTS each shot's line and place it on the edit timeline without overlaps (J-cuts allowed)."""
    audio_dir = work / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    placed, cursor = [], 0.0
    for shot, seg in zip(bible.shots, timeline):
        if not shot.vo_text.strip():
            continue
        mp3 = audio_dir / f"vo_{shot.shot_id}.mp3"
        if not mp3.exists():
            media.speech(shot.vo_text, mp3, voice=bible.voice.voice, speed=bible.voice.speed)
        dur = probe_duration(mp3)
        start = max(seg["start"] + VO_LEAD_IN, cursor + VO_GAP)
        placed.append({"shot_id": shot.shot_id, "path": str(mp3), "start": round(start, 3), "duration": round(dur, 3),
                       "end": round(start + dur, 3), "text": shot.vo_text, "segment_end": seg["end"]})
        cursor = start + dur
    return placed


def caption_filters(bible: ShotBible, timeline: List[dict], voice: List[dict], work: Path) -> List[str]:
    """drawtext filters: the shot's on-screen title up top and the VO line as a lower-third subtitle."""
    text_dir = work / "captions"
    text_dir.mkdir(parents=True, exist_ok=True)
    filters = []
    for shot, seg in zip(bible.shots, timeline):
        if shot.on_screen_text.strip():
            path = text_dir / f"title_{shot.shot_id}.txt"
            path.write_text("\n".join(wrap_caption(shot.on_screen_text, OUT_W * 0.82, 64, FONT)), encoding="utf-8")
            filters.append(
                f"drawtext=fontfile={FONT}:textfile={path}:fontsize=64:fontcolor=white:line_spacing=10:"
                f"box=1:boxcolor=black@0.35:boxborderw=24:x=(w-text_w)/2:y=h*0.12:"
                f"enable='between(t,{seg['start']:.2f},{seg['end']:.2f})'"
            )
    for vo in voice:
        path = text_dir / f"sub_{vo['shot_id']}.txt"
        path.write_text("\n".join(wrap_caption(vo["text"], OUT_W * 0.84, 46, FONT)), encoding="utf-8")
        filters.append(
            f"drawtext=fontfile={FONT}:textfile={path}:fontsize=46:fontcolor=white:line_spacing=8:"
            f"borderw=3:bordercolor=black@0.85:x=(w-text_w)/2:y=h*0.80:"
            f"enable='between(t,{vo['start']:.2f},{vo['end']:.2f})'"
        )
    return filters


def compose(bible: ShotBible, work: Path, state: dict, *, music_path: Optional[Path] = None) -> dict:
    seg_dir = work / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    order = [s.shot_id for s in bible.shots]
    anchor_png = Path(state["shots"][order[0]]["first_frame"])
    ref_stats = lab_stats(cv2.imread(str(anchor_png)))

    timeline, t = [], 0.0
    for i, shot in enumerate(bible.shots):
        entry = state["shots"][shot.shot_id]
        start_frame = CHAIN_HEAD_DROP_FRAMES if shot.handoff == "chain" else 0
        nxt = bible.shots[i + 1] if i + 1 < len(bible.shots) else None
        # Cut on the hand-off frame when the next clip continues from it; otherwise keep the tail.
        end_frame = entry["handoff"]["frame_index"] if nxt is not None and nxt.handoff == "chain" else entry["handoff"]["frames"] - 1
        seg = seg_dir / f"{shot.shot_id}.mp4"
        n = color_matched_segment(Path(entry["clip"]), seg, start_frame, end_frame,
                                  ref_stats if shot.handoff == "chain" else None)
        dur = n / FPS
        timeline.append({"shot_id": shot.shot_id, "segment": str(seg), "start": round(t, 3), "end": round(t + dur, 3),
                         "in_frame": start_frame, "out_frame": end_frame, "frames": n})
        t += dur
    total = t

    concat_list = seg_dir / "concat.txt"
    concat_list.write_text("".join(f"file '{Path(s['segment']).resolve()}'\n" for s in timeline), encoding="utf-8")
    picture = work / "picture.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(picture)])

    voice = build_voice(bible, work, timeline)
    if voice and voice[-1]["end"] > total - 0.2:
        raise RuntimeError(f"voice-over runs to {voice[-1]['end']:.2f}s but the picture is {total:.2f}s; shorten vo_text")

    if music_path is None and bible.voice.music_prompt:
        music_path = work / "audio" / "music.mp3"
        if not music_path.exists():
            try:
                media.music(bible.voice.music_prompt, music_path)
            except Exception as exc:  # noqa: BLE001 - music is optional; ship VO-only rather than fail
                print(f"[compose] music skipped: {exc}", flush=True)
                music_path = None

    inputs = ["-i", str(picture)]
    mix_parts, labels = [], []
    for k, vo in enumerate(voice):
        inputs += ["-i", vo["path"]]
        ms = int(vo["start"] * 1000)
        mix_parts.append(f"[{k + 1}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms},apad[v{k}]")
        labels.append(f"[v{k}]")
    filter_parts = list(mix_parts)
    vo_mix = "[vo]"
    if labels:
        filter_parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,atrim=0:{total:.3f},aformat=sample_rates=48000:channel_layouts=stereo[vo]")
    if music_path:
        inputs += ["-i", str(music_path)]
        mi = len(voice) + 1
        filter_parts.append(
            f"[{mi}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.3f},volume={MUSIC_GAIN_DB}dB,"
            f"afade=t=in:d=0.8,afade=t=out:st={max(0.0, total - 1.5):.3f}:d=1.5[mus]"
        )
        filter_parts.append("[vo]asplit[vo1][vo2]")
        filter_parts.append("[mus][vo2]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck]")
        filter_parts.append("[vo1][duck]amix=inputs=2:normalize=0:duration=first[mixraw]")
        vo_mix = "[mixraw]"
    filter_parts.append(f"{vo_mix}loudnorm=I=-14:TP=-1.5:LRA=11,aformat=sample_rates=48000:channel_layouts=stereo[aout]")
    vf = ",".join(caption_filters(bible, timeline, voice, work)) or "null"
    filter_parts.append(f"[0:v]{vf}[vout]")
    master = work / "master.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filter_parts),
          "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
          "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(master)])

    report = {"master": str(master), "duration": round(total, 3), "timeline": timeline, "voice": voice,
              "music": str(music_path) if music_path else None, "loudness": measure_loudness(master)}
    (work / "compose_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
