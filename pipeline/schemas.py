"""Canonical artifact schemas and validation."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from pipeline.archetypes import (
    AudioStrategy,
    CameraChoreography,
    CharacterRole,
    LightingContract,
    ProductArchetype,
)

class PresenterInfo(BaseModel):
    name: str = "Minh Anh"
    character_tag: str = "[KOL_MA]"
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
    prompt_6part: str
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
