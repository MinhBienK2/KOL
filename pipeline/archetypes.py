"""Product-to-Archetype Directorial Strategy, Character Routing & Cinematography Grammar.

Inspired by OpenMontage (pipeline_defs, shot_prompt_builder, delivery_promise)
and DramaClaw (director_world, scene_spatial_contract, stage_manifest).

This module defines:
1. ProductArchetype matrix (Fashion, Tech, Beauty, Home, General Commercial)
2. CharacterRole triad (Presenter vs Model vs Product-Only) & Dynamic Routing
3. AudioStrategy & Cinematography vocabularies (Choreography, Lighting, Spatial Staging)
4. Dynamic Character Persona & Wardrobe Adaptation (No hardcoded "Minh Anh mug")
5. Pre-configured high-conversion beat formulas per archetype
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

from pipeline.cinematography import LIGHTING_PHRASES, camera_phrase


# ==============================================================================
# Core Directorial Enums
# ==============================================================================

class ProductArchetype(str, Enum):
    """Product-to-Directorial category mapping."""
    FASHION_APPAREL = "fashion_apparel"
    TECH_GADGETS = "tech_gadgets"
    BEAUTY_SKINCARE = "beauty_skincare"
    HOME_LIFESTYLE = "home_lifestyle"
    GENERAL_COMMERCIAL = "general_commercial"


class CharacterRole(str, Enum):
    """The Triad of Visual Character Execution:
    - PRESENTER: On-camera direct-to-camera speaking head requiring lip-sync.
    - MODEL: Visual acting, posing, runway walk, aesthetic movement. Off-camera VO / BGM. No lip-sync.
    - PRODUCT_ONLY: Macro cinematography, tactile unboxing, hands-only interaction. Zero character face.
    """
    PRESENTER = "presenter"
    MODEL = "model"
    PRODUCT_ONLY = "product_only"


class AudioStrategy(str, Enum):
    """Audio delivery and mix strategy."""
    ON_CAMERA_SPEECH = "on_camera_speech"      # Synchronous speech matched to presenter lip movements
    OFF_CAMERA_VO = "off_camera_vo"            # Narration voiceover over model / product shots
    MUSIC_AND_SFX_ONLY = "music_and_sfx_only"  # Beat-synced trending music and foley sounds (ideal for fashion)
    ASMR_HYBRID = "asmr_hybrid"                # Whispered / soft VO layered with hyper-detailed sensory foley


class CameraChoreography(str, Enum):
    """DramaClaw-aligned camera motion grammar."""
    ORBIT = "orbit"                            # 360 dynamic orbit around subject/silhouette
    TRUCK = "truck"                            # Smooth lateral tracking camera motion
    PEDESTAL = "pedestal"                      # Vertical camera movement up/down
    PAN = "pan"                                # Horizontal angular sweep
    TILT = "tilt"                              # Vertical angular sweep
    ZOOM_IN = "zoom_in"                        # Dramatic snap zoom or optical macro push
    DRONE_FLYTHROUGH = "drone_flythrough"      # Sweeping spatial architectural glide
    DUTCH_ANGLE = "dutch_angle"                # Stylized canted horizon for high-energy/tension
    STATIC_MACRO = "macro_push_in"              # Cinematic macro push-in with focal depth shift
    TOP_DOWN_FLAT_LAY = "top_down_flat_lay"    # 90-degree overhead precision for unboxing/swatches


class LightingContract(str, Enum):
    """Lighting and color temperature contracts for spatial and visual continuity."""
    STUDIO_3POINT = "studio_3point"            # Clean key, fill, and rim lights (5500K neutral)
    EDITORIAL_FASHION = "editorial_fashion"    # High-contrast dramatic rim, soft beauty fill, directional beam (5000K)
    GOLDEN_HOUR = "golden_hour"                # Warm low-sun natural light, volumetric dust rays (3200K)
    CYBERPUNK_NEON = "cyberpunk_neon"          # Cyan and magenta edge rim, low-key ambient (mixed K)
    NORDIC_MINIMALIST = "nordic_minimalist"    # Soft diffused daylight, muted warm wood tones (4500K)
    BEAUTY_HIGH_KEY = "beauty_high_key"        # Radiant diffuse softbox, ring light eye reflection (5600K)


# ==============================================================================
# Directorial Archetype Configuration & Beat Templates
# ==============================================================================

class BeatTemplate(BaseModel):
    """Structured template for a single beat within an archetype."""
    beat_id: str
    beat_type: str
    name: str
    target_duration: float
    recommended_role: CharacterRole
    audio_strategy: AudioStrategy
    camera_choreography: CameraChoreography
    lighting_contract: LightingContract
    narrative_purpose: str
    pacing_note: str


class DirectorialArchetypeConfig(BaseModel):
    """Full directorial specifications for a product archetype."""
    archetype: ProductArchetype
    display_name: str
    description: str
    default_character_role: CharacterRole
    allowed_character_roles: List[CharacterRole]
    default_audio_strategy: AudioStrategy
    allowed_audio_strategies: List[AudioStrategy]
    default_lighting: LightingContract
    nominal_color_temp_kelvin: int
    primary_camera_motions: List[CameraChoreography]
    target_shot_duration_range: Tuple[float, float]
    target_speech_wpm: float
    motion_intensity: str  # "high", "medium", "subtle"
    character_guidance: str
    audio_foley_guidance: str
    beat_templates: List[BeatTemplate]


# ------------------------------------------------------------------------------
# 1. Fashion / Apparel Archetype
# ------------------------------------------------------------------------------
FASHION_APPAREL_CONFIG = DirectorialArchetypeConfig(
    archetype=ProductArchetype.FASHION_APPAREL,
    display_name="Fashion Lookbook & Runway Orbit",
    description=(
        "KOL performs as a high-fashion model wearing the outfit. Aesthetic lookbook runway, "
        "slow-mo fabric drape, dynamic 360 orbits, and match cuts. Off-camera voiceover or "
        "pure beat-synced trending music without awkward lip-syncing."
    ),
    default_character_role=CharacterRole.MODEL,
    allowed_character_roles=[CharacterRole.MODEL, CharacterRole.PRODUCT_ONLY],
    default_audio_strategy=AudioStrategy.MUSIC_AND_SFX_ONLY,
    allowed_audio_strategies=[AudioStrategy.MUSIC_AND_SFX_ONLY, AudioStrategy.OFF_CAMERA_VO],
    default_lighting=LightingContract.EDITORIAL_FASHION,
    nominal_color_temp_kelvin=5000,
    primary_camera_motions=[
        CameraChoreography.ORBIT,
        CameraChoreography.PEDESTAL,
        CameraChoreography.TRUCK,
        CameraChoreography.ZOOM_IN,
    ],
    target_shot_duration_range=(2.5, 4.5),
    target_speech_wpm=130.0,
    motion_intensity="high",
    character_guidance=(
        "Model in dynamic physical motion: confident runway strut, elegant pivot, jacket flare, "
        "silhouette profile turn. Do NOT generate mouth movements for speech. Model does visual acting."
    ),
    audio_foley_guidance=(
        "Deep bass house / electronic runway beat. Fabric whoosh SFX, heel clicks on concrete, "
        "zipper pull click. Off-camera trend VO if narration needed."
    ),
    beat_templates=[
        BeatTemplate(
            beat_id="beat_01_hook",
            beat_type="hook",
            name="Runway Step Pattern Interrupt",
            target_duration=3.0,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.MUSIC_AND_SFX_ONLY,
            camera_choreography=CameraChoreography.PEDESTAL,
            lighting_contract=LightingContract.EDITORIAL_FASHION,
            narrative_purpose="Stop the scroll with dramatic low-angle runway step and silhouette reveal.",
            pacing_note="High-energy beat drop exactly at 1.5s.",
        ),
        BeatTemplate(
            beat_id="beat_02_silhouette",
            beat_type="reveal",
            name="Full Outfit Runway Orbit",
            target_duration=4.0,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.MUSIC_AND_SFX_ONLY,
            camera_choreography=CameraChoreography.ORBIT,
            lighting_contract=LightingContract.EDITORIAL_FASHION,
            narrative_purpose="Showcase overall silhouette, tailoring, fit, and proportions in 360 degrees.",
            pacing_note="Smooth orbital motion tracking the model's pivot.",
        ),
        BeatTemplate(
            beat_id="beat_03_fabric_macro",
            beat_type="fabric_macro",
            name="Slow-Mo Fabric Drape & Texture",
            target_duration=4.0,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.MUSIC_AND_SFX_ONLY,
            camera_choreography=CameraChoreography.STATIC_MACRO,
            lighting_contract=LightingContract.EDITORIAL_FASHION,
            narrative_purpose="Highlight premium material texture, stitching quality, seam lines, and tactile drape.",
            pacing_note="120fps slow-motion fabric sway.",
        ),
        BeatTemplate(
            beat_id="beat_04_movement",
            beat_type="movement_flow",
            name="Kinetic Walk & Streetwear Flow",
            target_duration=4.5,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.MUSIC_AND_SFX_ONLY,
            camera_choreography=CameraChoreography.TRUCK,
            lighting_contract=LightingContract.EDITORIAL_FASHION,
            narrative_purpose="Show how the garment flows naturally during real-world urban movement.",
            pacing_note="Lateral tracking tracking speed-matched to model's pace.",
        ),
        BeatTemplate(
            beat_id="beat_05_styling",
            beat_type="styling_versatility",
            name="Day-to-Night Quick Cut Styling",
            target_duration=4.5,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.ZOOM_IN,
            lighting_contract=LightingContract.EDITORIAL_FASHION,
            narrative_purpose="Demonstrate versatility (pairing with accessories, jacket on/off).",
            pacing_note="Snappy punch-in cut.",
        ),
        BeatTemplate(
            beat_id="beat_06_cta",
            beat_type="cta",
            name="Editorial Freeze & Shop Drop",
            target_duration=4.0,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.PEDESTAL,
            lighting_contract=LightingContract.EDITORIAL_FASHION,
            narrative_purpose="Strong aspirational closer inviting the viewer to open the link in bio.",
            pacing_note="Editorial confident hero pose holding eye contact.",
        ),
    ],
)


# ------------------------------------------------------------------------------
# 2. Tech / Gadgets Archetype
# ------------------------------------------------------------------------------
TECH_GADGETS_CONFIG = DirectorialArchetypeConfig(
    archetype=ProductArchetype.TECH_GADGETS,
    display_name="Tactile Teardown & Precision Showcase",
    description=(
        "Immediate problem demonstration, tactile unboxing, macro zoom on ports and buttons, "
        "clean studio lighting, snappy transitions, and hands-on interaction."
    ),
    default_character_role=CharacterRole.PRODUCT_ONLY,
    allowed_character_roles=[CharacterRole.PRODUCT_ONLY, CharacterRole.PRESENTER, CharacterRole.MODEL],
    default_audio_strategy=AudioStrategy.ASMR_HYBRID,
    allowed_audio_strategies=[AudioStrategy.ASMR_HYBRID, AudioStrategy.ON_CAMERA_SPEECH, AudioStrategy.OFF_CAMERA_VO],
    default_lighting=LightingContract.STUDIO_3POINT,
    nominal_color_temp_kelvin=5500,
    primary_camera_motions=[
        CameraChoreography.TOP_DOWN_FLAT_LAY,
        CameraChoreography.ZOOM_IN,
        CameraChoreography.TRUCK,
        CameraChoreography.STATIC_MACRO,
    ],
    target_shot_duration_range=(2.0, 4.0),
    target_speech_wpm=160.0,
    motion_intensity="high",
    character_guidance=(
        "Hands-first tactile demonstration. Presenter used selectively for high-trust hook (0-3s) "
        "and punchy CTA (24-28s). Mid-shots focus on device precision, buttons, and display."
    ),
    audio_foley_guidance=(
        "Crisp tactile mechanical click, magnetic lid snap, protective film peel ASMR, "
        "subtle synthesizer whoosh, clean modern energetic tech bed."
    ),
    beat_templates=[
        BeatTemplate(
            beat_id="beat_01_hook",
            beat_type="hook",
            name="The Daily Frustration Problem",
            target_duration=3.0,
            recommended_role=CharacterRole.PRESENTER,
            audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
            camera_choreography=CameraChoreography.ZOOM_IN,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Agitate common user pain point (clutter, slow speed, poor build, dead battery).",
            pacing_note="Punchy, relatable facial reaction directly to camera.",
        ),
        BeatTemplate(
            beat_id="beat_02_unbox",
            beat_type="unboxing",
            name="Tactile Unboxing & Film Peel",
            target_duration=3.5,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.ASMR_HYBRID,
            camera_choreography=CameraChoreography.TOP_DOWN_FLAT_LAY,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Satisfying unboxing moment, revealing pristine product build in matte packaging.",
            pacing_note="Overhead 90-degree flat lay with audio emphasizing peel SFX.",
        ),
        BeatTemplate(
            beat_id="beat_03_macro_ports",
            beat_type="macro_detail",
            name="Macro Zoom on Ports & Tactile Buttons",
            target_duration=4.5,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.ASMR_HYBRID,
            camera_choreography=CameraChoreography.STATIC_MACRO,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Extreme close-up on CNC chamfered edges, tactile button clicks, and LED indicators.",
            pacing_note="Rack focus from port rim to indicator light.",
        ),
        BeatTemplate(
            beat_id="beat_04_action_demo",
            beat_type="performance_demo",
            name="Real-World Performance Test",
            target_duration=5.0,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.TRUCK,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Live demonstration of key USP solving the exact pain point raised in hook.",
            pacing_note="Snappy side-by-side or quick before/after comparison.",
        ),
        BeatTemplate(
            beat_id="beat_05_specs_portability",
            beat_type="specs_proof",
            name="Everyday Carry & Durability Proof",
            target_duration=4.0,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.PEDESTAL,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Pocket slip, bag stow, or durability drop test showing portability.",
            pacing_note="Quick kinetic motion.",
        ),
        BeatTemplate(
            beat_id="beat_06_cta",
            beat_type="cta",
            name="Presenter Trust Closer & Promo",
            target_duration=4.5,
            recommended_role=CharacterRole.PRESENTER,
            audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
            camera_choreography=CameraChoreography.ZOOM_IN,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Direct recommendation from trusted presenter, holding product, clear link-click CTA.",
            pacing_note="Direct eye contact, confident nod, on-screen link CTA banner (offer only if the brief supplies one).",
        ),
    ],
)


# ------------------------------------------------------------------------------
# 3. Beauty / Skincare Archetype
# ------------------------------------------------------------------------------
BEAUTY_SKINCARE_CONFIG = DirectorialArchetypeConfig(
    archetype=ProductArchetype.BEAUTY_SKINCARE,
    display_name="Sensory Glow & Texture Transformation",
    description=(
        "Texture macro (viscous drops, velvety cream swatches), gentle skin application glow, "
        "side-by-side skin transformation, and intimate ASMR audio with radiant beauty lighting."
    ),
    default_character_role=CharacterRole.MODEL,
    allowed_character_roles=[CharacterRole.MODEL, CharacterRole.PRODUCT_ONLY, CharacterRole.PRESENTER],
    default_audio_strategy=AudioStrategy.ASMR_HYBRID,
    allowed_audio_strategies=[AudioStrategy.ASMR_HYBRID, AudioStrategy.OFF_CAMERA_VO, AudioStrategy.ON_CAMERA_SPEECH],
    default_lighting=LightingContract.BEAUTY_HIGH_KEY,
    nominal_color_temp_kelvin=5600,
    primary_camera_motions=[
        CameraChoreography.STATIC_MACRO,
        CameraChoreography.ORBIT,
        CameraChoreography.TILT,
        CameraChoreography.ZOOM_IN,
    ],
    target_shot_duration_range=(3.0, 5.0),
    target_speech_wpm=125.0,
    motion_intensity="subtle",
    character_guidance=(
        "Bare radiant skin, soft dewy reflection, collarbones visible in silk loungewear robe, "
        "gentle self-care touch, smiling serenely into natural light. No exaggerated speaking head."
    ),
    audio_foley_guidance=(
        "Pipette suction, viscous serum drop landing with soft splash, cream smoothing across cheek, "
        "delicate glass bottle clink, warm ambient dream-pop chord."
    ),
    beat_templates=[
        BeatTemplate(
            beat_id="beat_01_hook",
            beat_type="hook",
            name="Sensory Macro Dropper Release",
            target_duration=3.0,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.ASMR_HYBRID,
            camera_choreography=CameraChoreography.STATIC_MACRO,
            lighting_contract=LightingContract.BEAUTY_HIGH_KEY,
            narrative_purpose="Hypnotic ultra-slow motion serum drop releasing from glass pipette.",
            pacing_note="Mesmerizing macro visual pattern interrupt.",
        ),
        BeatTemplate(
            beat_id="beat_02_skin_pain",
            beat_type="skin_agitation",
            name="Dryness & Barrier Fatigue Agitation",
            target_duration=3.5,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.ZOOM_IN,
            lighting_contract=LightingContract.BEAUTY_HIGH_KEY,
            narrative_purpose="Relatable focus on tired, dehydrated skin barrier under harsh air conditioning.",
            pacing_note="Gentle concern expressed through model's touch on dry cheek.",
        ),
        BeatTemplate(
            beat_id="beat_03_texture_swatch",
            beat_type="texture_macro",
            name="Velvety Swatch & Skin Melting ASMR",
            target_duration=4.5,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.ASMR_HYBRID,
            camera_choreography=CameraChoreography.STATIC_MACRO,
            lighting_contract=LightingContract.BEAUTY_HIGH_KEY,
            narrative_purpose="Show cream/gel texture gliding effortlessly across fingertip or glass tile.",
            pacing_note="Rich textural shimmer and glistening micro-beads.",
        ),
        BeatTemplate(
            beat_id="beat_04_application",
            beat_type="application_method",
            name="Facial Application & Instant Glow",
            target_duration=5.0,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.ASMR_HYBRID,
            camera_choreography=CameraChoreography.TILT,
            lighting_contract=LightingContract.BEAUTY_HIGH_KEY,
            narrative_purpose="Model gently pressing serum into cheekbones, instantly revealing luminous dewy bounce.",
            pacing_note="Soft upward camera tilt following the application gesture.",
        ),
        BeatTemplate(
            beat_id="beat_05_transformation",
            beat_type="transformation_proof",
            name="Flawless Glass Skin Daylight Bounce",
            target_duration=4.5,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.ORBIT,
            lighting_contract=LightingContract.BEAUTY_HIGH_KEY,
            narrative_purpose="Radiant daylight check: model turning head gracefully, light catching healthy cheekbone.",
            pacing_note="Slow circular orbit with golden ring reflection in eyes.",
        ),
        BeatTemplate(
            beat_id="beat_06_cta",
            beat_type="cta",
            name="Exclusive Bundle & Gift Offer",
            target_duration=4.0,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.ZOOM_IN,
            lighting_contract=LightingContract.BEAUTY_HIGH_KEY,
            narrative_purpose="Bottle placed beside fresh botanical ingredients, limited gift-with-purchase callout.",
            pacing_note="Gentle smile, clean beauty typography, tap link in bio.",
        ),
    ],
)


# ------------------------------------------------------------------------------
# 4. Home / Lifestyle Archetype
# ------------------------------------------------------------------------------
HOME_LIFESTYLE_CONFIG = DirectorialArchetypeConfig(
    archetype=ProductArchetype.HOME_LIFESTYLE,
    display_name="Cozy Sanctuary & Satisfying Functionality",
    description=(
        "Atmospheric cozy interior lighting, satisfying functional demonstration, "
        "seamless integration into daily morning/evening rituals, and warm acoustic ambience."
    ),
    default_character_role=CharacterRole.MODEL,
    allowed_character_roles=[CharacterRole.MODEL, CharacterRole.PRODUCT_ONLY, CharacterRole.PRESENTER],
    default_audio_strategy=AudioStrategy.OFF_CAMERA_VO,
    allowed_audio_strategies=[AudioStrategy.OFF_CAMERA_VO, AudioStrategy.ASMR_HYBRID, AudioStrategy.ON_CAMERA_SPEECH],
    default_lighting=LightingContract.GOLDEN_HOUR,
    nominal_color_temp_kelvin=3200,
    primary_camera_motions=[
        CameraChoreography.DRONE_FLYTHROUGH,
        CameraChoreography.TRUCK,
        CameraChoreography.PEDESTAL,
        CameraChoreography.ZOOM_IN,
    ],
    target_shot_duration_range=(3.0, 5.5),
    target_speech_wpm=135.0,
    motion_intensity="medium",
    character_guidance=(
        "Relaxed resident wearing comfortable oversized knit sweater or linen homewear. "
        "Natural, candid enjoyment of living space. Candid morning/evening routine."
    ),
    audio_foley_guidance=(
        "Gentle kettle steam hiss, ceramic mug clinking on wooden countertop, rain tapping on window, "
        "warm acoustic guitar arpeggio, soothing domestic tranquility."
    ),
    beat_templates=[
        BeatTemplate(
            beat_id="beat_01_hook",
            beat_type="hook",
            name="Cozy Morning Disruption",
            target_duration=3.5,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.TRUCK,
            lighting_contract=LightingContract.GOLDEN_HOUR,
            narrative_purpose="Establish warm morning sanctuary disrupted by mundane clutter or inefficient appliance.",
            pacing_note="Steadicam glide across sunlit living room or kitchen counter.",
        ),
        BeatTemplate(
            beat_id="beat_02_decor_reveal",
            beat_type="reveal",
            name="Minimalist Interior Harmony",
            target_duration=4.0,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.PEDESTAL,
            lighting_contract=LightingContract.GOLDEN_HOUR,
            narrative_purpose="Hero product sitting organically on Scandinavian oak table, elevating room aesthetics.",
            pacing_note="Smooth pedestal down revealing sleek silhouette in natural sunlight.",
        ),
        BeatTemplate(
            beat_id="beat_03_function_demo",
            beat_type="functional_demo",
            name="One-Touch Satisfying Operation",
            target_duration=5.0,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.ASMR_HYBRID,
            camera_choreography=CameraChoreography.ZOOM_IN,
            lighting_contract=LightingContract.GOLDEN_HOUR,
            narrative_purpose="Satisfying mechanical or smart action (whisper-quiet brew, airtight lock, smooth glide).",
            pacing_note="Crisp audio emphasis on the mechanical click/pour.",
        ),
        BeatTemplate(
            beat_id="beat_04_lifestyle_enjoy",
            beat_type="lifestyle_context",
            name="Serene Living Routine Integration",
            target_duration=5.0,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.DRONE_FLYTHROUGH,
            lighting_contract=LightingContract.GOLDEN_HOUR,
            narrative_purpose="Character enjoying reading, working, or unwinding on sofa with product nearby.",
            pacing_note="Slow atmospheric push-in conveying peace of mind.",
        ),
        BeatTemplate(
            beat_id="beat_05_clean_store",
            beat_type="convenience_proof",
            name="Effortless Clean & Compact Storage",
            target_duration=4.0,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.TRUCK,
            lighting_contract=LightingContract.GOLDEN_HOUR,
            narrative_purpose="One-wipe clean surface and compact space-saving footprint.",
            pacing_note="Quick, satisfying motion demonstrating zero maintenance hassle.",
        ),
        BeatTemplate(
            beat_id="beat_06_cta",
            beat_type="cta",
            name="Home Upgrade & Special Bundle",
            target_duration=4.5,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.ZOOM_IN,
            lighting_contract=LightingContract.GOLDEN_HOUR,
            narrative_purpose="Warm smile holding product, 'Make your sanctuary complete today' CTA.",
            pacing_note="Heartwarming natural glance, on-screen link to shop the home collection.",
        ),
    ],
)


# ------------------------------------------------------------------------------
# 5. General Commercial / Problem-Solution Archetype
# ------------------------------------------------------------------------------
GENERAL_COMMERCIAL_CONFIG = DirectorialArchetypeConfig(
    archetype=ProductArchetype.GENERAL_COMMERCIAL,
    display_name="Direct Problem-Solution Agitator",
    description=(
        "High-energy direct response commercial. Relatable pain point, shocking pattern interrupt, "
        "clear step-by-step benefit demonstration, social proof, and urgent limited-time CTA."
    ),
    default_character_role=CharacterRole.PRESENTER,
    allowed_character_roles=[CharacterRole.PRESENTER, CharacterRole.PRODUCT_ONLY, CharacterRole.MODEL],
    default_audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
    allowed_audio_strategies=[AudioStrategy.ON_CAMERA_SPEECH, AudioStrategy.OFF_CAMERA_VO, AudioStrategy.ASMR_HYBRID],
    default_lighting=LightingContract.STUDIO_3POINT,
    nominal_color_temp_kelvin=5500,
    primary_camera_motions=[
        CameraChoreography.ZOOM_IN,
        CameraChoreography.DUTCH_ANGLE,
        CameraChoreography.TRUCK,
        CameraChoreography.STATIC_MACRO,
    ],
    target_shot_duration_range=(2.5, 5.0),
    target_speech_wpm=155.0,
    motion_intensity="high",
    character_guidance=(
        "Expressive, highly credible presenter. Direct eye contact, relatable conversational gestures, "
        "sharp contrast between initial annoyance and genuine relief upon using solution."
    ),
    audio_foley_guidance=(
        "Punchy bass hits on cuts, alert sound on pain point, chime sound on solution reveal, "
        "upbeat driving commercial background track with automatic audio ducking."
    ),
    beat_templates=[
        BeatTemplate(
            beat_id="beat_01_hook",
            beat_type="hook",
            name="Pattern Interrupt Shock Hook",
            target_duration=3.5,
            recommended_role=CharacterRole.PRESENTER,
            audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
            camera_choreography=CameraChoreography.DUTCH_ANGLE,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Stop the scroll with counter-intuitive claim or dramatic everyday failure.",
            pacing_note="High-energy start, rapid punch-in to presenter.",
        ),
        BeatTemplate(
            beat_id="beat_02_pain",
            beat_type="pain_agitation",
            name="Visceral Pain Agitation",
            target_duration=4.5,
            recommended_role=CharacterRole.MODEL,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.ZOOM_IN,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Show tangible negative consequences (wasted money, lost time, mess).",
            pacing_note="Frustrated reaction, close-up on failure moment.",
        ),
        BeatTemplate(
            beat_id="beat_03_solution_reveal",
            beat_type="solution_reveal",
            name="Hero Solution Unveiling",
            target_duration=4.5,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.PEDESTAL,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Dramatic hero lighting reveal showing the product as the obvious smart answer.",
            pacing_note="Bright chime SFX, lighting sweep across product body.",
        ),
        BeatTemplate(
            beat_id="beat_04_feature_demo",
            beat_type="feature_demo",
            name="Core Mechanism in Action",
            target_duration=5.5,
            recommended_role=CharacterRole.PRODUCT_ONLY,
            audio_strategy=AudioStrategy.OFF_CAMERA_VO,
            camera_choreography=CameraChoreography.STATIC_MACRO,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Demonstrate why the technology works better than traditional alternatives.",
            pacing_note="Clear visual proof of claim.",
        ),
        BeatTemplate(
            beat_id="beat_05_social_proof",
            beat_type="social_proof",
            name="Delighted User Transformation",
            target_duration=4.5,
            recommended_role=CharacterRole.PRESENTER,
            audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
            camera_choreography=CameraChoreography.TRUCK,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Genuine satisfaction, holding product comfortably, validating user joy.",
            pacing_note="Bright, warm smile, relaxed posture.",
        ),
        BeatTemplate(
            beat_id="beat_06_cta",
            beat_type="cta",
            name="Direct Link Call-To-Action Closer",
            target_duration=4.5,
            recommended_role=CharacterRole.PRESENTER,
            audio_strategy=AudioStrategy.ON_CAMERA_SPEECH,
            camera_choreography=CameraChoreography.ZOOM_IN,
            lighting_contract=LightingContract.STUDIO_3POINT,
            narrative_purpose="Strong direct call to action, bio link tap (any offer must come from the brief).",
            pacing_note="Direct eye contact, urgent CTA graphic tag overlay.",
        ),
    ],
)


ARCHETYPE_REGISTRY: Dict[ProductArchetype, DirectorialArchetypeConfig] = {
    ProductArchetype.FASHION_APPAREL: FASHION_APPAREL_CONFIG,
    ProductArchetype.TECH_GADGETS: TECH_GADGETS_CONFIG,
    ProductArchetype.BEAUTY_SKINCARE: BEAUTY_SKINCARE_CONFIG,
    ProductArchetype.HOME_LIFESTYLE: HOME_LIFESTYLE_CONFIG,
    ProductArchetype.GENERAL_COMMERCIAL: GENERAL_COMMERCIAL_CONFIG,
}


def get_archetype_config(archetype: ProductArchetype | str) -> DirectorialArchetypeConfig:
    """Retrieve the full directorial config for a given product archetype."""
    if isinstance(archetype, str):
        try:
            archetype = ProductArchetype(archetype)
        except ValueError:
            archetype = ProductArchetype.GENERAL_COMMERCIAL
    return ARCHETYPE_REGISTRY.get(archetype, GENERAL_COMMERCIAL_CONFIG)


# ==============================================================================
# Dynamic Character Persona & Wardrobe Engine
# ==============================================================================

class CharacterPersona(BaseModel):
    """Dynamic character persona representation."""
    persona_id: str
    name: str
    character_tag: str
    gender: str
    ethnicity: str
    age_group: str
    body_type: str
    base_face_prompt: str
    character_file: str
    supported_archetypes: List[ProductArchetype] = Field(default_factory=list)


# Persona catalog
PERSONA_CATALOG: Dict[str, CharacterPersona] = {
    "kol_main": CharacterPersona(
        persona_id="kol_main",
        name="Mai Ly",
        character_tag="[KOL_MAIN]",
        gender="female",
        ethnicity="Vietnamese",
        age_group="young adult 20-25",
        body_type="Slim, well-proportioned, 166cm, natural posture",
        base_face_prompt=(
            "Vietnamese young woman, early 20s, refined oval face shape, natural chin-length black "
            "bob hairstyle, soft double eyelids, gentle dark brown almond eyes, straight elegant nose bridge, "
            "natural soft lips, smooth warm fair skin, calm intelligent and approachable expression, 8k"
        ),
        character_file="assets/characters/kol_main/character.json",
        supported_archetypes=[
            ProductArchetype.TECH_GADGETS,
            ProductArchetype.HOME_LIFESTYLE,
            ProductArchetype.GENERAL_COMMERCIAL,
            ProductArchetype.BEAUTY_SKINCARE,
            ProductArchetype.FASHION_APPAREL,
        ],
    ),
    "kol_minhanh": CharacterPersona(
        persona_id="kol_minhanh",
        name="Minh Anh",
        character_tag="[KOL_MINHANH]",
        gender="female",
        ethnicity="Vietnamese",
        age_group="young adult 22-26",
        body_type="Slim, elegant posture, 165cm",
        base_face_prompt=(
            "Vietnamese young woman, early 20s, refined oval face shape, natural straight black "
            "collarbone-length bob hair, neat center-part, soft double eyelids, gentle dark brown "
            "almond eyes, straight elegant nose bridge, natural soft lips, smooth warm fair skin"
        ),
        character_file="assets/characters/kol_minhanh/character.json",
        supported_archetypes=[
            ProductArchetype.TECH_GADGETS,
            ProductArchetype.HOME_LIFESTYLE,
            ProductArchetype.GENERAL_COMMERCIAL,
            ProductArchetype.BEAUTY_SKINCARE,
            ProductArchetype.FASHION_APPAREL,
        ],
    ),
    "model_fashion": CharacterPersona(
        persona_id="model_fashion",
        name="Linh Dan",
        character_tag="[MODEL_LD]",
        gender="female",
        ethnicity="Vietnamese",
        age_group="young adult 20-24",
        body_type="High-fashion runway model, tall 174cm, slender proportions, confident posture",
        base_face_prompt=(
            "High-fashion Vietnamese female model, high cheekbones, sharp jawline, sleek glossy black "
            "hair in wet-look ponytail, striking almond eyes with subtle cat-eye eyeliner, poised editorial expression"
        ),
        character_file="assets/characters/kol_main/character.json",  # fallback reference
        supported_archetypes=[ProductArchetype.FASHION_APPAREL],
    ),
    "creator_beauty": CharacterPersona(
        persona_id="creator_beauty",
        name="Mai Chi",
        character_tag="[BEAUTY_MC]",
        gender="female",
        ethnicity="Vietnamese",
        age_group="young adult 22-25",
        body_type="Delicate, gentle posture, bare smooth shoulders",
        base_face_prompt=(
            "Vietnamese beauty creator, ultra-smooth glass skin with natural dewy glow, soft rosy cheeks, "
            "wispy bangs framing gentle face, bright clear eyes, serene and inviting skincare aesthetic"
        ),
        character_file="assets/characters/kol_main/character.json",
        supported_archetypes=[ProductArchetype.BEAUTY_SKINCARE],
    ),
}


class ContextualWardrobeRule(BaseModel):
    """Rules for dynamically adapting character styling, wardrobe, and setting per archetype."""
    archetype: ProductArchetype
    wardrobe_directive: str
    environment_directive: str
    expression_mapping: Dict[str, str]  # maps emotion keyword to reference expression asset


WARDROBE_RULES: Dict[ProductArchetype, ContextualWardrobeRule] = {
    ProductArchetype.FASHION_APPAREL: ContextualWardrobeRule(
        archetype=ProductArchetype.FASHION_APPAREL,
        wardrobe_directive=(
            "Wearing the featured fashion apparel item directly. Styled with chic runway minimalist "
            "jewelry, sleek footwear, editorial hair and makeup tailored to the garment aesthetics."
        ),
        environment_directive="Architectural runway corridor, minimal concrete urban plaza, dramatic studio cyclorama with directional spotlights.",
        expression_mapping={
            "hook": "06_profile_90deg.jpg",
            "reveal": "05_three_quarter.jpg",
            "movement": "01_neutral.jpg",
            "cta": "02_smiling.jpg",
            "neutral": "01_neutral.jpg",
        },
    ),
    ProductArchetype.TECH_GADGETS: ContextualWardrobeRule(
        archetype=ProductArchetype.TECH_GADGETS,
        wardrobe_directive=(
            "Modern creative tech professional attire: fitted charcoal merino wool crewneck or "
            "minimalist dark navy tailored overshirt, clean smart watch, tidy styling."
        ),
        environment_directive="Modern minimalist desk studio, walnut wood accents, soft matte gray acoustic felt walls, subtle cyan LED rim lighting.",
        expression_mapping={
            "hook": "04_looking_down.jpg",
            "pain": "04_looking_down.jpg",
            "unbox": "05_three_quarter.jpg",
            "solution": "03_surprised.jpg",
            "cta": "02_smiling.jpg",
            "neutral": "01_neutral.jpg",
        },
    ),
    ProductArchetype.BEAUTY_SKINCARE: ContextualWardrobeRule(
        archetype=ProductArchetype.BEAUTY_SKINCARE,
        wardrobe_directive=(
            "Soft ivory silk loungewear robe gently draped over bare collarbones, hair neatly secured "
            "with minimalist silk headband, clean bare skin with zero heavy makeup, pure organic elegance."
        ),
        environment_directive="Sun-drenched luxury marble bathroom vanity, soft pastel linen accents, fresh eucalyptus branch in fluted glass vase.",
        expression_mapping={
            "hook": "05_three_quarter.jpg",
            "pain": "04_looking_down.jpg",
            "glow": "02_smiling.jpg",
            "transformation": "02_smiling.jpg",
            "cta": "02_smiling.jpg",
            "neutral": "01_neutral.jpg",
        },
    ),
    ProductArchetype.HOME_LIFESTYLE: ContextualWardrobeRule(
        archetype=ProductArchetype.HOME_LIFESTYLE,
        wardrobe_directive=(
            "Cozy oversized ribbed cream knit sweater, relaxed linen wide-leg pants, barefoot, "
            "hair in a loose effortless low bun, cozy effortless lifestyle aesthetic."
        ),
        environment_directive="Warm Scandinavian-Japandi living room, light oak furniture, cream bouclé sofa, sunbeams filtering through linen curtains.",
        expression_mapping={
            "hook": "04_looking_down.jpg",
            "reveal": "05_three_quarter.jpg",
            "enjoy": "02_smiling.jpg",
            "cta": "02_smiling.jpg",
            "neutral": "01_neutral.jpg",
        },
    ),
    ProductArchetype.GENERAL_COMMERCIAL: ContextualWardrobeRule(
        archetype=ProductArchetype.GENERAL_COMMERCIAL,
        wardrobe_directive=(
            "Crisp tailored white button-down collared dress shirt, dark navy tailored slim trousers, "
            "approachable smart-casual presenter look."
        ),
        environment_directive="Clean contemporary studio setting with balanced warm and cool lighting accents.",
        expression_mapping={
            "hook": "03_surprised.jpg",
            "pain": "04_looking_down.jpg",
            "solution": "03_surprised.jpg",
            "cta": "02_smiling.jpg",
            "neutral": "01_neutral.jpg",
        },
    ),
}


class DynamicPromptBuilder:
    """Dynamically builds video diffusion prompts, avoiding hardcoded 'Minh Anh mug' artifacts."""

    @staticmethod
    def resolve_persona(
        archetype: ProductArchetype,
        requested_persona_id: Optional[Union[str, CharacterPersona]] = None,
    ) -> CharacterPersona:
        """Pick the best matching persona for the product archetype."""
        if isinstance(requested_persona_id, CharacterPersona):
            return requested_persona_id
        if requested_persona_id and requested_persona_id in PERSONA_CATALOG:
            return PERSONA_CATALOG[requested_persona_id]
        # Canonical repository KOL is Minh Anh ([KOL_MA]) across all advertising campaigns
        return PERSONA_CATALOG["kol_main"]

    @staticmethod
    def persona_from_character_file(
        character_path: Union[Path, str],
        archetype: Optional[ProductArchetype] = None,
    ) -> CharacterPersona:
        """Build a persona from a character.json so a chosen KOL drives the prompts.

        persona_id is the character directory name so expression reference paths
        (assets/characters/<persona_id>/expressions) keep resolving.
        """
        import json

        path = Path(character_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        persona_id = path.parent.name or "kol_main"
        known = PERSONA_CATALOG.get(persona_id)
        return CharacterPersona(
            persona_id=persona_id,
            name=data.get("name") or (known.name if known else "KOL"),
            character_tag=data.get("character_tag") or (known.character_tag if known else "[KOL]"),
            gender=data.get("gender") or "female",
            ethnicity=data.get("ethnicity") or "Vietnamese",
            age_group=data.get("age_group") or "young adult",
            body_type=data.get("body_type") or "",
            base_face_prompt=data.get("face_prompt") or data.get("description") or (known.base_face_prompt if known else ""),
            character_file=str(path),
            supported_archetypes=list(ProductArchetype),
        )

    @staticmethod
    def build_subject_and_action_prompt(
        character_role: CharacterRole,
        archetype: ProductArchetype,
        product_name: str,
        scene_action: str,
        persona: Optional[CharacterPersona] = None,
        lighting: Optional[LightingContract] = None,
        camera: Optional[CameraChoreography] = None,
    ) -> str:
        """Compose a provider-optimized prompt based on CharacterRole, Archetype, and Context.

        CRITICAL DIRECTIVE:
        - If role is PRODUCT_ONLY: Suppress character face/body completely. Focus 100% on product physics.
        - If role is MODEL: Prompt visual acting, posture, and clothing without speech cues.
        - If role is PRESENTER: Prompt direct-to-camera eye contact and speaking delivery.
        """
        config = get_archetype_config(archetype)
        rule = WARDROBE_RULES.get(archetype, WARDROBE_RULES[ProductArchetype.GENERAL_COMMERCIAL])
        p = persona or DynamicPromptBuilder.resolve_persona(archetype)
        active_lighting = lighting or config.default_lighting
        active_camera = camera or CameraChoreography.ZOOM_IN

        if character_role == CharacterRole.PRODUCT_ONLY:
            # Pure product cinematography - no character facial identity
            parts = [
                f"Commercial macro product cinematography of {product_name}",
                f"Action and interaction: {scene_action}",
                f"Camera movement: {camera_phrase(active_camera, short=False)} with shallow depth of field, sharp focal plane on product geometry and surface materials",
                f"Environment and staging: {rule.environment_directive}",
                f"Lighting key: {LIGHTING_PHRASES.get(active_lighting.value, active_lighting.value)} at {config.nominal_color_temp_kelvin}K, realistic reflections and highlights",
                "Cinematic 8k commercial quality, photorealistic, zero character face, hyper-detailed textures",
            ]
            return ". ".join(parts)

        if character_role == CharacterRole.MODEL:
            # Visual acting model - NO mouth speaking cues
            parts = [
                f"Commercial fashion and lifestyle video featuring {p.character_tag} {p.name}",
                f"Subject: {p.base_face_prompt}",
                f"Wardrobe and styling: {rule.wardrobe_directive}",
                f"Visual acting action: {scene_action}",
                f"Poise: {config.character_guidance}",
                f"Camera movement: {camera_phrase(active_camera, short=False)}",
                f"Environment: {rule.environment_directive}",
                f"Lighting: {LIGHTING_PHRASES.get(active_lighting.value, active_lighting.value)} with elegant skin tones, 8k cinematic master shot",
            ]
            return ". ".join(parts)

        # PRESENTER: Direct-to-camera on-screen speaking head
        parts = [
            f"Commercial presenter video featuring {p.character_tag} {p.name}",
            f"Subject: {p.base_face_prompt}",
            f"Wardrobe: {rule.wardrobe_directive}",
            f"Delivery action: Direct eye contact to camera, {scene_action}, speaking with clear engaged expression",
            f"Camera framing: Medium close-up with a {camera_phrase(active_camera, short=False)}",
            f"Environment: {rule.environment_directive}",
            f"Lighting: {LIGHTING_PHRASES.get(active_lighting.value, active_lighting.value)}, studio portrait quality, crystal clear 8k resolution",
        ]
        return ". ".join(parts)

    @staticmethod
    def get_reference_expression_path(
        persona: CharacterPersona,
        archetype: ProductArchetype,
        emotion_intent: str,
    ) -> str:
        """Resolve the relative path to the best reference expression image."""
        rule = WARDROBE_RULES.get(archetype, WARDROBE_RULES[ProductArchetype.GENERAL_COMMERCIAL])
        filename = rule.expression_mapping.get(emotion_intent, "01_neutral.jpg")
        base_dir = Path("assets/characters") / persona.persona_id / "expressions"
        return str(base_dir / filename)


# ==============================================================================
# Dynamic Character Routing Rules
# ==============================================================================

def route_character_for_beat(
    archetype: ProductArchetype,
    beat_index: int,
    total_beats: int,
    beat_type: str,
) -> Tuple[CharacterRole, AudioStrategy]:
    """Algorithmic character and audio strategy routing for viral TVC beats.

    Implements the core decision tree:
    1. Fashion: Model (runway/poses) & Product-Only (fabric macro) only. OFF-CAMERA audio.
    2. Tech: Fast problem hook -> Tactile unbox (Product-Only) -> Port Macro (Product-Only)
       -> Performance test (Model) -> Urgency CTA (Presenter).
    3. Beauty: Serum macro drop (Product-Only) -> Skin concern (Model) -> Texture ASMR (Product-Only)
       -> Application glow (Model) -> Daylight proof (Model) -> CTA (Model).
    4. Home: Sanctuary hook (Model) -> Aesthetic decor (Product-Only) -> Demo (Product-Only)
       -> Routine comfort (Model) -> CTA (Model/Presenter).
    5. General: Balanced Presenter / Product-Only / Model rhythm.
    """
    config = get_archetype_config(archetype)
    templates = config.beat_templates

    if beat_index < len(templates):
        tpl = templates[beat_index]
        return tpl.recommended_role, tpl.audio_strategy

    # Fallback heuristic for arbitrary beat structures
    is_first = beat_index == 0
    is_last = beat_index == total_beats - 1

    if archetype == ProductArchetype.FASHION_APPAREL:
        if "fabric" in beat_type.lower() or "macro" in beat_type.lower() or "detail" in beat_type.lower():
            return CharacterRole.PRODUCT_ONLY, AudioStrategy.MUSIC_AND_SFX_ONLY
        return CharacterRole.MODEL, AudioStrategy.MUSIC_AND_SFX_ONLY

    if archetype == ProductArchetype.BEAUTY_SKINCARE:
        if "macro" in beat_type.lower() or "texture" in beat_type.lower() or "drop" in beat_type.lower():
            return CharacterRole.PRODUCT_ONLY, AudioStrategy.ASMR_HYBRID
        return CharacterRole.MODEL, AudioStrategy.ASMR_HYBRID

    if archetype == ProductArchetype.TECH_GADGETS:
        if is_first:
            return CharacterRole.PRESENTER, AudioStrategy.ON_CAMERA_SPEECH
        if is_last:
            return CharacterRole.PRESENTER, AudioStrategy.ON_CAMERA_SPEECH
        if "macro" in beat_type.lower() or "unbox" in beat_type.lower() or "port" in beat_type.lower():
            return CharacterRole.PRODUCT_ONLY, AudioStrategy.ASMR_HYBRID
        return CharacterRole.MODEL, AudioStrategy.OFF_CAMERA_VO

    if archetype == ProductArchetype.HOME_LIFESTYLE:
        if is_last:
            return CharacterRole.MODEL, AudioStrategy.OFF_CAMERA_VO
        if "demo" in beat_type.lower() or "feature" in beat_type.lower() or "product" in beat_type.lower():
            return CharacterRole.PRODUCT_ONLY, AudioStrategy.ASMR_HYBRID
        return CharacterRole.MODEL, AudioStrategy.OFF_CAMERA_VO

    # General commercial
    if is_first or is_last:
        return CharacterRole.PRESENTER, AudioStrategy.ON_CAMERA_SPEECH
    if "solution" in beat_type.lower() or "demo" in beat_type.lower() or "macro" in beat_type.lower():
        return CharacterRole.PRODUCT_ONLY, AudioStrategy.OFF_CAMERA_VO
    return CharacterRole.MODEL, AudioStrategy.OFF_CAMERA_VO


# ==============================================================================
# Deterministic Product-to-Archetype Classification
# ==============================================================================

# Keywords are stored accent-stripped / lower-case (see ``_normalize_text``) and matched on word
# boundaries so a short token such as "ao" never fires inside "dao".
_ARCHETYPE_KEYWORDS: Dict[ProductArchetype, Tuple[str, ...]] = {
    ProductArchetype.FASHION_APPAREL: (
        "dam", "vay", "ao", "quan", "ao khoac", "blazer", "jacket", "dress", "skirt", "shirt",
        "jeans", "hoodie", "sweater", "cardigan", "corset", "phom", "form dang", "thoi trang",
        "giay", "sneaker", "tui xach", "handbag", "fashion", "outfit", "lookbook", "do bo", "set do",
    ),
    ProductArchetype.TECH_GADGETS: (
        "ban phim", "keyboard", "chuot", "mouse", "tai nghe", "earbuds", "headphone", "bluetooth",
        "wireless", "khong day", "sac du phong", "power bank", "usb", "cap sac", "sac nhanh", "pin",
        "loa", "speaker", "camera", "man hinh", "laptop", "dien thoai", "smartwatch", "dong ho thong minh",
        "gadget", "rgb", "led", "cong nghe", "robot", "may chieu",
    ),
    ProductArchetype.BEAUTY_SKINCARE: (
        "serum", "kem duong", "kem chong nang", "sunscreen", "spf", "duong da", "duong am", "skincare",
        "makeup", "trang diem", "son moi", "lipstick", "mat na", "toner", "cleanser", "sua rua mat",
        "tay trang", "collagen", "retinol", "vitamin c", "da dau", "da kho", "da mun", "lan da",
        "nuoc hoa", "perfume", "dau goi", "dau xa", "cham soc da", "lam dep",
    ),
    ProductArchetype.HOME_LIFESTYLE: (
        "nen thom", "tinh dau", "decor", "trang tri", "phong khach", "phong ngu", "nha bep", "nha cua",
        "ly giu nhiet", "binh giu nhiet", "coc", "binh nuoc", "noi chien", "noi com", "may xay",
        "den ngu", "den ban", "chan ga", "goi om", "tham", "ke sach", "hop dung", "do gia dung",
        "kitchen", "candle", "home", "furniture", "noi that", "ap cuc", "cozy", "am cung",
    ),
}


def _normalize_text(text: str) -> str:
    """Lower-case, strip Vietnamese diacritics and collapse punctuation to single spaces."""
    lowered = text.replace("đ", "d").replace("Đ", "D").lower()
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFD", lowered) if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def classify_product_archetype(text: str) -> ProductArchetype:
    """Deterministically map free product text (title, copy, URL slug) to a ProductArchetype.

    Counts distinct keyword hits per archetype (accent/case-insensitive, whole-word). The archetype
    with the most hits wins; ties resolve in declaration order; no hits yields GENERAL_COMMERCIAL.
    """
    haystack = f" {_normalize_text(text or '')} "
    if haystack.strip() == "":
        return ProductArchetype.GENERAL_COMMERCIAL
    best = ProductArchetype.GENERAL_COMMERCIAL
    best_score = 0
    for archetype, keywords in _ARCHETYPE_KEYWORDS.items():
        score = sum(
            1 for kw in keywords if re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", haystack)
        )
        if score > best_score:
            best, best_score = archetype, score
    return best
