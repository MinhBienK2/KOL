"""Cinematic Shot Framing, Lens Optics & Storyboard Pre-visualization Engine.

Implements DramaClaw's multi-scale cinematography hierarchy and contact sheet generation:
- Shot Scales: ELS, WS, MWS (Cowboy), MS, MCU, CU, ECU (Macro), OTS, POV.
- Lenses: 24mm Ultra-Wide, 35mm Street, 50mm Natural Prime, 85mm Portrait Bokeh, 100mm Macro.
- Camera Angles: Eye Level, Low Angle Heroic, High Angle POV, Top-Down 90°, Dutch Canted.
- Storyboard Contact Sheet: Generates a 2x3 or 2x4 visual director pre-visualization sheet.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFont


class ShotScale(str, Enum):
    ELS = "extreme_long_shot"      # Environment scale, subject embedded in vast space
    WS = "wide_shot"              # Full body head-to-toe, full garment silhouette & floor
    MWS = "cowboy_shot"           # Mid-thigh up, dynamic posture, hand placement, garment contour
    MS = "medium_shot"            # Waist-up, natural social framing, active product handling
    MCU = "medium_close_up"       # Chest-up, presenter engagement, expressive upper body
    CU = "close_up"               # Shoulder/face, emotional micro-reactions, direct conviction
    ECU = "extreme_macro"         # 100mm hyper-detail: fabric weaves, switches, serum droplets
    OTS = "over_the_shoulder"     # Looking past presenter's shoulder to product on desk
    POV = "point_of_view"         # First-person view of presenter's hands interacting


class CameraLens(str, Enum):
    LENS_24MM = "24mm_wide"       # Expansive depth, dynamic perspective, dramatic room presence
    LENS_35MM = "35mm_street"     # Natural documentary flow, environmental portraiture
    LENS_50MM = "50mm_prime"      # Zero optical distortion, natural human vision standard
    LENS_85MM = "85mm_portrait"   # Shallow depth of field, creamy bokeh, isolated subject
    LENS_100MM = "100mm_macro"    # 1:1 true optical magnification, tack sharp micro-textures


class CameraAngle(str, Enum):
    EYE_LEVEL = "eye_level"       # Neutral, authentic, high-trust direct conversation
    LOW_ANGLE = "low_angle_15deg" # Heroic, empowering, elongates legs & silhouette
    HIGH_ANGLE = "high_angle_35deg"# Looking down on workspace, builds intimacy/focus
    TOP_DOWN = "top_down_90deg"   # Overhead geometric flat lay for unboxing/swatches
    DUTCH = "dutch_canted_20deg"  # 15°-20° off-axis roll, injects urgency/pattern interrupt


class FramingDirective(BaseModel):
    """Complete cinematic optics directive for a storyboard shot."""
    shot_scale: ShotScale
    lens: CameraLens
    angle: CameraAngle
    depth_of_field: str  # "shallow_f1.4", "cinematic_f2.8", "deep_f8.0"
    focal_point: str
    prompt_optics_directive: str

    def to_natural_clause(self) -> str:
        """Model-ready phrasing of the framing (no bracketed enum tokens)."""
        parts = [
            SHOT_SCALE_PHRASES.get(self.shot_scale, self.shot_scale.value.replace("_", " ")),
            LENS_PHRASES.get(self.lens, self.lens.value.replace("_", " ")),
            ANGLE_PHRASES.get(self.angle, self.angle.value.replace("_", " ")),
            DOF_PHRASES.get(self.depth_of_field, self.depth_of_field.replace("_", " ")),
        ]
        return f"{', '.join(parts)}, focus on {self.focal_point}."


def build_framing_directive(
    scale: ShotScale,
    lens: Optional[CameraLens] = None,
    angle: Optional[CameraAngle] = None,
    focal_point: str = "Subject",
) -> FramingDirective:
    """Builds an authoritative cinematic framing directive for diffusion prompts."""
    # Automatic optical pairing if not specified
    if lens is None:
        if scale in (ShotScale.ELS, ShotScale.WS):
            lens = CameraLens.LENS_24MM
        elif scale in (ShotScale.MWS, ShotScale.MS):
            lens = CameraLens.LENS_35MM
        elif scale in (ShotScale.MCU, ShotScale.CU):
            lens = CameraLens.LENS_85MM
        elif scale == ShotScale.ECU:
            lens = CameraLens.LENS_100MM
        else:
            lens = CameraLens.LENS_50MM

    if angle is None:
        if scale == ShotScale.WS:
            angle = CameraAngle.LOW_ANGLE
        elif scale == ShotScale.ECU:
            angle = CameraAngle.HIGH_ANGLE
        else:
            angle = CameraAngle.EYE_LEVEL

    dof_map = {
        CameraLens.LENS_24MM: "deep_f5.6",
        CameraLens.LENS_35MM: "cinematic_f2.8",
        CameraLens.LENS_50MM: "cinematic_f2.0",
        CameraLens.LENS_85MM: "shallow_f1.4",
        CameraLens.LENS_100MM: "ultra_shallow_f2.8_macro",
    }
    dof = dof_map.get(lens, "cinematic_f2.8")

    optics_desc = (
        f"Framing: [{scale.value.upper()}] with [{lens.value}] lens. "
        f"Camera angle: [{angle.value}], aperture: [{dof}], focal plane locked on {focal_point}. "
        f"Tack-sharp commercial cinematographic focus."
    )

    return FramingDirective(
        shot_scale=scale,
        lens=lens,
        angle=angle,
        depth_of_field=dof,
        focal_point=focal_point,
        prompt_optics_directive=optics_desc,
    )


# ==============================================================================
# Natural-language vocabulary for video diffusion prompts
#
# Hailuo / Veo / Kling / Sora guidance favours plain cinematographic phrasing
# ("slow push-in", "85mm lens, shallow depth of field") over snake_case enum
# values. These maps translate pipeline enums into that phrasing.
# ==============================================================================

SHOT_SCALE_PHRASES: Dict[ShotScale, str] = {
    ShotScale.ELS: "extreme wide establishing shot",
    ShotScale.WS: "wide full-body shot",
    ShotScale.MWS: "cowboy shot, mid-thigh up",
    ShotScale.MS: "medium shot, waist up",
    ShotScale.MCU: "medium close-up, chest up",
    ShotScale.CU: "close-up",
    ShotScale.ECU: "extreme macro close-up",
    ShotScale.OTS: "over-the-shoulder shot",
    ShotScale.POV: "first-person point-of-view shot",
}

LENS_PHRASES: Dict[CameraLens, str] = {
    CameraLens.LENS_24MM: "24mm wide-angle lens",
    CameraLens.LENS_35MM: "35mm lens",
    CameraLens.LENS_50MM: "50mm lens",
    CameraLens.LENS_85MM: "85mm portrait lens",
    CameraLens.LENS_100MM: "100mm macro lens",
}

ANGLE_PHRASES: Dict[CameraAngle, str] = {
    CameraAngle.EYE_LEVEL: "eye-level angle",
    CameraAngle.LOW_ANGLE: "slight low angle",
    CameraAngle.HIGH_ANGLE: "high angle looking down",
    CameraAngle.TOP_DOWN: "overhead top-down angle",
    CameraAngle.DUTCH: "canted dutch angle",
}

DOF_PHRASES: Dict[str, str] = {
    "deep_f5.6": "deep focus",
    "cinematic_f2.8": "shallow depth of field",
    "cinematic_f2.0": "shallow depth of field",
    "shallow_f1.4": "very shallow depth of field with creamy bokeh",
    "ultra_shallow_f2.8_macro": "razor-thin macro depth of field",
}

# Keyed by the CameraChoreography enum *values* in pipeline.archetypes.
CAMERA_MOTION_PHRASES: Dict[str, str] = {
    "orbit": "smooth slow orbit around the subject",
    "truck": "steady lateral tracking move",
    "pedestal": "slow vertical pedestal rise",
    "pan": "slow horizontal pan",
    "tilt": "slow upward tilt",
    "zoom_in": "slow push-in toward the subject",
    "drone_flythrough": "gliding drone fly-through",
    "dutch_angle": "canted dutch angle with a slight push-in",
    "macro_push_in": "slow macro push-in",
    "top_down_flat_lay": "overhead top-down framing, gentle drift",
}

# Short noun-ish labels for embedding inside script visual cues ("Camera orbit ...").
CAMERA_MOTION_LABELS: Dict[str, str] = {
    "orbit": "orbit",
    "truck": "tracking",
    "pedestal": "pedestal-up",
    "pan": "pan",
    "tilt": "tilt-up",
    "zoom_in": "push-in",
    "drone_flythrough": "drone fly-through",
    "dutch_angle": "dutch-angle",
    "macro_push_in": "macro push-in",
    "top_down_flat_lay": "top-down",
}

# Keyed by the LightingContract enum *values* in pipeline.archetypes.
LIGHTING_PHRASES: Dict[str, str] = {
    "studio_3point": "soft three-point studio lighting",
    "editorial_fashion": "editorial rim light with soft beauty fill",
    "golden_hour": "warm golden-hour sunlight",
    "cyberpunk_neon": "cyan and magenta neon edge light",
    "nordic_minimalist": "soft diffused window daylight",
    "beauty_high_key": "radiant high-key softbox light",
}


def camera_phrase(choreography: Any, *, short: bool = True) -> str:
    """Human wording for a camera choreography enum (or raw value string)."""
    value = getattr(choreography, "value", choreography)
    if value is None:
        return "push-in" if short else CAMERA_MOTION_PHRASES["zoom_in"]
    table = CAMERA_MOTION_LABELS if short else CAMERA_MOTION_PHRASES
    return table.get(str(value), str(value).replace("_", " "))


_TOKEN_PHRASES: Dict[str, str] = {**LIGHTING_PHRASES, **CAMERA_MOTION_PHRASES}
_TOKEN_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(k) for k in _TOKEN_PHRASES), key=len, reverse=True)) + r")\b"
)

# Filler that burns prompt budget without steering a video model.
_FILLER_RES = [
    re.compile(r",\s*8k\b", re.I),
    re.compile(r"\b8k\s+", re.I),
    re.compile(r"\b8k\b", re.I),
    re.compile(r"\bTack-sharp commercial cinematographic focus\.?\s*", re.I),
]
# Sentences superseded by the dedicated SET:/WEAR: directives when those are present.
_SET_SUPERSEDED_PREFIXES = ("Environment:", "Environment and staging:", "Lighting:", "Lighting key:")
_WEAR_SUPERSEDED_PREFIXES = ("Wardrobe:", "Wardrobe and styling:")


# Shed in this order when a prompt exceeds its word budget (generic coaching text that the
# subject/action/SET/WEAR sentences already imply).
_BUDGET_DROP_PREFIXES = ("Poise:", "Model does visual acting", "Styled with")


def humanize_directive_tokens(text: str) -> str:
    """Replace snake_case camera/lighting enum values with plain cinematographic phrasing."""
    return _TOKEN_RE.sub(lambda m: _TOKEN_PHRASES[m.group(1)], text)


def compact_video_prompt(text: str, max_words: int = 180) -> str:
    """Make a composed prompt model-ready: humanised, de-duplicated and within a word budget.

    Video models follow short, specific prompts better than 250-word concatenations
    (Veo ~100-150 words, Hailuo < 200). This is deterministic and keeps the directive
    order of the input, dropping only filler, duplicated sentences and clauses
    superseded by the SET:/WEAR: directives.
    """
    out = humanize_directive_tokens(text)
    for rx in _FILLER_RES:
        out = rx.sub("", out)
    out = re.sub(r",\s*([.,])", r"\1", out)
    out = re.sub(r"\.{2,}", ".", out)
    # Directive blocks (SET:/WEAR:) are sometimes glued on without a sentence break.
    out = re.sub(r"(?<![.!?])\s+(SET:|WEAR:)", r". \1", out)

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\[])", out) if s.strip()]
    has_set = any(s.startswith("SET:") for s in sentences)
    has_wear = any(s.startswith("WEAR:") for s in sentences)

    kept: List[str] = []
    seen: set[str] = set()
    for sent in sentences:
        if has_set and sent.startswith(_SET_SUPERSEDED_PREFIXES):
            continue
        if has_wear and sent.startswith(_WEAR_SUPERSEDED_PREFIXES):
            continue
        key = re.sub(r"\W+", " ", sent.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(sent)

    # Over budget: shed low-value guidance sentences in priority order. Framing, subject,
    # action, SET:/WEAR: and identity/isolation clauses are never dropped.
    def _wc(items: List[str]) -> int:
        return sum(len(x.split()) for x in items)

    for prefix in _BUDGET_DROP_PREFIXES:
        if _wc(kept) <= max_words:
            break
        kept = [x for x in kept if not x.startswith(prefix)]
    prompt = " ".join(kept)
    return re.sub(r"\s+", " ", prompt).strip()


# ==============================================================================
# Beat-aware shot scale planning
# ==============================================================================

_MACRO_BEAT_KEYWORDS = ("macro", "texture", "fabric", "detail")


def plan_shot_scales(beats: List[Any]) -> List[ShotScale]:
    """Choose a framing scale per beat from its Character Role and narrative function.

    Replaces a blind Wide->Close-Up cycle that put wide shots on speaking presenters
    (a tiny face cannot be lip-synced) and close-ups on every CTA. Rules:
    - Presenter: always chest-up or tighter so the mouth stays readable; CTA backs off
      to a medium shot leaving room for the CTA badge.
    - Model: wide/cowboy silhouettes that show the garment and body motion.
    - Product-Only: macro for texture/detail beats, medium otherwise.
    - Hook: the tightest scroll-stopping scale for its role.
    Adjacent shots never share a scale (edit rhythm).
    """
    pools = {
        "presenter": [ShotScale.MCU, ShotScale.CU, ShotScale.MS],
        "model": [ShotScale.MWS, ShotScale.WS, ShotScale.MS, ShotScale.MCU],
        "product_only": [ShotScale.MS, ShotScale.ECU, ShotScale.CU],
    }
    rotation = {k: 0 for k in pools}
    planned: List[ShotScale] = []
    for beat in beats:
        role = str(getattr(getattr(beat, "character_role", None), "value", getattr(beat, "character_role", "model")))
        if role not in pools:
            role = "model"
        beat_type = str(getattr(beat, "beat_type", "")).lower()
        pool = pools[role]
        if "hook" in beat_type:
            choice = {"presenter": ShotScale.MCU, "model": ShotScale.WS, "product_only": ShotScale.ECU}[role]
        elif beat_type.endswith("cta") or beat_type == "cta":
            choice = ShotScale.MS
        elif role == "product_only" and any(k in beat_type for k in _MACRO_BEAT_KEYWORDS):
            choice = ShotScale.ECU
        else:
            choice = pool[rotation[role] % len(pool)]
            rotation[role] += 1
        if planned and choice == planned[-1]:
            alternatives = [sc for sc in pool if sc != planned[-1]]
            choice = alternatives[0] if alternatives else choice
        planned.append(choice)
    return planned


# ==============================================================================
# DramaClaw Storyboard Contact Sheet (Visual Pre-visualization)
# ==============================================================================

def generate_storyboard_contact_sheet(
    shots: List[Dict[str, Any]],
    output_path: str | Path,
    campaign_title: str = "Commercial Storyboard",
) -> str:
    """Generates a professional 2-column multi-row director's contact sheet.

    Adapted directly from DramaClaw make_contract_sheet logic:
    Renders shot cards with Shot Scale, Lens, Angle, Lighting Kelvin, and Action Cues.
    """
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    cols = 2
    rows = (len(shots) + cols - 1) // cols
    cell_w = 540
    cell_h = 320
    header_h = 70
    gap = 20

    canvas_w = cols * cell_w + (cols + 1) * gap
    canvas_h = header_h + rows * cell_h + (rows + 1) * gap

    # Dark slate studio canvas (#0e1117)
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#0e1117")
    draw = ImageDraw.Draw(canvas)

    # Title header
    draw.rectangle([(0, 0), (canvas_w, header_h)], fill="#161b22")
    draw.text((gap, 16), f"🎬 DIRECTOR STORYBOARD CONTACT SHEET: {campaign_title.upper()}", fill="#58a6ff")
    draw.text((gap, 42), "DramaClaw Multi-Scale Framing & Spatial Continuity System", fill="#8b949e")

    for idx, shot in enumerate(shots):
        col = idx % cols
        row = idx // cols
        x = gap + col * (cell_w + gap)
        y = header_h + gap + row * (cell_h + gap)

        # Card container
        draw.rounded_rectangle(
            [(x, y), (x + cell_w, y + cell_h)],
            radius=10,
            fill="#1c2128",
            outline="#30363d",
            width=2,
        )

        # Card header badge
        shot_id = shot.get("shot_id", f"shot_{idx+1:02d}").upper()
        scale = shot.get("shot_scale", "MS").upper()
        duration = shot.get("estimated_duration", 4.0)
        camera_m = shot.get("camera_motion", "smooth_track")
        role = shot.get("character_role", "model").upper()
        lighting = shot.get("lighting", "studio_3point")
        kelvin = shot.get("color_temp_kelvin", 5500)

        # Draw Badge Bar
        badge_color = "#238636" if "hook" in shot_id.lower() or "cta" in shot_id.lower() else "#1f6feb"
        draw.rounded_rectangle([(x + 12, y + 12), (x + cell_w - 12, y + 42)], radius=5, fill=badge_color)
        draw.text(
            (x + 20, y + 18),
            f"[{shot_id}] • {scale} • {duration:.1f}s • ROLE: {role}",
            fill="#ffffff",
        )

        # Technical Details
        draw.text((x + 18, y + 54), f"🎥 Motion: {camera_m} | Lens: {shot.get('lens', '50mm_prime')}", fill="#e6edf3")
        draw.text((x + 18, y + 78), f"💡 Lighting: {lighting} ({kelvin}K)", fill="#e6edf3")
        draw.text((x + 18, y + 102), f"🎯 Intent: {shot.get('shot_intent', 'Commercial Communication')}", fill="#7ee787")

        # Action & Dialogue Box
        action = shot.get("scene_description", "Active kinetic product demonstration")
        spoken = shot.get("spoken_text", "")
        on_screen = shot.get("on_screen_text", "")

        # Wrap text helper
        def _wrap(text: str, max_chars: int = 55) -> List[str]:
            lines = []
            curr = []
            curr_len = 0
            for w in text.split():
                if curr_len + len(w) + 1 <= max_chars:
                    curr.append(w)
                    curr_len += len(w) + 1
                else:
                    lines.append(" ".join(curr))
                    curr = [w]
                    curr_len = len(w)
            if curr:
                lines.append(" ".join(curr))
            return lines

        draw.text((x + 18, y + 135), "Action / Visual Staging:", fill="#d2a8ff")
        action_lines = _wrap(action, max_chars=54)[:3]
        for l_idx, line in enumerate(action_lines):
            draw.text((x + 24, y + 155 + l_idx * 18), f"• {line}", fill="#8b949e")

        draw.text((x + 18, y + 220), "On-Screen Text & Typography:", fill="#f0883e")
        draw.text((x + 24, y + 240), f"» {on_screen[:50]}", fill="#ffffff")

        if spoken:
            draw.text((x + 18, y + 265), "Spoken Audio (VO/Speech):", fill="#58a6ff")
            draw.text((x + 24, y + 285), f"🗣️ \"{spoken[:48]}...\"", fill="#e6edf3")
        else:
            draw.text((x + 18, y + 270), "Audio: 🎵 Beat-Synced Commercial BGM + SFX", fill="#7ee787")

    canvas.save(out_p, "JPEG", quality=90, optimize=True)
    return str(out_p)
