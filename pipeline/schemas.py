"""Canonical artifact schemas and validation."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from pipeline.archetypes import (
    AudioStrategy,
    CameraChoreography,
    CharacterRole,
    LightingContract,
    ProductArchetype,
)
from pipeline.cinematography import CameraAngle, CameraLens, ShotScale

MAX_TRANSITION_DURATION = 1.5


def validate_transition(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Normalise a transition ({type, duration}) against the composer's supported set, or None."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("transition must be a dict {type, duration} or None")
    # Imported lazily: composer imports this module. The composer owns the vocabulary.
    from pipeline.composer import SUPPORTED_TRANSITIONS

    t_type = str(value.get("type", "cut")).strip().lower()
    if t_type not in SUPPORTED_TRANSITIONS:
        raise ValueError(f"transition type {t_type!r} not supported; use one of {', '.join(SUPPORTED_TRANSITIONS)}")
    duration = float(value.get("duration", 0.0))
    if duration < 0 or duration > MAX_TRANSITION_DURATION:
        raise ValueError(f"transition duration must be within 0..{MAX_TRANSITION_DURATION}s")
    return {"type": t_type, "duration": 0.0 if t_type == "cut" else duration}


class PresenterInfo(BaseModel):
    name: str = "Mai Ly"
    character_tag: str = "[KOL_MAIN]"
    role: str = "Lead Presenter / Protagonist"
    character_file: str = "assets/characters/kol_main/character.json"


class BriefArtifact(BaseModel):
    campaign_id: str
    product_name: str
    target_persona: str
    pain_points: List[str]
    usps: List[str]
    visual_tone: str
    aspect_ratio: str = "9:16"
    presenter: PresenterInfo = Field(default_factory=PresenterInfo)
    archetype: ProductArchetype = ProductArchetype.GENERAL_COMMERCIAL
    category: Optional[str] = None
    character_role: CharacterRole = CharacterRole.PRESENTER
    target_audio_strategy: AudioStrategy = AudioStrategy.ON_CAMERA_SPEECH
    # Offers/prices the advertiser actually supplied (e.g. "Giảm 20% đến hết 30/6").
    # The scriptwriter never invents offers; with none supplied it uses neutral CTA copy.
    offers: List[str] = Field(default_factory=list)

class ScriptBeat(BaseModel):
    scene_id: str
    beat_type: str  # "hook", "pain", "solution", "cta"
    spoken_text: str
    on_screen_text: str
    visual_cue: str
    estimated_duration: float
    archetype: Optional[ProductArchetype] = None
    character_role: CharacterRole = CharacterRole.PRESENTER
    audio_strategy: AudioStrategy = AudioStrategy.ON_CAMERA_SPEECH
    camera_choreography: Optional[CameraChoreography] = None
    lighting_contract: Optional[LightingContract] = None
    narrative_purpose: Optional[str] = None
    # English visual description for video models (spoken_text / on_screen_text stay Vietnamese).
    visual_cue_en: Optional[str] = None
    # English image-to-video motion for this shot: subject action + speed + ending state, no appearance/set.
    motion_cue_en: Optional[str] = None
    # Optional agent direction persisted in script.json; storyboard honours it over its own planning.
    shot_scale: Optional[ShotScale] = None
    lens: Optional[CameraLens] = None
    angle: Optional[CameraAngle] = None
    # Transition INTO this beat from the previous one: {"type": <composer transition>, "duration": s}.
    transition: Optional[Dict[str, Any]] = None

    @field_validator("transition")
    @classmethod
    def _check_transition(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return validate_transition(v)

class ScriptArtifact(BaseModel):
    campaign_id: str
    product_name: str
    target_duration: float
    beats: List[ScriptBeat]
    archetype: ProductArchetype = ProductArchetype.GENERAL_COMMERCIAL

class StoryboardShot(BaseModel):
    shot_id: str
    scene_id: str
    shot_type: str  # e.g., "Extreme Close-Up", "Medium Presenter Shot", "Macro Detail"
    angle: str
    camera_motion: str
    lighting: str
    character_tag: Optional[str] = None
    identity_lock_directive: Optional[str] = None
    style_constraints: str
    scene_description: str
    prompt_6part: str  # still first-frame description (Stage 4 image prompt)
    # Stage 5 image-to-video prompt: Hailuo camera command + motion only. Older plans: None (prompt_6part used).
    motion_prompt: Optional[str] = None
    estimated_duration: float
    reference_expression: Optional[str] = None
    character_role: Optional[CharacterRole] = None
    camera_choreography: Optional[str] = None
    lighting_contract: Optional[str] = None
    spatial_staging: Optional[str] = None
    color_temp_kelvin: Optional[int] = None
    shot_intent: Optional[str] = None
    kinetic_action: Optional[str] = None
    is_hero_moment: Optional[bool] = False
    # Transition into this shot from the previous one (copied from the script beat).
    transition: Optional[Dict[str, Any]] = None
    generation_mode: Optional[str] = None  # "i2v", "r2v", "product_hero"
    reference_assets: Optional[List[str]] = None

class ScenePlanArtifact(BaseModel):
    campaign_id: str
    shots: List[StoryboardShot]
    slideshow_risk: Optional[Dict[str, Any]] = None
    spatial_staging_contract: Optional[Dict[str, Any]] = None
    storyboard_contact_sheet: Optional[str] = None
class KeyframeAsset(BaseModel):
    shot_id: str
    image_path: Optional[str] = None
    cleaned_image_path: Optional[str] = None
    watermark_removed: bool = False
    width: int = 1080
    height: int = 1920
    generation_mode: Optional[str] = None
    reference_assets: Optional[List[str]] = None
    # "synthesized" (scene frame rendered from references), "reference_pad" (the reference itself
    # padded to 9:16: not the planned scene) or "override" (agent-supplied first frame).
    keyframe_source: Optional[str] = None
    synthesis_references: Optional[List[str]] = None
    synthesis_error: Optional[str] = None
    identity_vs_anchor: Optional[float] = None
class AssetManifestArtifact(BaseModel):
    campaign_id: str
    keyframes: List[KeyframeAsset]
    audio_stems: List[str] = Field(default_factory=list)
    raw_video_clips: List[str] = Field(default_factory=list)
    synced_video_clips: List[str] = Field(default_factory=list)


class AudioTrackConfig(BaseModel):
    track_id: str
    type: str  # "voiceover", "bgm", "sfx"
    file_path: str
    target_lufs: Optional[float] = None
    ducking_attenuation_db: Optional[float] = None


class EditDecisionsArtifact(BaseModel):
    campaign_id: str
    render_runtime: str = "ffmpeg"
    target_aspect_ratio: str = "9:16"
    timeline_clips: List[str]
    audio_tracks: List[AudioTrackConfig]
    transitions: List[dict] = Field(default_factory=list)
    captions: List[dict] = Field(default_factory=list)
    output_master_path: str


class GateVerificationResult(BaseModel):
    gate_name: str
    passed: bool
    details: dict[str, Any]
    error_message: Optional[str] = None


class RenderReportArtifact(BaseModel):
    campaign_id: str
    master_video_path: str
    file_size_bytes: int
    duration_seconds: float
    video_codec: str
    audio_codec: str
    width: int
    height: int
    aspect_ratio: str
    verification_gates: List[GateVerificationResult]
    overall_status: str


class PublishLogArtifact(BaseModel):
    campaign_id: str
    product_name: str
    master_video_path: str
    thumbnail_path: str
    title: str
    description: str
    hashtags: List[str]
    published_at: str

# ==============================================================================
# Competitor Research & Creative Concept Artifact Re-exports
# ==============================================================================
from pipeline.researcher import (
    CompetitorLandscape,
    CompetitorResearchArtifact,
    CreativeAngle,
    CreativeConceptArtifact,
    DirectorialDirectives,
    HookStrategy,
    ObjectionProof,
    ProductIntel,
    ProductPricing,
    SelectedWinningAngle,
    ViralHookCandidate,
)
