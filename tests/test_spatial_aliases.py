"""Archetype camera/lighting names must resolve to the spatial staging registry (stage 3)."""

import pytest

from pipeline.archetypes import CameraChoreography, LightingContract
from pipeline.spatial_staging import (
    CAMERA_CHOREOGRAPHY_REGISTRY,
    LIGHTING_CONTRACT_REGISTRY,
    CameraChoreographyType,
    DramaClawSpatialGrammar,
    LightingContractType,
    resolve_choreography_type,
    resolve_lighting_type,
)


@pytest.mark.parametrize("choreo", list(CameraChoreography))
def test_every_archetype_choreography_resolves_to_registry(choreo):
    assert resolve_choreography_type(choreo.value) in CAMERA_CHOREOGRAPHY_REGISTRY


@pytest.mark.parametrize("light", list(LightingContract))
def test_every_archetype_lighting_resolves_to_registry(light):
    assert resolve_lighting_type(light.value) in LIGHTING_CONTRACT_REGISTRY


def test_specific_aliases_are_not_silently_defaulted():
    assert resolve_choreography_type("drone_flythrough") == CameraChoreographyType.DRONE_FLY_THROUGH
    assert resolve_choreography_type("macro_push_in") == CameraChoreographyType.ZOOM_IN
    assert resolve_lighting_type("golden_hour") == LightingContractType.GOLDEN_HOUR_NATURAL
    assert resolve_lighting_type("nordic_minimalist") == LightingContractType.MINIMALIST_NORDIC_INTERIOR


def test_synthesized_prompt_uses_resolved_specs():
    prompt = DramaClawSpatialGrammar.synthesize_shot_prompt(
        character_tag="[KOL]",
        identity_lock="same face",
        scene_action="walks",
        choreography="drone_flythrough",
        lighting="golden_hour",
    )
    assert "Drone FPV Fly-Through".upper() in prompt
    assert "3200K" in prompt
