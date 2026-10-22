#!/usr/bin/env python3
"""Pre-production prompt pack: the exact prompts Stage 4/5 would send, without sending them.

Reads a run's ``scene_plan.json`` (after Stage 3) and writes ``artifacts/prompt_pack.json`` and
``artifacts/prompt_pack.md``: per shot the first-frame image prompt with its reference images
(as Stage 4 ``--keyframe-source synth`` composes them) and the video request (mode, model,
duration, prompt) as Stage 5 would build it. No network, no image or video generation.

Deterministic lints flag prompt defects a reviewer would otherwise have to find by reading.

Usage: python3 tools/prompt_pack.py --run projects/<topic>/<campaign>/runs/v1 [--strict] [--json]
Exit codes: 0 ok, 1 lint errors with --strict, 2 invalid input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.config import BASE_DIR, CHARACTER_PATH
from pipeline.identity_keyframe import (
    IdentityReferenceError,
    _shot_dispatch,
    compose_synthesis_prompt,
    load_reference_overrides,
    plan_synthesis_references,
    resolve_canonical_face_anchor,
    resolve_product_hero_reference,
)
from pipeline.schemas import ScenePlanArtifact
from pipeline.slideshow_risk import score_slideshow_risk
from pipeline.wardrobe import ENVIRONMENT_CATALOG, WARDROBE_CATALOG
from tools.generate_video import normalize_duration
from pipeline.video_engine import DEFAULT_R2V_MODEL, DEFAULT_RESOLUTION, DEFAULT_VIDEO_MODEL, video_prompt_for

#: Quality-tag boilerplate that modern image/video models ignore or that reads as noise.
JUNK_TAG_RE = re.compile(r"\b(8k|4k|uhd|ultra[- ]hd|masterpiece|best quality|highly detailed|trending on artstation)\b", re.I)
STUDIO_LIGHT_RE = re.compile(r"\bstudio (?:portrait |softbox )?lighting\b|\bsoftbox\b", re.I)
#: Neutral/cool daylight (~5000-6500K). Golden hour, sunrise and sunset are genuinely warm (~2500-3500K), so not listed.
DAYLIGHT_RE = re.compile(r"\b(daylight|midday|noon|overcast|bright (?:mid-?morning )?sun(?:light)?|cool window light)\b", re.I)
#: Hailuo text prompt hard limit (characters).
VIDEO_PROMPT_MAX_CHARS = 2000
#: Above this an I2V prompt is re-describing the picture instead of directing motion (research: ~20-60 words).
VIDEO_PROMPT_MAX_WORDS = 80
#: Appearance/set directives belong to the first frame; in an I2V prompt they compete with the image.
IMAGE_DIRECTIVE_RE = re.compile(r"\b(SET:|WEAR:|Subject:|Identity lock|hairstyle|almond eyes|nose bridge)", re.I)


class _Dispatch:
    """The slice of a Stage 4 KeyframeAsset that decides the Stage 5 request mode."""

    def __init__(self, generation_mode: str):
        self.generation_mode = generation_mode
        self.reference_assets = None


class _InputDir:
    """The slice of ProjectWorkspace the reference resolvers read."""

    def __init__(self, input_dir: Path):
        self.input_dir = input_dir


def _rel(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(BASE_DIR))
    except ValueError:
        return str(path)


#: A person in a product-only video prompt invites the model to add one (Product Isolation).
PERSON_RE = re.compile(r"\b(she|her|woman|speaks to camera)\b", re.I)
#: Camera-move words left in a still-frame prompt (motion belongs to the video prompt).
STILL_CAMERA_RE = re.compile(r"\b(tracking shot|dutch-angle|push-in|orbit|pedestal|truck(?:ing)? (?:left|right))\b", re.I)


def lint_shot(
    shot: Any, image_prompt: str, video_prompt: str, set_is_studio: bool, r2v: bool = False
) -> List[Dict[str, str]]:
    """Deterministic defects in one shot's prompts: ``[{"level", "code", "detail"}]``."""
    issues: List[Dict[str, str]] = []

    def add(level: str, code: str, detail: str) -> None:
        issues.append({"level": level, "code": code, "detail": detail})

    for label, text in (("image", image_prompt), ("video", video_prompt)):
        tags = sorted({m.group(0).lower() for m in JUNK_TAG_RE.finditer(text)})
        if tags:
            add("warn", f"{label}_junk_tags", f"quality tags {tags} carry no direction")
    if not set_is_studio and STUDIO_LIGHT_RE.search(shot.prompt_6part):
        add("error", "studio_light_in_location", "studio lighting phrase in a non-studio set")
    kelvin = getattr(shot, "color_temp_kelvin", None)
    if kelvin and kelvin < 4000 and DAYLIGHT_RE.search(shot.prompt_6part + " " + (shot.scene_description or "")):
        add("error", "kelvin_vs_daylight", f"{kelvin}K is tungsten but the shot describes daylight")
    if not getattr(shot, "motion_prompt", None):
        add("error", "video_prompt_is_scene_prompt", "no motion_prompt: Stage 5 would send the still-frame prompt (re-run Stage 3)")
    elif not video_prompt.lstrip().startswith("["):
        add("warn", "video_no_camera_command", "motion prompt does not open with a Hailuo [camera] command")
    role = getattr(getattr(shot, "character_role", None), "value", getattr(shot, "character_role", None))
    if role == "product_only" and PERSON_RE.search(getattr(shot, "motion_prompt", None) or ""):
        add("error", "video_person_in_product_shot", "product-only motion prompt mentions a person or speech")
    still_moves = sorted({m.group(0).lower() for m in STILL_CAMERA_RE.finditer(image_prompt)})
    if still_moves:
        add("warn", "image_camera_move", f"camera-move words {still_moves} in a still-frame prompt (keep them in visual_cue_en out)")
    if r2v and role == "model":
        add("warn", "r2v_without_product_reference",
            "R2V sends only the face: the product in this shot is redrawn from text; set generation_mode i2v if it must match")
    hits = sorted({m.group(1) for m in IMAGE_DIRECTIVE_RE.finditer(video_prompt)}) if not r2v else []
    if hits:
        add("error", "video_redescribes_image", f"appearance/set directives {hits} in the I2V prompt")
    if not r2v and len(video_prompt.split()) > VIDEO_PROMPT_MAX_WORDS:
        add("warn", "video_prompt_wordy", f"{len(video_prompt.split())} words > {VIDEO_PROMPT_MAX_WORDS}: direct motion, not the picture")
    if len(video_prompt) > VIDEO_PROMPT_MAX_CHARS:
        add("error", "video_prompt_too_long", f"{len(video_prompt)} chars > {VIDEO_PROMPT_MAX_CHARS} (Hailuo limit)")
    return issues


def default_look_lints(image_prompt: str) -> List[Dict[str, str]]:
    """The archetype's catalogue SET/WEAR left in place: a studio, blazer or cyberpunk desk the brief never asked for.

    Both QA preprod rounds would have shipped them (general_commercial studio + blazer, tech_gadgets
    cyberpunk desk + techwear hoodie) had the reviewer not asked for set_direction/wear_direction.
    """
    issues = []
    for env in ENVIRONMENT_CATALOG.values():
        if env.prompt_set_directive.strip() in image_prompt:
            issues.append({"level": "warn", "code": "default_set",
                           "detail": f"archetype default set '{env.env_id}': confirm it fits the brief or pass set_direction"})
    for item in WARDROBE_CATALOG.values():
        if item.prompt_wear_directive.strip() in image_prompt:
            issues.append({"level": "warn", "code": "default_wear",
                           "detail": f"archetype default wardrobe '{item.costume_id}': confirm it fits or pass wear_direction"})
    return issues


def trim_lints(planned: float, generated: float) -> List[Dict[str, str]]:
    """A clip cut to well under its generated length shows only the start of its motion prompt."""
    if generated and planned / generated < 0.6:
        return [{"level": "warn", "code": "clip_heavily_trimmed",
                 "detail": f"only the first {planned:g}s of a {generated:g}s clip is used: the key action must start at frame 0"}]
    return []


def build_prompt_pack(run_dir: Path, character_path: Optional[Path] = None) -> Dict[str, Any]:
    artifacts = run_dir / "artifacts"
    plan_path = artifacts / "scene_plan.json"
    if not plan_path.exists():
        raise FileNotFoundError(f"{plan_path} not found: run Stage 3 first")
    plan = ScenePlanArtifact.model_validate(json.loads(plan_path.read_text(encoding="utf-8")))
    char_data = json.loads((character_path or CHARACTER_PATH).read_text(encoding="utf-8"))
    input_dir = run_dir.parent.parent / "input"
    ws = _InputDir(input_dir)

    overrides = load_reference_overrides(artifacts, None, ws)
    default_portrait = BASE_DIR / char_data.get("portrait_image", "assets/characters/kol_main/portrait.png")
    face_anchor = (
        Path(overrides["face_anchor"]) if overrides.get("face_anchor")
        else resolve_canonical_face_anchor(char_data, default_portrait)
    )
    pack_errors: List[str] = []
    try:
        product_hero = (
            Path(overrides["product_hero"]) if overrides.get("product_hero")
            else resolve_product_hero_reference(None, workspace=ws)
        )
    except IdentityReferenceError as exc:
        product_hero = None
        pack_errors.append(str(exc))

    set_is_studio = "studio" in json.dumps(plan.spatial_staging_contract or {}, ensure_ascii=False).lower()
    shots: List[Dict[str, Any]] = []
    for shot in plan.shots:
        mode = _shot_dispatch(shot)
        per_shot = (overrides.get("shots") or {}).get(shot.shot_id, {})
        explicit = [Path(p) for p in per_shot.get("synthesis_references") or []]
        refs, roles = plan_synthesis_references(mode, explicit, face_anchor, product_hero)
        image_prompt = compose_synthesis_prompt(shot, roles)
        # R2V sends no scene frame, so Stage 5 adds the scene sentences to the motion (video_prompt_for).
        video_prompt = video_prompt_for(shot, _Dispatch("r2v" if mode == "r2v" else mode))
        shots.append({
            "shot_id": shot.shot_id,
            "intent": shot.shot_intent,
            "character_role": getattr(shot.character_role, "value", shot.character_role),
            "image": {
                "first_frame_override": _rel(Path(per_shot["first_frame"])) if per_shot.get("first_frame") else None,
                "references": [{"role": r, "path": _rel(p)} for r, p in zip(roles, refs)],
                "prompt": image_prompt,
                "words": len(image_prompt.split()),
            },
            "video": {
                "mode": "R2V" if mode == "r2v" else "I2V",
                "model": DEFAULT_R2V_MODEL if mode == "r2v" else DEFAULT_VIDEO_MODEL,
                "planned_seconds": shot.estimated_duration,
                "generated_seconds": normalize_duration(shot.estimated_duration, DEFAULT_RESOLUTION),
                "prompt": video_prompt,
                "words": len(video_prompt.split()),
                "chars": len(video_prompt),
            },
            "lints": lint_shot(shot, image_prompt, video_prompt, set_is_studio, r2v=mode == "r2v")
            + trim_lints(shot.estimated_duration, normalize_duration(shot.estimated_duration, DEFAULT_RESOLUTION))
            + default_look_lints(image_prompt),
        })
    # The Stage 8 slideshow gate, run here so preproduction QA sees a rejection before any money is spent.
    risk = score_slideshow_risk(json.loads(plan_path.read_text(encoding="utf-8")))
    pack_errors.extend(f"slideshow_risk: {r}" for r in risk.hard_reject_reasons)
    return {
        "campaign_id": plan.campaign_id,
        "run_dir": _rel(run_dir),
        "errors": pack_errors,
        "slideshow_risk": {"verdict": risk.verdict, "average_score": risk.average_score,
                           "reasons": [d.reason for d in risk.dimensions.values() if d.score > 0]},
        "total_planned_seconds": round(sum(s["video"]["planned_seconds"] for s in shots), 2),
        "shots": shots,
    }


def render_markdown(pack: Dict[str, Any]) -> str:
    lines = [f"# Prompt pack · {pack['campaign_id']}", "",
             f"Run: `{pack['run_dir']}` · planned {pack['total_planned_seconds']} s", ""]
    risk = pack.get("slideshow_risk")
    if risk:
        lines += [f"Slideshow risk (Stage 8 gate): **{risk['verdict']}** · {risk['average_score']}"
                  + "".join(f"; {r}" for r in risk["reasons"]), ""]
    for err in pack["errors"]:
        lines.append(f"- **ERROR** {err}")
    for s in pack["shots"]:
        img, vid = s["image"], s["video"]
        lines += [f"## {s['shot_id']} · {s['character_role']} · {s['intent']}", ""]
        for lint in s["lints"]:
            lines.append(f"- **{lint['level'].upper()}** `{lint['code']}`: {lint['detail']}")
        refs = ", ".join(f"{r['role']}=`{r['path']}`" for r in img["references"]) or "none"
        lines += ["", f"**First frame** ({img['words']} words) · refs: {refs}", "", "```", img["prompt"], "```", "",
                  f"**Video** {vid['mode']} · {vid['model']} · planned {vid['planned_seconds']} s → "
                  f"generated {vid['generated_seconds']} s · {vid['words']} words", "", "```", vid["prompt"], "```", ""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, type=Path, help="run directory (projects/<topic>/<campaign>/runs/vN)")
    ap.add_argument("--character", type=Path, help="character.json (default: kol_main)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when any lint error is found")
    ap.add_argument("--json", action="store_true", help="print the pack JSON on stdout")
    args = ap.parse_args(argv)
    run_dir = args.run if args.run.is_absolute() else BASE_DIR / args.run
    try:
        pack = build_prompt_pack(run_dir, args.character)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    artifacts = run_dir / "artifacts"
    (artifacts / "prompt_pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifacts / "prompt_pack.md").write_text(render_markdown(pack), encoding="utf-8")
    errors = [l for s in pack["shots"] for l in s["lints"] if l["level"] == "error"] + pack["errors"]
    if args.json:
        print(json.dumps(pack, ensure_ascii=False, indent=2))
    else:
        print(f"wrote {artifacts / 'prompt_pack.md'} · {len(pack['shots'])} shots · {len(errors)} lint errors")
    return 1 if (args.strict and errors) else 0


if __name__ == "__main__":
    sys.exit(main())
