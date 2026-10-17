"""Canonical artifact schemas and validation."""

from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, Field


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


class ScriptBeat(BaseModel):
    scene_id: str
    beat_type: str  # "hook", "pain", "solution", "cta"
    spoken_text: str
    on_screen_text: str
    visual_cue: str
    estimated_duration: float


class ScriptArtifact(BaseModel):
    campaign_id: str
    product_name: str
    target_duration: float
    beats: List[ScriptBeat]


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


class ScenePlanArtifact(BaseModel):
    campaign_id: str
    shots: List[StoryboardShot]


class KeyframeAsset(BaseModel):
    shot_id: str
    image_path: str
    cleaned_image_path: str
    watermark_removed: bool
    width: int
    height: int


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
