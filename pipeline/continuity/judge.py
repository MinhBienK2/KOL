"""Visual judges: a vision model describes the picture, the LLM scores it against the Shot Bible.

Describing first and judging second keeps the judge honest: the vision model does not see the
checklist, so it cannot simply agree with it.
"""

from __future__ import annotations

import json
from typing import List

from pipeline import llm
from pipeline.continuity.bible import Shot, ShotBible

DESCRIBE_QUESTION = (
    "Describe this image precisely for a film continuity supervisor: every person (count, face, hair, "
    "clothing, pose, hands, gaze), every vehicle or product (type, colour, visible parts, any lettering "
    "exactly as written, gears or single speed, rack, fenders, fork, brakes, tyres), the setting, light "
    "direction and time of day, camera framing and angle, and any text, watermark, border, blur band or "
    "visual artefact. Do not guess what is not visible."
)

JUDGE_SYSTEM = (
    "You are a strict film continuity supervisor and commercial art director. You receive the shot "
    "contract and an independent description of the rendered image. Score only what the description "
    "supports; a feature that is not mentioned is NOT present, unless the contract says a hidden part is "
    "not a failure. Reply with JSON only."
)


def product_questions(bible: ShotBible) -> str:
    """Direct factual questions for the describer: a free description skips small parts like fenders."""
    features = bible.product.must_show + bible.product.must_not_show
    return ("\n\nThen answer each question with yes/no/unclear plus what you see:\n"
            + "\n".join(f"- Is this visible: {f}?" for f in features))


def checklist(bible: ShotBible, shot: Shot, *, frame_role: str) -> List[str]:
    if frame_role == "keyframe":
        # The keyframe fixes the product for the whole chain, so every canon feature must be seen.
        items = [f"Product visible and matches: {feature}" for feature in bible.product.must_show]
        items += [f"Must NOT show: {feature}" for feature in bible.product.must_not_show]
    else:
        # A chained clip inherits the approved product; a far or turned bicycle hides small parts,
        # so only a contradiction (wrong colour, gears seen, a second bike) fails here.
        items = [f"Same product as the approved first frame ({bible.product.name}); fail only if the "
                 f"description contradicts it (not red, a derailleur or basket seen, a different bicycle). "
                 f"A part hidden by distance or angle is NOT a failure"]
    items += [
        f"Talent wardrobe{'' if frame_role == 'keyframe' else ' (fail only on a contradiction, not on missing detail)'}: {bible.talent.wardrobe}",
        f"Location: {bible.location.canon_text}; light: {bible.location.lighting}",
        "Exactly one person; no extra people in the foreground",
        "No added text, caption, watermark, border, letterbox or blur band (lettering printed on the product or on tyres is expected and allowed)",
    ]
    if frame_role == "keyframe":
        items.append(f"Composition matches the keyframe brief: {shot.keyframe_prompt}")
    else:
        items.append(f"End state reached: {shot.end_state}")
    return items


def judge_description(bible: ShotBible, shot: Shot, description: str, *, frame_role: str) -> dict:
    """``{"score": 0-10, "checks": [...], "problems": [...], "passed": bool}`` from the LLM judge."""
    items = checklist(bible, shot, frame_role=frame_role)
    prompt = (
        f"SHOT CONTRACT ({shot.shot_id}, purpose: {shot.purpose})\nChecklist:\n"
        + "\n".join(f"{i + 1}. {item}" for i, item in enumerate(items))
        + f"\n\nINDEPENDENT DESCRIPTION OF THE {frame_role.upper()}:\n{description}\n\n"
        'Return {"checks":[{"item":<n>,"pass":true|false,"evidence":"..."}],'
        '"score":<0-10 overall fitness for this shot>,"problems":["..."]}. '
        + ("A wrong product (gears instead of single speed, wrong colour, missing rack or lettering) or a "
           "watermark/blur band caps the score at 4." if frame_role == "keyframe" else
           "This is the last frame of a chained clip: the score is mainly whether the end state is reached "
           "with a clean, continuable pose and no artefact. A product contradiction or a blur band caps it at 4; "
           "an unconfirmed small detail does not lower the score.")
    )
    for attempt in range(3):
        res = llm.chat(JUDGE_SYSTEM, prompt, temperature=0.0, max_tokens=3000, timeout=180)
        try:
            verdict = llm.extract_json(res["content"])
            break
        except ValueError:
            if attempt == 2:
                raise
    checks = verdict.get("checks") or []
    verdict["passed_ratio"] = round(sum(bool(c.get("pass")) for c in checks) / len(checks), 3) if checks else 0.0
    verdict["score"] = float(verdict.get("score") or 0)
    verdict["checklist"] = items
    verdict["judge_model"] = res["model"]
    return verdict


def dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
