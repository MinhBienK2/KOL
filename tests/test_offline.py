"""Guaranteed offline mode: the guard fires, and stages 5/6 run with every network path exploding."""

from __future__ import annotations

import json
import socket
import subprocess
import urllib.request
from pathlib import Path

import pytest

from pipeline import audio_lip_sync, researcher, telemetry, video_engine
from pipeline.archetypes import ProductArchetype
from pipeline.audio_lip_sync import (
    probe_audio_duration,
    produce_all_audio_and_lip_sync,
    synthesize_voice_stem,
)
from pipeline.briefing import create_product_brief
from pipeline.identity_keyframe import generate_clean_keyframes
from pipeline.offline import (
    OfflineNetworkError,
    guard_network,
    guarded_urlopen,
    is_offline,
    offline_mode,
)
from pipeline.scriptwriter import generate_commercial_script
from pipeline.storyboard import generate_scene_plan
from pipeline.video_engine import (
    is_placeholder_clip,
    render_all_video_clips,
    render_single_video_clip,
    resolve_video_mode,
)
from pipeline.verification import verify_prompt_ledger_gate
from pipeline.workspace import ProjectWorkspace
from tools import dramaclaw_shot_builder, generate_video


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("KOL_OFFLINE", raising=False)
    previous = telemetry.current()
    telemetry.use(None)
    yield
    telemetry.use(previous)


def _boom(*args, **kwargs):
    raise AssertionError("NETWORK ACCESS ATTEMPTED")


@pytest.fixture
def network_explodes(monkeypatch):
    """Every way out of the process raises: urllib, the low-level video/TTS/LLM helpers, sockets."""
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(urllib.request, "urlretrieve", _boom)
    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    for module, names in (
        (generate_video, ("upload_first_frame", "submit_video_job", "poll_and_download_video")),
        (video_engine, ("upload_first_frame", "submit_video_job", "poll_and_download_video")),
        (researcher, ("call_llm", "resolve_affiliate_url")),
        (dramaclaw_shot_builder, ("upload_reference_image",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, _boom)


def _video_stream(path: str) -> dict:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration:format_tags=comment",
            "-of", "json", path,
        ]
    )
    return json.loads(out)


# ----------------------------------------------------------------------------- the guard


def test_is_offline_reads_env(monkeypatch):
    assert not is_offline()
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("KOL_OFFLINE", value)
        assert is_offline()
    monkeypatch.setenv("KOL_OFFLINE", "0")
    assert not is_offline()


def test_offline_mode_context_overrides_env_and_restores(monkeypatch):
    with offline_mode(True):
        assert is_offline()
        with offline_mode(False):
            assert not is_offline()
        assert is_offline()
    assert not is_offline()
    monkeypatch.setenv("KOL_OFFLINE", "1")
    with offline_mode(False):
        assert not is_offline()


def test_guard_raises_clear_error_when_offline(monkeypatch):
    monkeypatch.setenv("KOL_OFFLINE", "1")
    with pytest.raises(OfflineNetworkError, match="KOL_OFFLINE"):
        guard_network("minimax.submit_video", "https://example.invalid/x")
    monkeypatch.delenv("KOL_OFFLINE")
    guard_network("fine")


@pytest.mark.parametrize(
    "call",
    [
        lambda tmp: generate_video.upload_first_frame("assets/characters/kol_main/portrait.png"),
        lambda tmp: generate_video.submit_video_job("prompt"),
        lambda tmp: generate_video.poll_and_download_video("task", tmp / "x.mp4"),
        lambda tmp: researcher.call_llm("system", "user"),
        lambda tmp: dramaclaw_shot_builder.upload_reference_image("assets/characters/kol_main/portrait.png"),
        lambda tmp: guarded_urlopen(urllib.request.Request("http://127.0.0.1:9/"), operation="t"),
        lambda tmp: synthesize_voice_stem("xin chào", tmp / "v.wav", mode="api"),
        lambda tmp: render_single_video_clip("shot_01", "p", tmp / "c.mp4", max_retries=3, initial_retry_delay=0),
        lambda tmp: render_all_video_clips(mode="api"),
    ],
)
def test_every_paid_call_site_is_guarded(tmp_path, monkeypatch, call):
    monkeypatch.setenv("KOL_OFFLINE", "1")
    # If the guard were missing the call would reach the (exploding) network instead.
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(urllib.request, "urlretrieve", _boom)
    with pytest.raises(OfflineNetworkError):
        call(tmp_path)


def test_generate_first_frame_offline_uses_local_reference_not_network(tmp_path, monkeypatch, network_explodes):
    monkeypatch.setenv("KOL_OFFLINE", "1")
    out = tmp_path / "frame.png"
    assert dramaclaw_shot_builder.generate_first_frame("sips tea", out, aspect_ratio="9:16")
    assert out.exists()


def test_video_mode_resolution(monkeypatch):
    assert resolve_video_mode("api") == "api"
    assert resolve_video_mode("diffusion") == "api"
    assert resolve_video_mode("ffmpeg") == "ffmpeg"
    assert resolve_video_mode("auto") == "api"
    monkeypatch.setenv("KOL_OFFLINE", "1")
    assert resolve_video_mode("auto") == "ffmpeg"
    with pytest.raises(ValueError):
        resolve_video_mode("bogus")


# ----------------------------------------------------------------------------- researcher


def test_research_pipeline_offline_uses_deterministic_fallbacks(tmp_path, monkeypatch, network_explodes):
    monkeypatch.setenv("KOL_OFFLINE", "1")
    research, concepts = researcher.run_research_pipeline(
        "https://example.invalid/p Cốc giữ nhiệt thông minh",
        campaign_id="offline_research",
        archetype=ProductArchetype.TECH_GADGETS,
        output_dir=tmp_path,
        use_llm=True,  # explicitly requested, but offline must win
    )
    assert research.product_intel.title
    assert concepts.concept_options


# ----------------------------------------------------------------------------- stages 4-6


def _build_workspace(tmp_path: Path):
    ws = ProjectWorkspace(topic=ProductArchetype.FASHION_APPAREL, project_id="offline_run", base_dir=tmp_path)
    ws.ensure_dirs()
    brief = create_product_brief(product_name="Váy Satin Lụa Pháp", workspace=ws)
    script = generate_commercial_script(brief=brief, workspace=ws)
    plan = generate_scene_plan(script=script, workspace=ws)
    return ws, script, plan


def test_stage5_ffmpeg_and_stage6_offline_never_touch_network(tmp_path, monkeypatch, network_explodes):
    monkeypatch.setenv("KOL_OFFLINE", "1")
    ws, script, plan = _build_workspace(tmp_path)
    recorder = telemetry.RunTelemetry(
        "offline_run", "fashion_apparel", telemetry_dir=tmp_path / "telemetry", base_dir=tmp_path
    )

    with telemetry.use_recorder(recorder):
        # Stage 4 is local already; it must not need the network either.
        generate_clean_keyframes(scene_plan=plan, workspace=ws)

        clips = render_all_video_clips(mode="ffmpeg", workspace=ws)
        assert len(clips) == len(plan.shots)
        for clip, shot in zip(clips, plan.shots):
            info = _video_stream(clip)["streams"][0]
            assert (info["width"], info["height"]) == (1080, 1920)
            assert float(info["duration"]) == pytest.approx(shot.estimated_duration, abs=0.1)
            assert is_placeholder_clip(clip)
            assert "KOL_PLACEHOLDER" in _video_stream(clip)["format"]["tags"]["comment"]

        stems, synced = produce_all_audio_and_lip_sync(workspace=ws)  # offline default from env
        assert len(stems) == len(script.beats)
        assert len(synced) == len(clips)
        for stem in stems:
            assert Path(stem).exists()
            assert probe_audio_duration(stem) > 1.0

    state = recorder.snapshot()
    ledger = state["prompts"]
    assert ledger and all(p["mode"] == "LOCAL_FFMPEG" and p["placeholder"] is True for p in ledger.values())
    assert all("minimax" not in c.get("name", "") for c in state.get("api_calls", []))
    events = telemetry.read_events(recorder.events_path)
    tts_items = [
        e["payload"]["item"]
        for e in events
        if e.get("type") == "stage_progress" and "stem" in ((e.get("payload") or {}).get("item") or {})
    ]
    assert tts_items, "stage 6 emitted no TTS progress items"
    assert all(item["placeholder"] and item["tts_fallback"] for item in tts_items)

    # Lip-sync items reuse the TTS item's id; they must repeat the flag or it is overwritten.
    sync_items = [
        e["payload"]["item"]
        for e in events
        if e.get("type") == "stage_progress" and (e.get("payload") or {}).get("item", {}).get("status") == "lip_sync_aligned"
    ]
    assert sync_items and all(i["tts_fallback"] and i["placeholder_video"] and i["placeholder_audio"] for i in sync_items)
    final_items = {i["id"]: i for i in next(st for st in state["stages"] if st["stage"] == 6)["items"]}
    assert final_items and all(i.get("tts_fallback") for i in final_items.values())

    # The Prompt Ledger keeps the placeholder video mode AND now carries tts_fallback + the prompt.
    assert all(p["tts_fallback"] is True and p["mode"] == "LOCAL_FFMPEG" and p["prompt"] for p in ledger.values())
    assert all(p["stage"] == 5 for p in ledger.values())
    gate = verify_prompt_ledger_gate(ledger)
    assert not gate.passed
    assert all(
        "tts_fallback" in reasons and "mode=LOCAL_FFMPEG" in reasons
        for reasons in gate.details["flagged_shots"].values()
    )


def test_ffmpeg_mode_works_without_kol_offline_env_and_scopes_guard(tmp_path, monkeypatch, network_explodes):
    ws, _, plan = _build_workspace(tmp_path)
    generate_clean_keyframes(scene_plan=plan, workspace=ws)
    seen = []
    real = video_engine.render_local_placeholder_clip

    def spy(*args, **kwargs):
        seen.append(is_offline())
        return real(*args, **kwargs)

    monkeypatch.setattr(video_engine, "render_local_placeholder_clip", spy)
    render_all_video_clips(mode="ffmpeg", workspace=ws)
    assert seen and all(seen)  # guard scoped on while rendering locally
    assert not is_offline()  # and restored afterwards


def test_api_mode_discards_stale_placeholder_instead_of_caching_it(tmp_path, monkeypatch):
    ws, _, plan = _build_workspace(tmp_path)
    generate_clean_keyframes(scene_plan=plan, workspace=ws)
    render_all_video_clips(mode="ffmpeg", workspace=ws)
    called = []

    def fake_single(**kwargs):
        called.append(kwargs["shot_id"])
        raise video_engine.VideoGenerationError("stop here")

    monkeypatch.setattr(video_engine, "render_single_video_clip", fake_single)
    with pytest.raises(video_engine.VideoGenerationError):
        render_all_video_clips(mode="api", workspace=ws)
    assert called, "api mode must re-render, not reuse the placeholder as a cached diffusion clip"


def test_local_tts_is_silent_not_a_tone(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_lip_sync.shutil, "which", lambda name: None)
    result = synthesize_voice_stem("Xin chào các bạn", tmp_path / "v.wav", target_duration=3.0, mode="local")
    assert result.engine == "silence" and result.placeholder
    assert result.duration == pytest.approx(3.0, abs=0.1)
    stats = subprocess.run(
        ["ffmpeg", "-i", result.path, "-af", "volumedetect", "-f", "null", "-"],
        stderr=subprocess.PIPE,
    ).stderr.decode()
    assert "max_volume: -91" in stats or "mean_volume: -91" in stats  # digital silence


def test_api_tts_failure_falls_back_to_flagged_local_stem(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_lip_sync.shutil, "which", lambda name: None)
    monkeypatch.setattr(audio_lip_sync, "guarded_urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    result = synthesize_voice_stem("Xin chào", tmp_path / "v.wav", target_duration=2.5, mode="api")
    assert result.fallback and result.placeholder and result.engine == "silence"


def test_produce_audio_api_mode_refused_while_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("KOL_OFFLINE", "1")
    ws, script, _ = _build_workspace(tmp_path)
    with pytest.raises(OfflineNetworkError):
        produce_all_audio_and_lip_sync(script=script, workspace=ws, tts_mode="api")
