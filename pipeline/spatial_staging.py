"""DramaClaw Spatial Scene Staging Engine for AI Commercial Production.

Provides structured camera choreography definitions, lighting & environment contracts,
spatial continuity validation across shots, and a prompt grammar compliant with
DramaClaw / SuperTale director world conventions.
"""

from __future__ import annotations

import enum
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class CameraChoreographyType(str, enum.Enum):
    """Canonical camera choreography taxonomy for high-conversion commercial video."""
    TRUCK = "truck"                    # Lateral movement perpendicular to optical axis
    PAN = "pan"                        # Horizontal rotational scan around nodal point
    TILT = "tilt"                      # Vertical rotational pitch around horizontal axis
    PEDESTAL = "pedestal"              # Vertical bodily elevation along Y axis
    ZOOM_IN = "zoom_in"                # Focal length change or dolly push-in toward subject
    ORBIT = "orbit"                    # Arc / 360 circular rotation around subject center
    DRONE_FLY_THROUGH = "drone_fly_through"  # Aerial dynamic glide sweeping through 3D space
    DUTCH_ANGLE = "dutch_angle"        # Canted roll 15°-45° off-axis creating tension/urgency


class CameraChoreographySpec(BaseModel):
    """Specification for a camera choreography maneuver."""
    choreography_type: CameraChoreographyType
    name: str
    direction: str                     # e.g., "left_to_right", "upwards", "clockwise_45deg"
    speed: str                         # "slow_cinematic", "dynamic_snappy", "steady_fluid"
    narrative_purpose: str             # e.g., "Contextual pacing", "Product reveal", "Urgency hook"
    diffusion_motion_cue: str          # Unambiguous motion verbs for video diffusion models
    focal_depth_cue: str = "shallow depth of field, crisp subject focus"

    def to_prompt_clause(self) -> str:
        return (
            f"Camera choreography: {self.name.upper()} ({self.direction}, {self.speed}). "
            f"{self.diffusion_motion_cue}. {self.focal_depth_cue}"
        )


CAMERA_CHOREOGRAPHY_REGISTRY: Dict[CameraChoreographyType, CameraChoreographySpec] = {
    CameraChoreographyType.TRUCK: CameraChoreographySpec(
        choreography_type=CameraChoreographyType.TRUCK,
        name="Truck Lateral Glide",
        direction="smooth lateral tracking shot moving parallel to workspace",
        speed="steady_fluid",
        narrative_purpose="Pacing across workspace, establishing physical context without cutting",
        diffusion_motion_cue="Continuous physical camera translation on dolly rails from screen-left to screen-right, maintaining parallel parallax against background objects",
        focal_depth_cue="medium depth of field, sharp foreground tracking",
    ),
    CameraChoreographyType.PAN: CameraChoreographySpec(
        choreography_type=CameraChoreographyType.PAN,
        name="Horizontal Pan",
        direction="pan left to right following subject line of sight",
        speed="slow_cinematic",
        narrative_purpose="Guiding viewer eye from consumer pain point to hero product solution",
        diffusion_motion_cue="Smooth tripod pan rotating horizontally around nodal axis, sweeping fluidly across the scene",
        focal_depth_cue="deep focus background elements, tack-sharp focal subject",
    ),
    CameraChoreographyType.TILT: CameraChoreographySpec(
        choreography_type=CameraChoreographyType.TILT,
        name="Vertical Tilt",
        direction="tilt up from product base to presenter expressive face",
        speed="dynamic_snappy",
        narrative_purpose="Connecting tactile product details to presenter emotional validation",
        diffusion_motion_cue="Vertical camera pitch tilt rotating smoothly upwards on tripod head, revealing character reaction",
        focal_depth_cue="rack focus from close-up product to presenter eyes",
    ),
    CameraChoreographyType.PEDESTAL: CameraChoreographySpec(
        choreography_type=CameraChoreographyType.PEDESTAL,
        name="Pedestal Elevation",
        direction="pedestal crane up from low table surface to eye level",
        speed="slow_cinematic",
        narrative_purpose="Grand hero reveal elevating ordinary everyday object into premium lifestyle status",
        diffusion_motion_cue="Vertical jib crane elevator movement rising steadily straight up without changing tilt angle",
        focal_depth_cue="smooth bokeh transition as camera ascends",
    ),
    CameraChoreographyType.ZOOM_IN: CameraChoreographySpec(
        choreography_type=CameraChoreographyType.ZOOM_IN,
        name="Cinematic Push-In Zoom",
        direction="forward dolly push-in directly toward center of interest",
        speed="steady_fluid",
        narrative_purpose="Intensifying emotional focus, micro-inspection of LED digital display / texture",
        diffusion_motion_cue="Rapid optical and dolly push-in zooming steadily toward subject, background compression increasing",
        focal_depth_cue="creamy cinematic background blur, ultra-crisp macro details",
    ),
    CameraChoreographyType.ORBIT: CameraChoreographySpec(
        choreography_type=CameraChoreographyType.ORBIT,
        name="Commercial Arc Orbit",
        direction="45-to-90 degree circular arc orbit around subject center of mass",
        speed="slow_cinematic",
        narrative_purpose="Creating high-end luxury commercial dimensionality and 3D specular light play",
        diffusion_motion_cue="Smooth circular orbital arc track circling around the presenter and product, continuous perspective parallax",
        focal_depth_cue="tack-sharp rotating focal plane with soft swirling background bokeh",
    ),
    CameraChoreographyType.DRONE_FLY_THROUGH: CameraChoreographySpec(
        choreography_type=CameraChoreographyType.DRONE_FLY_THROUGH,
        name="Drone FPV Fly-Through",
        direction="sweeping forward aerial glide penetrating environment into hero presenter",
        speed="dynamic_snappy",
        narrative_purpose="High-energy viral hook, establishing lifestyle setting and modern tempo",
        diffusion_motion_cue="Dynamic flying drone trajectory gliding seamlessly through interior space, steady gimbal stabilization",
        focal_depth_cue="wide-angle cinematic field of view with sweeping depth",
    ),
    CameraChoreographyType.DUTCH_ANGLE: CameraChoreographySpec(
        choreography_type=CameraChoreographyType.DUTCH_ANGLE,
        name="Dutch Canted Angle",
        direction="25-degree roll canted off-horizontal axis",
        speed="steady_fluid",
        narrative_purpose="Visual tension and psychological urgency during hook and pain beats",
        diffusion_motion_cue="Deliberately canted Dutch camera angle with slight creeping push-in, conveying dramatic problem disruption",
        focal_depth_cue="dynamic diagonal composition with sharp graphic silhouettes",
    ),
}


class LightingContractType(str, enum.Enum):
    """Canonical lighting environments maintaining spatial color temperature continuity."""
    THREE_POINT_STUDIO = "three_point_studio"
    GOLDEN_HOUR_NATURAL = "golden_hour_natural"
    CYBERPUNK_NEON = "cyberpunk_neon"
    MINIMALIST_NORDIC_INTERIOR = "minimalist_nordic_interior"


class LightingContractSpec(BaseModel):
    """Lighting and environment contract."""
    contract_type: LightingContractType
    name: str
    nominal_kelvin: int                # e.g., 5600 for daylight studio, 3200 for warm golden hour
    key_light_azimuth: int             # Angle in degrees relative to camera: 45 = camera-left
    key_light_elevation: int           # Angle above horizon (e.g. 30 degrees)
    fill_ratio: float                  # Ratio of fill to key (e.g. 0.5)
    rim_intensity: str                 # "subtle", "sharp_edge", "high_contrast_specular"
    color_palette: List[str]
    atmosphere_notes: str

    def to_prompt_clause(self) -> str:
        palette_str = ", ".join(self.color_palette)
        return (
            f"Lighting contract: {self.name.upper()} ({self.nominal_kelvin}K color temperature). "
            f"Key light at {self.key_light_azimuth}° azimuth, {self.key_light_elevation}° elevation; "
            f"fill ratio {self.fill_ratio}; rim lighting: {self.rim_intensity}. "
            f"Color palette: {palette_str}. {self.atmosphere_notes}"
        )


LIGHTING_CONTRACT_REGISTRY: Dict[LightingContractType, LightingContractSpec] = {
    LightingContractType.THREE_POINT_STUDIO: LightingContractSpec(
        contract_type=LightingContractType.THREE_POINT_STUDIO,
        name="3-Point Commercial Studio",
        nominal_kelvin=5600,
        key_light_azimuth=45,
        key_light_elevation=35,
        fill_ratio=0.5,
        rim_intensity="sharp_edge",
        color_palette=["neutral white", "soft warm skin tones", "corporate slate gray", "matte black"],
        atmosphere_notes="Clean commercial high-key illumination, diffuse softbox highlights, high CRI 98+, zero harsh facial shadows.",
    ),
    LightingContractType.GOLDEN_HOUR_NATURAL: LightingContractSpec(
        contract_type=LightingContractType.GOLDEN_HOUR_NATURAL,
        name="Golden Hour Natural Sunlight",
        nominal_kelvin=3200,
        key_light_azimuth=60,
        key_light_elevation=15,
        fill_ratio=0.35,
        rim_intensity="high_contrast_specular",
        color_palette=["warm amber", "honey gold", "terracotta", "deep warm shadows"],
        atmosphere_notes="Low-angle raking sunlight casting elongated soft penumbra shadows, subtle warm anamorphic flare, luminous rim glows.",
    ),
    LightingContractType.CYBERPUNK_NEON: LightingContractSpec(
        contract_type=LightingContractType.CYBERPUNK_NEON,
        name="Cyberpunk Dual-Tone Neon",
        nominal_kelvin=6500,
        key_light_azimuth=-45,
        key_light_elevation=25,
        fill_ratio=0.3,
        rim_intensity="high_contrast_specular",
        color_palette=["electric cyan", "hot magenta", "deep indigo", "glossy obsidian"],
        atmosphere_notes="High-contrast dual-tone chromatic lighting, saturated rim highlights on glossy tech surfaces, dark atmospheric falloff.",
    ),
    LightingContractType.MINIMALIST_NORDIC_INTERIOR: LightingContractSpec(
        contract_type=LightingContractType.MINIMALIST_NORDIC_INTERIOR,
        name="Minimalist Nordic Architectural Daylight",
        nominal_kelvin=5000,
        key_light_azimuth=40,
        key_light_elevation=30,
        fill_ratio=0.6,
        rim_intensity="subtle",
        color_palette=["natural birch wood", "matte chalk white", "soft sage", "pale cream"],
        atmosphere_notes="Soft wraparound indirect daylight from large Scandinavian window bay, ultra-smooth gradient falloff, clean zen aesthetic.",
    ),
}


class SpatialAnchor(BaseModel):
    """Spatial topology anchor representing an established location in the stage world."""
    anchor_id: str
    name: str
    zone_description: str
    fixed_fixtures: List[str] = Field(default_factory=list)
    forbidden_transforms: List[str] = Field(default_factory=list)

    def to_prompt_clause(self) -> str:
        fixtures_str = ", ".join(self.fixed_fixtures) if self.fixed_fixtures else "uncluttered space"
        forbidden_str = (
            f" (Do not transform or move: {', '.join(self.forbidden_transforms)})"
            if self.forbidden_transforms
            else ""
        )
        return f"Spatial staging anchor [{self.anchor_id}]: {self.zone_description}. Fixed stage fixtures: {fixtures_str}{forbidden_str}."


class SpatialContinuityContract(BaseModel):
    """Enforces spatial, lighting, and color temperature continuity across shots."""
    environment_name: str = "Modern Executive Home Office"
    lighting_contract_type: LightingContractType = LightingContractType.MINIMALIST_NORDIC_INTERIOR
    nominal_kelvin: int = 5000
    max_kelvin_drift: int = 200        # Max allowed color temp variation across shots
    locked_key_light_azimuth: int = 40 # Lock key light to camera-left across all shots
    active_anchors: Dict[str, SpatialAnchor] = Field(default_factory=dict)

    def validate_shot_continuity(
        self,
        shot_kelvins: List[Tuple[str, int]],
        shot_azimuths: Optional[List[Tuple[str, int]]] = None,
    ) -> Tuple[bool, List[str]]:
        """Validates that a sequence of shots respects color temperature and lighting vectors."""
        errors: List[str] = []
        for shot_id, k in shot_kelvins:
            drift = abs(k - self.nominal_kelvin)
            if drift > self.max_kelvin_drift:
                errors.append(
                    f"Shot '{shot_id}' color temp {k}K exceeds max drift ({self.max_kelvin_drift}K) "
                    f"from nominal {self.nominal_kelvin}K (drift={drift}K)."
                )

        if shot_azimuths:
            for shot_id, az in shot_azimuths:
                # Key light flipping from left (positive) to right (negative) without narrative reason
                if (az > 0 and self.locked_key_light_azimuth < 0) or (az < 0 and self.locked_key_light_azimuth > 0):
                    errors.append(
                        f"Shot '{shot_id}' key light azimuth ({az}°) flipped sign relative to locked "
                        f"environment azimuth ({self.locked_key_light_azimuth}°)."
                    )

        return (len(errors) == 0, errors)


class DramaClawSpatialGrammar:
    """DramaClaw compliant spatial prompt synthesizer for video diffusion models."""

    @staticmethod
    def synthesize_shot_prompt(
        character_tag: str,
        identity_lock: str,
        scene_action: str,
        choreography: CameraChoreographySpec | CameraChoreographyType | str,
        lighting: LightingContractSpec | LightingContractType | str,
        spatial_anchor: SpatialAnchor | str | None = None,
        style_positive: str = "cinematic photorealistic, 8k commercial grade, tack-sharp focal details",
        style_negative: str = "watermark, logo, text, deformed limbs, blurry, jumpy camera, slideshow, static still",
    ) -> str:
        """Synthesizes a 7-part DramaClaw structured spatial prompt."""
        # Resolve choreography
        if isinstance(choreography, str):
            try:
                ch_type = CameraChoreographyType(choreography.lower())
                choreography_spec = CAMERA_CHOREOGRAPHY_REGISTRY[ch_type]
            except (ValueError, KeyError):
                choreography_spec = CAMERA_CHOREOGRAPHY_REGISTRY[CameraChoreographyType.TRUCK]
        elif isinstance(choreography, CameraChoreographyType):
            choreography_spec = CAMERA_CHOREOGRAPHY_REGISTRY[choreography]
        else:
            choreography_spec = choreography

        # Resolve lighting
        if isinstance(lighting, str):
            try:
                lt_type = LightingContractType(lighting.lower())
                lighting_spec = LIGHTING_CONTRACT_REGISTRY[lt_type]
            except (ValueError, KeyError):
                lighting_spec = LIGHTING_CONTRACT_REGISTRY[LightingContractType.THREE_POINT_STUDIO]
        elif isinstance(lighting, LightingContractType):
            lighting_spec = LIGHTING_CONTRACT_REGISTRY[lighting]
        else:
            lighting_spec = lighting

        # Spatial anchor text
        if isinstance(spatial_anchor, SpatialAnchor):
            anchor_text = spatial_anchor.to_prompt_clause()
        elif isinstance(spatial_anchor, str) and spatial_anchor.strip():
            anchor_text = f"Spatial staging: {spatial_anchor.strip()}."
        else:
            anchor_text = "Spatial staging: established modern interior workspace."

        parts = [
            f"{character_tag} {identity_lock}.",
            f"Scene Action: {scene_action}.",
            anchor_text,
            choreography_spec.to_prompt_clause(),
            lighting_spec.to_prompt_clause(),
            f"Style & Optics: {style_positive}.",
            f"Negative constraints: {style_negative}.",
        ]

        return " ".join(parts)
