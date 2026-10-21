"""Shot Bible: the single contract every continuity step reads.

The director agent writes it once (story, product truth, talent, location, look, voice and the
shot list). Later steps only read it, so the idea, the script and the render cannot drift apart:
the keyframe prompt, motion prompts and voice-over all come from this one file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

#: Hailuo camera commands (bracket syntax). A shot uses exactly one.
CAMERA_COMMANDS = (
    "Static shot", "Push in", "Pull out", "Truck left", "Truck right", "Pan left", "Pan right",
    "Tilt up", "Tilt down", "Pedestal up", "Pedestal down", "Zoom in", "Zoom out", "Tracking shot",
    "Shake",
)
#: Motion prompts describe change over time; longer prompts make Hailuo average the instructions.
MAX_MOTION_WORDS = 80
#: Vietnamese TTS reads roughly this many characters per second at speed 1.0 (measured on
#: speech-01 voices); used only for the pre-render estimate, the real stem is measured later.
VI_CHARS_PER_SECOND = 11.5
#: Seconds of every clip the voice-over may occupy (leaves air at the seams).
VO_FILL_RATIO = 0.92
#: Tokens that steer nothing in a video model, or ask it to draw UI it cannot draw.
BANNED_TOKENS = ("8k", "masterpiece", "best quality", "ultra detailed", "call-to-action button", "cta button")
#: Re-describing appearance in an I2V motion prompt fights the first frame.
APPEARANCE_WORDS = ("hairstyle", "almond eyes", "nose bridge", "skin tone", "oval face", "double eyelids")
#: Chained hops before identity/colour drift is expected (community reports 2-3).
#: Product lettering and the face melt after 2-3 chained hops (measured: THONGNHAT -> "SSHMNAT" on
#: hop 3, face similarity 0.88 -> 0.25). Two hops, then re-anchor.
CHAIN_MAX_HOPS = 2
#: A hand-off frame only carries what it shows: a rider far away or seen from behind gives the next
#: clip no face, and the model invents a new person (measured: r3 shot_03 became someone else).
FACELESS_END_STATE_WORDS = ("back to camera", "from behind", "far ", "far down", "mid-distance", "distance",
                            "smaller", "tiny", "out of frame", "exits", "disappears")


class ProductCanon(BaseModel):
    name: str
    hero_image: str
    canon_text: str = Field(..., description="Exact visible description used verbatim in image prompts")
    must_show: List[str] = Field(default_factory=list, description="Visible features a judge must find")
    must_not_show: List[str] = Field(default_factory=list)
    allowed_claims: List[str] = Field(default_factory=list, description="Only claims the VO may state")
    printed_text: List[str] = Field(
        default_factory=list,
        description="Words printed on the product (brand, tyre maker). Any other lettering the describer reads "
                    "on the product means the model melted it, which no director review can overrule",
    )


class TalentCanon(BaseModel):
    character_id: str = "kol_main"
    reference_images: List[str]
    canon_text: str
    wardrobe: str


class LocationCanon(BaseModel):
    canon_text: str
    time_of_day: str
    lighting: str


class VoiceSpec(BaseModel):
    voice: str = "Vietnamese_kindhearted_girl"
    speed: float = 1.0
    music_prompt: Optional[str] = None


class Shot(BaseModel):
    shot_id: str
    purpose: str = Field(..., description="Why the shot exists; what the viewer must feel or learn")
    handoff: Literal["anchor", "chain"] = Field(
        ..., description="anchor: first frame is a generated keyframe; chain: last frame of the previous clip"
    )
    keyframe_prompt: Optional[str] = Field(None, description="Required for anchor shots: composition of frame 1")
    keyframe_from: Optional[str] = Field(
        None, description="Re-anchor: start this anchor shot from an earlier anchor's approved keyframe "
                          "(clean product and face again after chained hops) instead of generating a new one",
    )
    motion_prompt: str = Field(..., description="Only what changes over the clip, plus one [Camera] command")
    start_state: str
    end_state: str = Field(..., description="Clean, continuable pose the next clip starts from")
    vo_text: str = ""
    on_screen_text: str = ""
    duration: int = 6

    @field_validator("duration")
    @classmethod
    def _hailuo_duration(cls, value: int) -> int:
        if value not in (6, 10):
            raise ValueError("Hailuo-2.3 renders 6s or 10s clips")
        return value


class ShotBible(BaseModel):
    campaign_id: str
    title: str
    controlling_idea: str = Field(..., description="One sentence the whole video proves")
    visual_motif: str
    audience_arc: List[str] = Field(..., description="Viewer feeling per shot, in order")
    target_duration: float
    aspect_ratio: str = "9:16"
    product: ProductCanon
    talent: TalentCanon
    location: LocationCanon
    look: str
    voice: VoiceSpec = Field(default_factory=VoiceSpec)
    shots: List[Shot]


def load_bible(path: str | Path) -> ShotBible:
    return ShotBible.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def camera_commands_in(text: str) -> List[str]:
    return [c for c in re.findall(r"\[([^\]]+)\]", text) if c.strip() in CAMERA_COMMANDS]


def estimate_vo_seconds(text: str, speed: float = 1.0) -> float:
    return len(text.strip()) / (VI_CHARS_PER_SECOND * speed) if text.strip() else 0.0


def lint_bible(bible: ShotBible, base_dir: Path) -> dict:
    """Problems that would make the render miss the script. ``errors`` block; ``warnings`` inform."""
    errors: List[str] = []
    warnings: List[str] = []

    for label, rel in [("product.hero_image", bible.product.hero_image),
                       *[(f"talent.reference_images[{i}]", r) for i, r in enumerate(bible.talent.reference_images)]]:
        if not (base_dir / rel).is_file():
            errors.append(f"{label} not found: {rel}")

    if not bible.shots:
        errors.append("no shots")
    elif bible.shots[0].handoff != "anchor":
        errors.append(f"{bible.shots[0].shot_id}: the first shot must be an anchor (nothing to chain from)")
    if len(bible.audience_arc) != len(bible.shots):
        errors.append(f"audience_arc has {len(bible.audience_arc)} entries for {len(bible.shots)} shots")

    hops = 0
    total = 0.0
    for shot in bible.shots:
        sid = shot.shot_id
        total += shot.duration
        if shot.handoff == "anchor" and shot.keyframe_from:
            earlier = {s.shot_id: s for s in bible.shots[:bible.shots.index(shot)]}
            source = earlier.get(shot.keyframe_from)
            if source is None or source.handoff != "anchor" or source.keyframe_from:
                errors.append(f"{sid}: keyframe_from must name an earlier anchor shot with its own keyframe")
        elif shot.handoff == "anchor" and not (shot.keyframe_prompt or "").strip():
            errors.append(f"{sid}: anchor shot needs keyframe_prompt")
        cams = camera_commands_in(shot.motion_prompt)
        if len(cams) != 1:
            errors.append(f"{sid}: motion_prompt needs exactly one [Camera] command from CAMERA_COMMANDS, found {cams}")
        words = len(shot.motion_prompt.split())
        if words > MAX_MOTION_WORDS:
            errors.append(f"{sid}: motion_prompt is {words} words (max {MAX_MOTION_WORDS})")
        low = (shot.motion_prompt + " " + (shot.keyframe_prompt or "")).lower()
        for token in BANNED_TOKENS:
            if token in low:
                errors.append(f"{sid}: banned token {token!r}")
        for word in APPEARANCE_WORDS:
            if word in shot.motion_prompt.lower():
                errors.append(f"{sid}: motion_prompt re-describes appearance ({word!r}); the first frame owns that")
        vo = estimate_vo_seconds(shot.vo_text, bible.voice.speed)
        if vo > shot.duration * VO_FILL_RATIO:
            errors.append(f"{sid}: VO needs ~{vo:.1f}s but the clip is {shot.duration}s; shorten vo_text")
        hops = hops + 1 if shot.handoff == "chain" else 0
        if hops > CHAIN_MAX_HOPS:
            errors.append(f"{sid}: {hops} consecutive chained hops (max {CHAIN_MAX_HOPS}); lettering and face melt by "
                          f"then. Make this shot an anchor, e.g. keyframe_from the first anchor")

    for shot, nxt in zip(bible.shots, bible.shots[1:]):
        end = f" {shot.end_state.lower()} "
        hits = [w for w in FACELESS_END_STATE_WORDS if w in end]
        if nxt.handoff == "chain" and hits:
            errors.append(f"{shot.shot_id}: end_state leaves no readable face ({hits}) but {nxt.shot_id} chains from it; "
                          f"end on a medium framing with her face visible, or make {nxt.shot_id} an anchor")

    if abs(total - bible.target_duration) > 0.15 * bible.target_duration:
        warnings.append(f"shots total {total:.0f}s vs target {bible.target_duration:.0f}s (seam trims shorten it slightly)")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "planned_seconds": total}
