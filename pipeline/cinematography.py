"""Cinematic Shot Framing, Lens Optics & Storyboard Pre-visualization Engine.

Implements DramaClaw's multi-scale cinematography hierarchy and contact sheet generation:
- Shot Scales: ELS, WS, MWS (Cowboy), MS, MCU, CU, ECU (Macro), OTS, POV.
- Lenses: 24mm Ultra-Wide, 35mm Street, 50mm Natural Prime, 85mm Portrait Bokeh, 100mm Macro.
- Camera Angles: Eye Level, Low Angle Heroic, High Angle POV, Top-Down 90°, Dutch Canted.
- Storyboard Contact Sheet: Generates a 2x3 or 2x4 visual director pre-visualization sheet.
"""

from __future__ import annotations

import json
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
