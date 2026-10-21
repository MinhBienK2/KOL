"""Gates on the finished master, plus the contact sheet the reviewing director looks at."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import cv2
import numpy as np

from pipeline import asr
from pipeline.continuity.bible import ShotBible
from pipeline.continuity.chain import CHAIN_IDENTITY_THRESHOLD, identity_consistency

DURATION_TOLERANCE = 0.15
#: Correlation of the frames either side of a chained cut; a hidden seam stays well above this.
SEAM_MIN_CORRELATION = 0.85
#: Mean absolute LAB difference across a chained cut (colour jump).
SEAM_MAX_COLOR_DELTA = 6.0
#: A seam may be this much below the clip's own 2-frame correlation (measured: a visible jump was
#: 0.72 against 0.90 inside; a hidden cut in fast motion was 0.76 against 0.64 inside).
SEAM_MOTION_MARGIN = 0.05
LUFS_TARGET, LUFS_TOLERANCE = -14.0, 1.5
VO_MAX_CER = 0.2


def _frame(video: Path, index: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"cannot read frame {index} of {video}")
    return frame


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = cv2.resize(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), (270, 480)).astype(np.float32)
    b = cv2.resize(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), (270, 480)).astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6))


def _color_delta(a: np.ndarray, b: np.ndarray) -> float:
    la = cv2.cvtColor(cv2.resize(a, (135, 240)), cv2.COLOR_BGR2LAB).astype(np.float32)
    lb = cv2.cvtColor(cv2.resize(b, (135, 240)), cv2.COLOR_BGR2LAB).astype(np.float32)
    return float(np.abs(la.reshape(-1, 3).mean(0) - lb.reshape(-1, 3).mean(0)).mean())


def contact_sheet(master: Path, timeline: List[dict], out: Path) -> Path:
    """Three frames per shot (head, middle, tail) in one row each."""
    rows = []
    fps = 24
    for seg in timeline:
        start, end = int(round(seg["start"] * fps)), int(round(seg["end"] * fps)) - 1
        picks = [start, (start + end) // 2, end]
        rows.append(np.hstack([cv2.resize(_frame(master, i), (270, 480)) for i in picks]))
    sheet = np.vstack(rows)
    cv2.imwrite(str(out), sheet)
    return out


def verify(bible: ShotBible, work: Path, state: dict, report: dict) -> dict:
    master = Path(report["master"])
    timeline = report["timeline"]
    gates = {}

    duration = report["duration"]
    gates["duration"] = {"value": duration, "target": bible.target_duration,
                         "passed": abs(duration - bible.target_duration) <= DURATION_TOLERANCE * bible.target_duration}

    seams = []
    fps = 24
    for prev, nxt, shot in zip(timeline, timeline[1:], bible.shots[1:]):
        if shot.handoff != "chain":
            continue
        end = int(round(prev["end"] * fps))
        a = _frame(master, end - 1)
        b = _frame(master, int(round(nxt["start"] * fps)))
        corr, delta = _corr(a, b), _color_delta(a, b)
        # Fast motion lowers frame-to-frame correlation inside a clip too, so the seam is held to the
        # clip's own 2-frame change (the dropped head frames make the seam a 2-frame step).
        inside = sorted(_corr(_frame(master, end - 4 - k), _frame(master, end - 2 - k)) for k in (0, 2, 5))[1]
        required = min(SEAM_MIN_CORRELATION, inside - SEAM_MOTION_MARGIN)
        seams.append({"cut": f"{prev['shot_id']}->{nxt['shot_id']}", "correlation": round(corr, 4),
                      "in_clip_correlation": round(inside, 4), "required": round(required, 4),
                      "color_delta": round(delta, 2),
                      "passed": corr >= required and delta <= SEAM_MAX_COLOR_DELTA})
    gates["seams"] = {"cuts": seams, "passed": all(s["passed"] for s in seams)}

    anchor = Path(state["shots"][bible.shots[0].shot_id]["first_frame"])
    ident = identity_consistency(anchor, master)
    gates["identity"] = {**ident, "threshold": CHAIN_IDENTITY_THRESHOLD}

    expected = " ".join(s.vo_text for s in bible.shots if s.vo_text.strip())
    try:
        transcript = asr.transcribe(master, language="vi", timeout=120)
        match = asr.speech_match(expected, transcript, threshold=VO_MAX_CER)
        gates["voice"] = {"transcript": transcript, **match, "passed": match["ok"]}
    except Exception as exc:  # noqa: BLE001
        gates["voice"] = {"error": str(exc), "passed": False}

    loud = report["loudness"]
    gates["loudness"] = {**loud, "passed": abs(loud["integrated_lufs"] - LUFS_TARGET) <= LUFS_TOLERANCE}

    gates["clips"] = {
        "per_shot": {sid: {"score": e.get("score"), "approved": e.get("approved"), "seam_similarity": e.get("seam_similarity")}
                     for sid, e in state["shots"].items()},
        "passed": bool(state.get("approved")),
    }
    sheet = contact_sheet(master, timeline, work / "contact_sheet.jpg")
    result = {"passed": all(g.get("passed") for g in gates.values()), "gates": gates, "contact_sheet": str(sheet)}
    (work / "verify_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
