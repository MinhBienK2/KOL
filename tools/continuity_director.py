#!/usr/bin/env python3
"""Continuity director CLI: Shot Bible -> anchor keyframes -> chained clips -> master -> gates.

Every step writes artifacts under ``--work`` and prints one JSON object (``--json``) so the
director agent can review it before paying for the next step.

  lint       validate the Shot Bible (no network)
  keyframes  generate + judge candidates for every anchor shot
  approve    pin a keyframe candidate (--candidate) or a rendered clip (--clip) by hand, with --reason
  rejudge    re-score rendered clips from their stored descriptions (after a judge change; no renders)
  render     chained Hailuo I2V clips, judged per clip (re-render failures); --one = next shot only
  compose    seam trims, colour match, VO, music, captions -> master.mp4
  verify     gates on the master + contact_sheet.jpg
  all        every step in order, stopping at the first failed review

Exit codes: 0 ok | 1 error | 2 invalid bible/prerequisite | 3 a review gate failed (inspect, fix, rerun the step).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.continuity import bible as bible_mod  # noqa: E402
from pipeline.continuity.chain import approve_clip, rejudge_chain, render_chain  # noqa: E402
from pipeline.continuity.compose import compose  # noqa: E402
from pipeline.continuity.keyframes import generate_anchor  # noqa: E402
from pipeline.continuity.verify import verify  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent.parent
EXIT_OK, EXIT_ERROR, EXIT_INVALID, EXIT_REVIEW = 0, 1, 2, 3


def _emit(payload: dict, as_json: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=None if as_json else 2))


def _anchor_frames(bible: bible_mod.ShotBible, work: Path) -> dict:
    frames, missing = {}, []
    for shot in bible.shots:
        if shot.handoff != "anchor":
            continue
        kf = work / "keyframes" / f"{shot.keyframe_from or shot.shot_id}_keyframe.png"
        qc_path = work / "keyframes" / f"{shot.keyframe_from or shot.shot_id}_keyframe_qc.json"
        qc = json.loads(qc_path.read_text(encoding="utf-8")) if qc_path.exists() else {}
        if kf.exists() and (qc.get("approved") or qc.get("manual_approval")):
            frames[shot.shot_id] = str(kf)
        else:
            missing.append(shot.shot_id)
    if missing:
        raise FileNotFoundError(f"no approved keyframe for {missing}; run `keyframes` or `approve`")
    return frames


def step_lint(bible, work, args) -> tuple[int, dict]:
    res = bible_mod.lint_bible(bible, BASE_DIR)
    return (EXIT_OK if res["ok"] else EXIT_INVALID), {"step": "lint", **res}


def step_keyframes(bible, work, args) -> tuple[int, dict]:
    out = {}
    for shot in bible.shots:
        if shot.handoff == "anchor" and not shot.keyframe_from and (not args.shots or shot.shot_id in args.shots):
            qc = generate_anchor(bible, shot, BASE_DIR, work / "keyframes", candidates=args.candidates, provider=args.provider)
            out[shot.shot_id] = {k: qc[k] for k in ("selected", "selected_score", "approved", "identity_locked_to_reference")}
            out[shot.shot_id]["problems"] = next((c.get("verdict", {}).get("problems") for c in qc["candidates"]
                                                 if c["candidate"] == qc["selected"]), None)
    ok = all(v["approved"] for v in out.values())
    return (EXIT_OK if ok else EXIT_REVIEW), {"step": "keyframes", "shots": out, "dir": str(work / "keyframes")}


def step_approve(bible, work, args) -> tuple[int, dict]:
    if args.clip:
        entry = approve_clip(work, args.shot, args.clip, args.reason, [s.shot_id for s in bible.shots])
        return EXIT_OK, {"step": "approve", "shot": args.shot, "clip": args.clip, "manual_approval": entry["manual_approval"]}
    kdir = work / "keyframes"
    cand = kdir / args.candidate
    if not cand.exists():
        return EXIT_INVALID, {"step": "approve", "error": f"candidate not found: {cand}"}
    shutil.copyfile(cand, kdir / f"{args.shot}_keyframe.png")
    qc_path = kdir / f"{args.shot}_keyframe_qc.json"
    qc = json.loads(qc_path.read_text(encoding="utf-8")) if qc_path.exists() else {"shot_id": args.shot}
    qc.update({"selected": args.candidate, "manual_approval": {"candidate": args.candidate, "reason": args.reason}})
    qc_path.write_text(json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")
    return EXIT_OK, {"step": "approve", "shot": args.shot, "candidate": args.candidate}


def step_render(bible, work, args) -> tuple[int, dict]:
    state = render_chain(bible, work, anchor_frames=_anchor_frames(bible, work), max_attempts=args.attempts,
                         resolution=args.resolution, only=args.shots or None, one=args.one)
    summary = {sid: {"score": e.get("score"), "approved": e.get("approved"), "identity": (e.get("identity") or {}).get("similarity"),
                     "seam": e.get("seam_similarity"), "problems": (e.get("verdict") or {}).get("problems"),
                     "clip": e.get("clip"), "handoff": (e.get("handoff") or {}).get("path")}
               for sid, e in state["shots"].items()}
    payload = {"step": "render", "approved": state["approved"], "remaining": state.get("remaining"),
               "rendered": state.get("rendered"), "blocked_on": state.get("blocked_on"), "shots": summary}
    if args.one and state.get("rendered"):
        ok = bool(state["shots"][state["rendered"]].get("approved"))
    else:
        ok = state["approved"]
    return (EXIT_OK if ok else EXIT_REVIEW), payload


def step_rejudge(bible, work, args) -> tuple[int, dict]:
    state = rejudge_chain(bible, work)
    summary = {sid: {"score": e.get("score"), "approved": e.get("approved"), "problems": (e.get("verdict") or {}).get("problems")}
               for sid, e in state["shots"].items()}
    return (EXIT_OK if state["approved"] else EXIT_REVIEW), {"step": "rejudge", "approved": state["approved"], "shots": summary}


def _state(work: Path) -> dict:
    path = work / "chain_state.json"
    if not path.exists():
        raise FileNotFoundError("chain_state.json missing; run `render` first")
    return json.loads(path.read_text(encoding="utf-8"))


def step_compose(bible, work, args) -> tuple[int, dict]:
    report = compose(bible, work, _state(work))
    return EXIT_OK, {"step": "compose", "master": report["master"], "duration": report["duration"],
                     "loudness": report["loudness"], "voice": [{k: v[k] for k in ("shot_id", "start", "end")} for v in report["voice"]]}


def step_verify(bible, work, args) -> tuple[int, dict]:
    report = json.loads((work / "compose_report.json").read_text(encoding="utf-8"))
    res = verify(bible, work, _state(work), report)
    # A failed gate is never overruled at this step: the video is not ready and must go back.
    return (EXIT_OK if res["passed"] else EXIT_REVIEW), {"step": "verify", "shippable": res["passed"], **res}


STEPS = {"lint": step_lint, "keyframes": step_keyframes, "approve": step_approve, "render": step_render,
         "rejudge": step_rejudge,
         "compose": step_compose, "verify": step_verify}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=[*STEPS, "all"])
    parser.add_argument("--bible", required=True, help="Shot Bible JSON")
    parser.add_argument("--work", required=True, help="Run directory for this bible's artifacts")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--shots", nargs="*", default=[], help="Limit keyframes/render to these shot ids (forces re-render)")
    parser.add_argument("--candidates", type=int, default=3)
    parser.add_argument("--provider", default="auto", choices=["auto", "flow2api", "minimax"])
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--one", action="store_true", help="render: only the next shot that needs rendering, then stop for review")
    parser.add_argument("--resolution", default="1080P", choices=["768P", "1080P"])
    parser.add_argument("--shot", help="approve: shot id")
    parser.add_argument("--candidate", help="approve: keyframe candidate file name")
    parser.add_argument("--clip", help="approve: rendered clip file name (e.g. shot_02_a2.mp4)")
    parser.add_argument("--reason", default="", help="approve: why the director overrules the judge")
    args = parser.parse_args()

    try:
        bible = bible_mod.load_bible(args.bible)
    except Exception as exc:  # noqa: BLE001
        _emit({"step": args.step, "error": f"invalid bible: {exc}"}, args.json)
        return EXIT_INVALID
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.bible, work / "shot_bible.json") if Path(args.bible).resolve() != (work / "shot_bible.json").resolve() else None

    steps = ["lint", "keyframes", "render", "compose", "verify"] if args.step == "all" else [args.step]
    results = []
    for name in steps:
        try:
            code, payload = STEPS[name](bible, work, args)
        except FileNotFoundError as exc:
            code, payload = EXIT_INVALID, {"step": name, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            code, payload = EXIT_ERROR, {"step": name, "error": f"{type(exc).__name__}: {exc}"}
        results.append(payload)
        if code != EXIT_OK:
            _emit(payload if len(steps) == 1 else {"steps": results, "stopped_at": name}, args.json)
            return code
    _emit(results[0] if len(steps) == 1 else {"steps": results}, args.json)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
