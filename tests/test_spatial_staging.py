import pytest

from pipeline.spatial_staging import (
    CameraChoreographySpec,
    CameraChoreographyType,
    CAMERA_CHOREOGRAPHY_REGISTRY,
    LightingContractSpec,
    LightingContractType,
    LIGHTING_CONTRACT_REGISTRY,
    SpatialAnchor,
    SpatialContinuityContract,
    DramaClawSpatialGrammar,
)


def test_camera_choreography_registry_completeness():
    required_types = {
        CameraChoreographyType.TRUCK,
        CameraChoreographyType.PAN,
        CameraChoreographyType.TILT,
        CameraChoreographyType.PEDESTAL,
        CameraChoreographyType.ZOOM_IN,
        CameraChoreographyType.ORBIT,
        CameraChoreographyType.DRONE_FLY_THROUGH,
        CameraChoreographyType.DUTCH_ANGLE,
    }
    assert set(CAMERA_CHOREOGRAPHY_REGISTRY.keys()) == required_types

    for ch_type, spec in CAMERA_CHOREOGRAPHY_REGISTRY.items():
        assert spec.choreography_type == ch_type
        clause = spec.to_prompt_clause()
        assert "Camera choreography:" in clause
        assert spec.diffusion_motion_cue in clause


def test_lighting_contract_registry_completeness():
    required_types = {
        LightingContractType.THREE_POINT_STUDIO,
        LightingContractType.GOLDEN_HOUR_NATURAL,
        LightingContractType.CYBERPUNK_NEON,
        LightingContractType.MINIMALIST_NORDIC_INTERIOR,
        LightingContractType.NATURAL_DAYLIGHT,
        LightingContractType.OVERCAST_DAYLIGHT,
        LightingContractType.PRACTICAL_NIGHT,
    }
    assert set(LIGHTING_CONTRACT_REGISTRY.keys()) == required_types
    # Real locations need real daylight, not golden hour or a studio rim (QA preprod r1).
    assert LIGHTING_CONTRACT_REGISTRY[LightingContractType.NATURAL_DAYLIGHT].nominal_kelvin == 5600
    assert LIGHTING_CONTRACT_REGISTRY[LightingContractType.OVERCAST_DAYLIGHT].nominal_kelvin == 6500

    # Check nominal Kelvins
    assert LIGHTING_CONTRACT_REGISTRY[LightingContractType.THREE_POINT_STUDIO].nominal_kelvin == 5600
    assert LIGHTING_CONTRACT_REGISTRY[LightingContractType.GOLDEN_HOUR_NATURAL].nominal_kelvin == 3200
    assert LIGHTING_CONTRACT_REGISTRY[LightingContractType.CYBERPUNK_NEON].nominal_kelvin == 6500
    assert LIGHTING_CONTRACT_REGISTRY[LightingContractType.MINIMALIST_NORDIC_INTERIOR].nominal_kelvin == 5000

    for lt_type, spec in LIGHTING_CONTRACT_REGISTRY.items():
        clause = spec.to_prompt_clause()
        assert "Lighting contract:" in clause
        assert f"{spec.nominal_kelvin}K" in clause


def test_spatial_continuity_validation():
    contract = SpatialContinuityContract(
        environment_name="Nordic Studio",
        lighting_contract_type=LightingContractType.MINIMALIST_NORDIC_INTERIOR,
        nominal_kelvin=5000,
        max_kelvin_drift=200,
        locked_key_light_azimuth=40,
    )

    # Valid shots: kelvins within 5000 ± 200 (4900, 5100), key light azimuth 40
    valid_kelvins = [("shot_01", 5000), ("shot_02", 5100), ("shot_03", 4950)]
    valid_azimuths = [("shot_01", 40), ("shot_02", 45), ("shot_03", 35)]
    ok, errors = contract.validate_shot_continuity(valid_kelvins, valid_azimuths)
    assert ok is True
    assert len(errors) == 0

    # Drift violation: shot_02 at 5400K (drift 400K > 200K)
    bad_kelvins = [("shot_01", 5000), ("shot_02", 5400)]
    ok, errors = contract.validate_shot_continuity(bad_kelvins)
    assert ok is False
    assert any("exceeds max drift" in e for e in errors)

    # Light direction flip violation: shot_02 key light flipped to -45 (camera-right)
    flipped_azimuths = [("shot_01", 40), ("shot_02", -45)]
    ok, errors = contract.validate_shot_continuity(valid_kelvins[:2], flipped_azimuths)
    assert ok is False
    assert any("flipped sign" in e for e in errors)


def test_dramaclaw_spatial_grammar_synthesizer():
    anchor = SpatialAnchor(
        anchor_id="center_desk",
        name="Executive Desk Center Mark",
        zone_description="Minimalist oak desk centered in frame, window bay on screen-left",
        fixed_fixtures=["oak desk", "matte black laptop", "ceramic coaster"],
        forbidden_transforms=["relocate window to right side", "substitute desk for metal table"],
    )

    prompt = DramaClawSpatialGrammar.synthesize_shot_prompt(
        character_tag="[KOL_MAIN]",
        identity_lock="Vietnamese young woman, early 20s, refined oval face",
        scene_action="gently taps the LED touch lid of the Lumina Smart Mug revealing 65C display",
        choreography=CameraChoreographyType.ORBIT,
        lighting=LightingContractType.THREE_POINT_STUDIO,
        spatial_anchor=anchor,
        style_positive="cinematic photorealistic, 8k commercial grade, tack-sharp focal details",
        style_negative="watermark, deformed hands, blurry, static slideshow",
    )

    assert "[KOL_MAIN]" in prompt
    assert "Vietnamese young woman" in prompt
    assert "Scene Action: gently taps the LED touch lid" in prompt
    assert "Spatial staging anchor [center_desk]" in prompt
    assert "Camera choreography: COMMERCIAL ARC ORBIT" in prompt
    assert "Lighting contract: 3-POINT COMMERCIAL STUDIO (5600K color temperature)" in prompt
    assert "Style & Optics:" in prompt
    assert "Negative constraints:" in prompt
