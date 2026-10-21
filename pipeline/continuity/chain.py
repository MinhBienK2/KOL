"""Chained image-to-video: the hand-off frame of clip N is the first frame of clip N+1.

Clips render strictly in order. After each clip the sharpest frame of its tail becomes the
hand-off (the cut point for the edit and the next clip's first frame), the clip is checked
against the shot contract and the approved keyframe identity, and a failing clip is re-rendered
before anything downstream is paid for.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from pipeline import face_identity
from pipeline.continuity import judge, media
from pipeline.continuity.bible import ShotBible

#: Hand-off candidates: the last N frames (~0.5s at 24fps). The last frame is often blurred or
#: mid-blink, so the sharpest of the tail wins and the clip is cut there.
HANDOFF_TAIL_FRAMES = 12
#: Hailuo's first frames after the input image are frequently a soft "settle"; the edit drops them.
CHAIN_HEAD_DROP_FRAMES = 2
#: Same-person similarity inside one video (well above the cross-person ~0.1-0.3 band).
CHAIN_IDENTITY_THRESHOLD = 0.45
MIN_CLIP_SCORE = 6.5
#: Face height / frame height on a hand-off that a chained clip starts from. A readable face at the
#: seam measured ~0.06; a rider far down the street gave no detection and the next clip swapped her.
MIN_HANDOFF_FACE_HEIGHT = 0.04
#: Identity is measured on faces turned less than this (face_identity.face_yaw), sampled this often.
FRONTAL_MAX_YAW = 0.2
IDENTITY_SAMPLE_SECONDS = 0.5
#: Below this the face belongs to another person (cross-person SFace ~0.1-0.3); no review overrules it.
IDENTITY_HARD_FLOOR = 0.30
#: Lettering the describer reads must match a printed word this closely (or be a visible part of it).
PRINTED_TEXT_MATCH = 0.8


def read_frames(video: Path, start: int, end: int) -> List[np.ndarray]:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    frames = []
    for _ in range(start, end):
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames


def video_meta(video: Path) -> dict:
    cap = cv2.VideoCapture(str(video))
    meta = {
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "fps": float(cap.get(cv2.CAP_PROP_FPS) or 24.0),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    }
    cap.release()
    return meta


def sharpness(frame: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def pick_handoff(video: Path, out_png: Path) -> dict:
    """Save the sharpest tail frame; the edit cuts the clip right after it."""
    meta = video_meta(video)
    start = max(0, meta["frames"] - HANDOFF_TAIL_FRAMES)
    tail = read_frames(video, start, meta["frames"])
    scores = [sharpness(f) for f in tail]
    best = int(np.argmax(scores))
    cv2.imwrite(str(out_png), tail[best])
    index = start + best
    return {"frame_index": index, "time": round(index / meta["fps"], 4), "sharpness": round(scores[best], 1),
            "tail_sharpness": [round(s, 1) for s in scores], **meta}


def handoff_face_height(png: Path) -> float:
    """Height of the largest face relative to the frame (0.0 when no face is detected)."""
    img = cv2.imread(str(png))
    try:
        faces = face_identity._detect_faces(img)
    except Exception:  # noqa: BLE001 - face models unavailable: do not block, the judge still runs
        return 1.0
    return round(float(faces[0][3]) / img.shape[0], 4) if len(faces) else 0.0


def printed_text_check(description: str, printed_text: List[str]) -> dict:
    """Compare quoted lettering in the describer's text with the product's printed words.

    ``ok`` is None when nothing was read (hidden or not mentioned), False when the describer read
    lettering that is no printed word or visible part of one (the model melted it: "SSHMNAT").
    """
    if not printed_text:
        return {"ok": None, "read": []}
    read = [t.strip() for t in re.findall(r'["“”]([A-Za-z][A-Za-z0-9 .\-]{1,30})["“”]', description)]
    read = [t for t in read if t.upper() == t and sum(c.isalpha() for c in t) >= 3]
    known = [w.upper() for w in printed_text]

    def matches(token: str) -> bool:
        token = token.upper().replace(" ", "")
        return any(token in word or SequenceMatcher(None, token, word).ratio() >= PRINTED_TEXT_MATCH for word in known)

    bad = [t for t in read if not matches(t)]
    return {"ok": (not bad) if read else None, "read": read, "unknown": bad}


def hard_failures(record: dict) -> List[str]:
    """Failures a director cannot overrule: the clip shows another person or a melted product."""
    out = []
    sim = (record.get("identity") or {}).get("similarity")
    if sim is not None and sim < IDENTITY_HARD_FLOOR:
        out.append(f"identity {sim} < {IDENTITY_HARD_FLOOR}: another person")
    if (record.get("printed_text") or {}).get("ok") is False:
        out.append(f"product lettering melted: read {record['printed_text']['unknown']}")
    return out


def identity_consistency(anchor_png: Path, video: Path) -> dict:
    """Same-person check against the approved keyframe, on near-frontal faces only.

    SFace scores a turned head of the same person as low as another person (measured 0.18-0.32 at
    yaw 0.35-1.0 against 0.6-0.78 frontal in one clip), so turned and missing faces are skipped and
    frames are sampled every ``IDENTITY_SAMPLE_SECONDS`` to keep enough frontal ones.
    """
    anchor = face_identity.embed_face_with_yaw(face_identity.read_image(anchor_png))
    if anchor is None:  # no face in the anchor (e.g. a product-only keyframe)
        return {"skipped": f"no face in {anchor_png}", "passed": True}
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    step = max(1, int(round(fps * IDENTITY_SAMPLE_SECONDS)))
    frames = [f for i in range(0, total, step) for f in read_frames(video, i, i + 1)]
    scores, turned = [], 0
    for frame in frames:
        found = face_identity.embed_face_with_yaw(frame)
        if found is None:
            continue
        if found[1] > FRONTAL_MAX_YAW:
            turned += 1
            continue
        scores.append(face_identity.cosine_similarity(anchor[0], found[0]))
    res = {"frames_checked": len(frames), "frontal_frames": len(scores), "turned_frames": turned,
           "threshold": CHAIN_IDENTITY_THRESHOLD, "face_found": bool(scores)}
    if not scores:
        # back view, profile ride or product insert: nothing reliable to compare, not a failure
        return {**res, "similarity": None, "passed": True, "note": "no frontal face in sampled frames"}
    ratio = sum(s >= CHAIN_IDENTITY_THRESHOLD for s in scores) / len(scores)
    return {**res, "similarity": round(float(np.median(scores)), 4), "min_similarity": round(min(scores), 4),
            "passing_ratio": round(ratio, 3), "passed": ratio >= face_identity.MIN_PASSING_FRAME_RATIO}


def seam_similarity(handoff_png: Path, next_clip: Path) -> Optional[float]:
    """Correlation of the hand-off frame and the first kept frame of the next clip (1.0 = invisible cut)."""
    frames = read_frames(next_clip, CHAIN_HEAD_DROP_FRAMES, CHAIN_HEAD_DROP_FRAMES + 1)
    if not frames:
        return None
    a = cv2.cvtColor(cv2.imread(str(handoff_png)), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(frames[0], (a.shape[1], a.shape[0])), cv2.COLOR_BGR2GRAY)
    a = cv2.resize(a, (270, 480)).astype(np.float32)
    b = cv2.resize(b, (270, 480)).astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    return round(float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-6)), 4)


def render_chain(bible: ShotBible, work: Path, *, anchor_frames: dict, max_attempts: int = 2,
                 resolution: str = "1080P", only: Optional[List[str]] = None, one: bool = False) -> dict:
    """Render shots in order. ``anchor_frames`` maps anchor shot ids to approved keyframes.

    A shot is kept only when it is approved (by the judge or ``approve --clip``) and was rendered from
    the current first frame. With ``one`` the call renders a single shot and returns, so the director
    reviews every clip before paying for the next one (and no command outlives an agent's wait limit).
    A rendered but unapproved shot stops the chain: approve it, or rewrite and re-render it.
    """
    clips_dir = work / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    state_path = work / "chain_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"shots": {}}
    for key in ("blocked_on", "rendered"):
        state.pop(key, None)
    identity_anchor: Optional[Path] = None
    previous_handoff: Optional[Path] = None

    for index, shot in enumerate(bible.shots):
        feeds_chain = index + 1 < len(bible.shots) and bible.shots[index + 1].handoff == "chain"
        if shot.handoff == "anchor":
            first_frame = Path(anchor_frames[shot.shot_id])
            identity_anchor = first_frame
        else:
            if previous_handoff is None:
                raise RuntimeError(f"{shot.shot_id}: chain shot without a previous hand-off frame")
            first_frame = previous_handoff

        done = state["shots"].get(shot.shot_id)
        if done and done.get("approved") and (only is None or shot.shot_id not in only) \
                and done.get("first_frame") == str(first_frame):
            previous_handoff = Path(done["handoff"]["path"])
            continue

        if done and not done.get("approved") and one and (only is None or shot.shot_id not in only) \
                and done.get("first_frame") == str(first_frame):
            state["blocked_on"] = shot.shot_id  # reviewed-and-failed clip: the director must decide
            break

        attempts = []
        for attempt in range(1, max_attempts + 1):
            clip = clips_dir / f"{shot.shot_id}_a{attempt}.mp4"
            record: dict = {"attempt": attempt, "clip": str(clip), "first_frame": str(first_frame)}
            try:
                media.render_i2v(first_frame, shot.motion_prompt, clip, duration=shot.duration, resolution=resolution)
                handoff_png = clips_dir / f"{shot.shot_id}_a{attempt}_handoff.png"
                record["handoff"] = {**pick_handoff(clip, handoff_png), "path": str(handoff_png)}
                record["identity"] = identity_consistency(identity_anchor, clip)
                description = media.describe_image(handoff_png, judge.DESCRIBE_QUESTION + judge.product_questions(bible))
                record["end_description"] = description
                record["verdict"] = judge.judge_description(bible, shot, description, frame_role="end")
                record["printed_text"] = printed_text_check(description, bible.product.printed_text)
                record["score"] = record["verdict"]["score"]
                record["handoff"]["face_height"] = handoff_face_height(handoff_png)
                face_ok = not feeds_chain or record["handoff"]["face_height"] >= MIN_HANDOFF_FACE_HEIGHT
                if not face_ok:
                    record["verdict"].setdefault("problems", []).append(
                        f"hand-off face height {record['handoff']['face_height']} < {MIN_HANDOFF_FACE_HEIGHT}: "
                        "the next chained clip would re-invent the talent")
                record["hard_failures"] = hard_failures(record)
                record["verdict"].setdefault("problems", []).extend(record["hard_failures"])
                record["approved"] = (record["score"] >= MIN_CLIP_SCORE and bool(record["identity"].get("passed"))
                                      and face_ok and not record["hard_failures"])
            except Exception as exc:  # noqa: BLE001
                record["error"] = str(exc)[:300]
                record["score"] = -1.0
                record["approved"] = False
            attempts.append(record)
            print(f"[chain] {shot.shot_id} attempt {attempt}: score={record.get('score')} "
                  f"identity={record.get('identity', {}).get('similarity')} approved={record['approved']}", flush=True)
            if record["approved"]:
                break

        best = max(attempts, key=lambda r: (r["approved"], r["score"]))
        entry = {**best, "attempts": attempts, "first_frame": str(first_frame), "handoff_kind": shot.handoff}
        state["shots"][shot.shot_id] = entry
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if "handoff" not in best:
            raise RuntimeError(f"{shot.shot_id}: no usable clip after {max_attempts} attempts: {best.get('error')}")
        previous_handoff = Path(best["handoff"]["path"])
        if one:
            state["rendered"] = shot.shot_id
            break

    # Seams are measured once every clip exists.
    order = [s.shot_id for s in bible.shots]
    for prev_id, next_id in zip(order, order[1:]):
        if prev_id not in state["shots"] or next_id not in state["shots"]:
            continue
        nxt = state["shots"][next_id]
        if nxt["handoff_kind"] == "chain":
            nxt["seam_similarity"] = seam_similarity(Path(state["shots"][prev_id]["handoff"]["path"]), Path(nxt["clip"]))
    state["approved"] = all(state["shots"].get(sid, {}).get("approved") for sid in order)
    state["remaining"] = [sid for sid in order if not state["shots"].get(sid, {}).get("approved")]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def rejudge_chain(bible: ShotBible, work: Path) -> dict:
    """Re-score stored end descriptions after a judge change, without new renders or vision calls.

    The selected attempt is kept: later shots were rendered from its hand-off frame.
    """
    state_path = work / "chain_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    shots = {s.shot_id: s for s in bible.shots}
    for shot_id, entry in state["shots"].items():
        for record in entry["attempts"]:
            if "end_description" not in record:
                continue
            record["verdict"] = judge.judge_description(bible, shots[shot_id], record["end_description"], frame_role="end")
            record["score"] = record["verdict"]["score"]
            record["printed_text"] = printed_text_check(record["end_description"], bible.product.printed_text)
            record["hard_failures"] = hard_failures(record)
            record["approved"] = (record["score"] >= MIN_CLIP_SCORE and bool(record["identity"].get("passed"))
                                  and not record["hard_failures"])
            if record["clip"] == entry["clip"]:
                entry.update({k: record[k] for k in ("verdict", "score", "approved")})
            print(f"[rejudge] {shot_id} attempt {record['attempt']}: score={record['score']} approved={record['approved']}", flush=True)
    state["approved"] = all(state["shots"][s.shot_id].get("approved") for s in bible.shots if s.shot_id in state["shots"]) \
        and len(state["shots"]) == len(bible.shots)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def approve_clip(work: Path, shot_id: str, clip_name: str, reason: str, order: List[str]) -> dict:
    """Director overrule: pin one rendered attempt as the shot's clip (logged with the reason)."""
    state_path = work / "chain_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    entry = state["shots"][shot_id]
    record = next(r for r in entry["attempts"] if Path(r["clip"]).name == clip_name)
    if record["clip"] != entry["clip"]:
        raise ValueError(f"{clip_name} is not the attempt later shots were chained from ({Path(entry['clip']).name}); "
                         f"re-render from {shot_id} instead")
    blocked = hard_failures(record)
    if blocked:
        raise ValueError(f"{clip_name} cannot be approved: {'; '.join(blocked)}. Re-render it, or re-anchor "
                         f"(handoff anchor + keyframe_from) so the shot starts from a clean frame")
    entry.update({"approved": True, "manual_approval": {"clip": clip_name, "reason": reason}})
    # ``order`` is every bible shot: an unrendered shot is still remaining.
    state["remaining"] = [sid for sid in order if not state["shots"].get(sid, {}).get("approved")]
    state["approved"] = not state["remaining"]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry
