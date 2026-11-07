"""Offline contract tests for the ComfyUI gateway video provider (``pipeline.comfy_video``).

The templates in ``tests/fixtures/comfy`` are the gateway's own UI workflows (Comfy-Org
templates), so the converter and the graph builders are exercised against the real inputs
without touching the network.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import comfy_video as cv
from pipeline.comfy_ui2api import convert

FIXTURES = Path(__file__).parent / "fixtures" / "comfy"
TEMPLATES = {
    cv.FLOW_T2V: FIXTURES / "pika-h3-flex-t2v.json",
    cv.FLOW_FL2VA: FIXTURES / "pika-h3-flex-fl2va.json",
    cv.FLOW_REF2VA: FIXTURES / "pika-h3-flex-ref2va.json",
}

#: Minimal node schemas: enough to coerce the widgets these templates use.
OBJECT_INFO = {
    "MiniMaxH3ImageToVideo": {"input": {"required": {
        "clip": ["CLIP", {}], "vae": ["VAE", {}], "prompt": ["STRING", {}],
        "width": ["INT", {}], "height": ["INT", {}], "length": ["INT", {}],
    }, "optional": {"first_frame": ["IMAGE", {}], "last_frame": ["IMAGE", {}]}}},
    "MiniMaxH3ReferenceToVideo": {"input": {"required": {
        "clip": ["CLIP", {}], "prompt": ["STRING", {}], "width": ["INT", {}],
        "height": ["INT", {}], "length": ["INT", {}], "ref_image_size": ["COMBO", {}],
    }, "optional": {"vae": ["VAE", {}], "audio_vae": ["VAE", {}],
                    "ref_images": ["COMFY_AUTOGROW_V3", {}]}}},
    "SaveVideo": {"input": {"required": {"video": ["VIDEO", {}], "filename_prefix": ["STRING", {}],
                                         "format": ["COMFY_DYNAMICCOMBO_V3", {}]},
                             "optional": {"codec": ["COMFY_DYNAMICCOMBO_V3", {}]}}},
    "LoadImage": {"input": {"required": {"image": ["COMBO", {}]}}},
    "CreateVideo": {"input": {"required": {"images": ["IMAGE", {}], "fps": ["FLOAT", {}]},
                              "optional": {"audio": ["AUDIO", {}], "bit_depth": ["COMBO", {}],
                                           "color_space": ["COMBO", {}], "chroma_subsampling": ["COMBO", {}],
                                           "codec": ["COMBO", {}]}}},
    "RandomNoise": {"input": {"required": {"noise_seed": ["INT", {}]}}},
    "VAELoader": {"input": {"required": {"vae_name": ["COMBO", {}]}}},
    "UNETLoader": {"input": {"required": {"unet_name": ["COMBO", {}], "weight_dtype": ["COMBO", {}]}}},
    "CLIPLoader": {"input": {"required": {"clip_name": ["COMBO", {}], "type": ["COMBO", {}]},
                              "optional": {"device": ["COMBO", {}]}}},
    "LoraLoaderModelOnly": {"input": {"required": {"model": ["MODEL", {}], "lora_name": ["COMBO", {}],
                                                   "strength_model": ["FLOAT", {}]}}},
    "KSamplerSelect": {"input": {"required": {"sampler_name": ["COMBO", {}]}}},
    "ManualSigmas": {"input": {"required": {"sigmas": ["STRING", {}]}}},
    "PrimitiveInt": {"input": {"required": {"value": ["INT", {}]}}},
    "PrimitiveFloat": {"input": {"required": {"value": ["FLOAT", {}]}}},
    "PrimitiveStringMultiline": {"input": {"required": {"value": ["STRING", {}]}}},
    "ComfyMathExpression": {"input": {"required": {"expression": ["STRING", {}]},
                                      "optional": {"values": ["COMFY_AUTOGROW_V3", {}]}}},
    "ResolutionSelector": {"input": {"required": {"aspect_ratio": ["COMBO", {}], "megapixels": ["FLOAT", {}],
                                                  "multiple": ["INT", {}]}}},
    "GetImageSize": {"input": {"required": {"image": ["IMAGE", {}]}}},
    "VAEDecode": {"input": {"required": {"samples": ["LATENT", {}], "vae": ["VAE", {}]}}},
    "VAEDecodeAudio": {"input": {"required": {"samples": ["LATENT", {}], "vae": ["VAE", {}]}}},
    "SamplerCustomAdvanced": {"input": {"required": {"noise": ["NOISE", {}], "guider": ["GUIDER", {}],
                                                       "sampler": ["SAMPLER", {}], "sigmas": ["SIGMAS", {}],
                                                       "latent_image": ["LATENT", {}]}}},
    "BasicGuider": {"input": {"required": {"model": ["MODEL", {}], "conditioning": ["CONDITIONING", {}]}}},
}


def _template(flow: str) -> dict:
    return json.loads(TEMPLATES[flow].read_text(encoding="utf-8"))


def _model_node(graph: dict) -> tuple:
    for node_id, node in graph.items():
        if node["class_type"] in ("MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"):
            return node_id, node
    raise AssertionError("no MiniMax H3 node in the converted graph")


# --- duration / geometry ------------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,frames",
    [(5, 124), (6, 158), (10, 243), (3.5, 90)],
)
def test_frames_follow_pika_grid(seconds, frames):
    assert cv.frames_for_duration(seconds) == frames


def test_normalize_duration_clamps_to_pika_range():
    assert cv.normalize_duration(3.0) == 5
    assert cv.normalize_duration(6.4) == 6
    assert cv.normalize_duration(30) == 15


def test_fit_resolution_keeps_aspect_and_size_multiple():
    width, height = cv.fit_resolution("9:16")
    assert width % cv.DEFAULT_SIZE_MULTIPLE == 0 and height % cv.DEFAULT_SIZE_MULTIPLE == 0
    assert abs(width / height - 9 / 16) < 0.05
    # A reference frame wins over the nominal aspect ratio.
    assert cv.fit_resolution("9:16", reference_size=(1920, 1080)) == (1312, 736)


# --- prompt binding ------------------------------------------------------------------


def test_t2v_prompt_is_sent_unchanged():
    assert cv.compose_prompt(cv.FLOW_T2V, "a slow push-in") == "a slow push-in"


def test_fl2va_prompt_states_the_first_frame_contract():
    out = cv.compose_prompt(cv.FLOW_FL2VA, "she turns to camera")
    assert "first frame" in out
    assert "last frame" not in out  # no last frame is supplied: do not promise one
    assert out.endswith("she turns to camera")


def test_fl2va_prompt_mentions_the_last_frame_only_when_one_is_supplied():
    out = cv.compose_prompt(cv.FLOW_FL2VA, "she turns", has_last_frame=True)
    assert "first frame" in out and "last frame" in out


def test_ref2va_prompt_declares_the_identity_anchor_as_picture_1():
    out = cv.compose_prompt(cv.FLOW_REF2VA, "she walks in", references=2)
    assert "<Picture 1>" in out and "identity anchor" in out
    assert "<Picture 2>" in out and "wardrobe anchor" in out
    assert out.endswith("she walks in")


# --- conversion ----------------------------------------------------------------------


def test_converter_expands_subgraph_and_keeps_dynamic_input_paths():
    graph = convert(_template(cv.FLOW_FL2VA), OBJECT_INFO)
    node_id, node = _model_node(graph)
    assert node["class_type"] == "MiniMaxH3ImageToVideo"
    # Dynamic (autogrow) inputs keep their dotted path in the API graph.
    math_nodes = [n for n in graph.values() if n["class_type"] == "ComfyMathExpression"]
    assert math_nodes and all("values.a" in n["inputs"] for n in math_nodes)
    # The subgraph's inner pipeline became real API nodes.
    assert any(n["class_type"] == "CreateVideo" for n in graph.values())


def test_converter_drops_frontend_only_nodes():
    graph = convert(_template(cv.FLOW_T2V), OBJECT_INFO)
    assert not any(n["class_type"] in ("MarkdownNote", "Note") for n in graph.values())


# --- graph building ------------------------------------------------------------------


def test_build_graph_t2v_has_no_image_input():
    with patch.object(cv, "fetch_template", return_value=_template(cv.FLOW_T2V)), \
         patch.object(cv, "load_object_info", return_value=OBJECT_INFO):
        graph = cv.build_graph(cv.FLOW_T2V, "a serum drop falls", width=736, height=1312, length=124)
    node_id, node = _model_node(graph)
    assert "first_frame" not in node["inputs"]
    assert "last_frame" not in node["inputs"]
    assert node["inputs"]["width"] == 736 and node["inputs"]["height"] == 1312
    assert node["inputs"]["length"] == 124


def test_build_graph_fl2va_wires_the_first_frame_and_drops_an_unused_last_frame():
    with patch.object(cv, "fetch_template", return_value=_template(cv.FLOW_FL2VA)), \
         patch.object(cv, "load_object_info", return_value=OBJECT_INFO):
        graph = cv.build_graph(cv.FLOW_FL2VA, "she turns", first_frame="first.png",
                               width=736, height=1312, length=124)
    node_id, node = _model_node(graph)
    target = node["inputs"]["first_frame"][0]
    assert graph[target]["class_type"] == "LoadImage"
    assert graph[target]["inputs"]["image"] == "first.png"
    assert "last_frame" not in node["inputs"]


def test_build_graph_ref2va_wires_every_reference_image():
    with patch.object(cv, "fetch_template", return_value=_template(cv.FLOW_REF2VA)), \
         patch.object(cv, "load_object_info", return_value=OBJECT_INFO):
        graph = cv.build_graph(cv.FLOW_REF2VA, "she walks", references=["face.png", "sheet.png"],
                               width=736, height=1312, length=124)
    node_id, node = _model_node(graph)
    first = graph[node["inputs"]["ref_images.ref_image_0"][0]]
    second = graph[node["inputs"]["ref_images.ref_image_1"][0]]
    assert first["inputs"]["image"] == "face.png"
    assert second["inputs"]["image"] == "sheet.png"


def test_build_graph_ref2va_without_references_is_refused():
    with patch.object(cv, "fetch_template", return_value=_template(cv.FLOW_REF2VA)), \
         patch.object(cv, "load_object_info", return_value=OBJECT_INFO):
        with pytest.raises(cv.ComfyVideoError, match="reference image"):
            cv.build_graph(cv.FLOW_REF2VA, "she walks", width=736, height=1312, length=124)


def test_build_graph_sets_the_output_prefix():
    with patch.object(cv, "fetch_template", return_value=_template(cv.FLOW_T2V)), \
         patch.object(cv, "load_object_info", return_value=OBJECT_INFO):
        graph = cv.build_graph(cv.FLOW_T2V, "p", width=736, height=1312, length=124,
                               filename_prefix="kol/shot_01")
    save = next(n for n in graph.values() if n["class_type"] == "SaveVideo")
    assert save["inputs"]["filename_prefix"] == "kol/shot_01"


# --- error classification -------------------------------------------------------------


def test_validation_and_auth_errors_are_not_retryable():
    assert cv.is_retryable_error(cv.ComfyValidationError("bad graph")) is False
    assert cv.is_retryable_error(cv.ComfyAuthError("401")) is False
    assert cv.is_retryable_error(cv.ComfyAccessError("cf sign-in page")) is True


@pytest.mark.parametrize("code,retryable", [(429, True), (503, True), (408, True), (401, False), (400, False)])
def test_http_status_classification(code, retryable):
    err = urllib.error.HTTPError("u", code, "m", {}, None)
    assert cv.is_retryable_error(err) is retryable


def test_local_failures_are_not_retryable():
    assert cv.is_retryable_error(FileNotFoundError("img")) is False
    assert cv.is_retryable_error(ValueError("bad")) is False
    assert cv.is_retryable_error(TimeoutError("slow")) is True
