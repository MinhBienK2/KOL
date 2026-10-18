"""Shared fixtures for dashboard tests: synthetic run trees built from real artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _fake_mp4(path: Path, size: int = 4096) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x11" * max(0, size - 16))
    return path


def _fake_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"\x22" * 64)
    return path


def _fake_audio(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + b"\x00" * 60)
    return path


STORY_PROMPT = (
    "Framing: [WIDE_SHOT] with [24mm_wide] lens. Camera angle: [low_angle_15deg]. "
    "Commercial fashion and lifestyle video featuring [KOL_MA] Minh Anh. "
    "Wardrobe and styling: Wearing the featured fashion apparel item directly. "
    "Visual acting action: [KOL_MA] walks toward camera. "
    "Environment: Paris cafe terrace in soft daylight."
)


def build_workspace_run(base_dir: Path, project_id: str = "campaign_demo", topic: str = "fashion_apparel") -> Path:
    """Create a workspace-layout run with canonical artifacts + telemetry on disk."""
    from pipeline import telemetry as telemetry_module

    root = base_dir / "projects" / topic / project_id
    artifacts = root / "artifacts"
    keyframes = root / "keyframes"
    media = root / "media"
    artifacts.mkdir(parents=True, exist_ok=True)

    _write_json(
        artifacts / "brief.json",
        {
            "campaign_id": project_id,
            "product_name": "Đầm xòe cherry",
            "target_persona": "Phụ nữ 22-30 yêu thời trang",
            "pain_points": ["Khó chọn trang phục dự tiệc"],
            "usps": ["Form chuẩn", "Chất liệu cao cấp"],
            "visual_tone": "Editorial fashion",
            "archetype": topic,
        },
    )
    _write_json(
        artifacts / "competitor_research.json",
        {
            "campaign_id": project_id,
            "product_intel": {"title": "Đầm xòe cherry", "brand": "Local"},
            "competitor_landscape": {"saturated_angles": ["Giảm giá sốc"]},
            "viral_hook_library": [],
        },
    )
    _write_json(
        artifacts / "creative_concept.json",
        {
            "campaign_id": project_id,
            "product_name": "Đầm xòe cherry",
            "concept_options": [
                {"angle_id": "a1", "angle_archetype": "fashion_lookbook", "title": "Cherry noir"},
                {"angle_id": "a2", "angle_archetype": "general", "title": "Second option"},
                {"angle_id": "a3", "angle_archetype": "general", "title": "Third option"},
            ],
            "winning_concept": {"selected_angle_id": "a1", "selection_rationale": "Best retention"},
        },
    )
    _write_json(
        artifacts / "script.json",
        {
            "campaign_id": project_id,
            "product_name": "Đầm xòe cherry",
            "target_duration": 24.0,
            "beats": [
                {
                    "scene_id": "scene_01",
                    "beat_type": "hook",
                    "spoken_text": "Đây là chiếc đầm khiến bạn nổi bật.",
                    "on_screen_text": "ĐẦM XÒE CHERRY",
                    "visual_cue": "[KOL_MA] walks toward camera",
                    "estimated_duration": 6.0,
                }
            ],
        },
    )
    _write_json(
        artifacts / "scene_plan.json",
        {
            "campaign_id": project_id,
            "shots": [
                {
                    "shot_id": "shot_01",
                    "scene_id": "scene_01",
                    "shot_type": "WS • Hook",
                    "angle": "low_angle_15deg",
                    "camera_motion": "truck",
                    "lighting": "editorial_fashion",
                    "style_constraints": "Fashion commercial aesthetic",
                    "scene_description": "[KOL_MA] walks toward camera",
                    "prompt_6part": STORY_PROMPT,
                    "estimated_duration": 6.0,
                    "color_temp_kelvin": 5600,
                    "is_hero_moment": True,
                }
            ],
            "slideshow_risk": {"average_score": 1.2, "verdict": "PASSED", "passed": True},
            "storyboard_contact_sheet": str(artifacts / "storyboard_contact_sheet.jpg"),
        },
    )
    _fake_image(artifacts / "storyboard_contact_sheet.jpg")
    _fake_image(keyframes / "shot_01_clean.jpg")
    _fake_mp4(media / "raw_clips" / "shot_01.mp4")
    _fake_mp4(media / "synced_clips" / "shot_01.mp4")
    _fake_audio(media / "audio" / "voice_shot_01.wav")
    master = _fake_mp4(root / f"final_master_{project_id}.mp4", size=8192)
    thumbnail = _fake_image(root / f"thumbnail_{project_id}.jpg")
    _write_json(
        artifacts / "asset_manifest.json",
        {
            "campaign_id": project_id,
            "keyframes": [
                {
                    "shot_id": "shot_01",
                    "image_path": "assets/characters/kol_main/portrait.png",
                    "cleaned_image_path": str(keyframes / "shot_01_clean.jpg"),
                    "watermark_removed": True,
                    "width": 1080,
                    "height": 1920,
                }
            ],
            "audio_stems": [str(media / "audio" / "voice_shot_01.wav")],
            "raw_video_clips": [str(media / "raw_clips" / "shot_01.mp4")],
            "synced_video_clips": [str(media / "synced_clips" / "shot_01.mp4")],
        },
    )
    _write_json(
        artifacts / "edit_decisions.json",
        {
            "campaign_id": project_id,
            "timeline_clips": [str(media / "synced_clips" / "shot_01.mp4")],
            "audio_tracks": [
                {"track_id": "bgm", "type": "bgm", "file_path": "assets/audio/music/commercial_bgm.mp3", "ducking_attenuation_db": -24.0}
            ],
            "captions": [{"text": "ĐẦM XÒE CHERRY", "start": 0.0, "end": 2.0}],
            "output_master_path": str(master),
        },
    )
    _write_json(
        artifacts / "render_report.json",
        {
            "campaign_id": project_id,
            "master_video_path": str(master),
            "file_size_bytes": master.stat().st_size,
            "duration_seconds": 24.0,
            "video_codec": "h264",
            "audio_codec": "aac",
            "width": 1080,
            "height": 1920,
            "aspect_ratio": "9:16",
            "verification_gates": [
                {"gate_name": "technical_integrity_gate", "passed": True, "details": {"width": 1080}, "error_message": None}
            ],
            "overall_status": "PASSED",
        },
    )
    _write_json(
        artifacts / "publish_log.json",
        {
            "campaign_id": project_id,
            "product_name": "Đầm xòe cherry",
            "master_video_path": str(master),
            "thumbnail_path": str(thumbnail),
            "title": "Đầm xòe cherry cho mọi buổi tiệc",
            "description": "Form chuẩn, chất liệu cao cấp.",
            "hashtags": ["#DamXoeCherry"],
            "published_at": "2026-10-18T00:00:00Z",
        },
    )

    # Real telemetry producer (no hand-written state.json).
    recorder = telemetry_module.RunTelemetry(
        project_id,
        topic,
        telemetry_dir=root / telemetry_module.TELEMETRY_DIRNAME,
        base_dir=root,
    )
    with telemetry_module.use_recorder(recorder):
        recorder.start_run(
            campaign_id=project_id,
            product_name="Đầm xòe cherry",
            archetype=topic,
            video_mode="api",
            resume_from_stage=1,
            workspace_root=str(root),
            artifacts_dir=str(artifacts),
            master_video_path=str(master),
            thumbnail_path=str(thumbnail),
        )
        for stage in range(1, 8):
            recorder.start_stage(stage, message=f"Stage {stage} running")
            recorder.stage_progress(stage, 1, 1, label=f"stage {stage} item")
            recorder.complete_stage(stage, message=f"Stage {stage} done")
        recorder.register_artifact(artifacts / "scene_plan.json", stage=3)
        recorder.register_artifact(master, stage=7)
        recorder.record_prompt(
            "shot_01",
            STORY_PROMPT,
            stage=5,
            mode="I2V",
            model="MiniMax-Hailuo-2.3",
            aspect_ratio="9:16",
            duration_requested=6,
            first_frame=str(keyframes / "shot_01_clean.jpg"),
            task_id="task-123",
            attempt_increment=1,
            output_rel_path="media/raw_clips/shot_01.mp4",
            size_bytes=4096,
        )
        recorder.record_api_call(
            "minimax.submit_video",
            endpoint="https://example.test/v1/media/video",
            request={"model": "MiniMax-Hailuo-2.3", "api_key": "sk-should-be-redacted"},
            response={"task_id": "task-123"},
            status=200,
            ok=True,
            stage=5,
            shot_id="shot_01",
        )
        recorder.start_stage(8, message="Verification")
        recorder.stage_progress(8, 1, 1, label="technical_integrity_gate")
        recorder.complete_stage(8, message="Overall: PASSED")
        recorder.finish_run(True, "Pipeline completed", elapsed_seconds=42.0)
    return root


def build_legacy_run(base_dir: Path, project_id: str = "campaign_legacy") -> Path:
    """Create a legacy artifacts-only run (no telemetry) with a partial pipeline."""
    artifacts = base_dir / "artifacts" / project_id
    artifacts.mkdir(parents=True, exist_ok=True)
    _write_json(
        artifacts / "brief.json",
        {"campaign_id": project_id, "product_name": "Ly giữ nhiệt", "target_persona": "Dân văn phòng", "pain_points": [], "usps": [], "visual_tone": "Studio"},
    )
    _write_json(
        artifacts / "script.json",
        {
            "campaign_id": project_id,
            "product_name": "Ly giữ nhiệt",
            "target_duration": 20.0,
            "beats": [
                {
                    "scene_id": "scene_01",
                    "beat_type": "hook",
                    "spoken_text": "Cà phê nguội?",
                    "on_screen_text": "GIỮ NHIỆT 24H",
                    "visual_cue": "macro shot",
                    "estimated_duration": 5.0,
                }
            ],
        },
    )
    _write_json(
        artifacts / "scene_plan.json",
        {
            "campaign_id": project_id,
            "shots": [
                {
                    "shot_id": "shot_01",
                    "scene_id": "scene_01",
                    "shot_type": "ECU • Hook",
                    "angle": "eye_level",
                    "camera_motion": "zoom_in",
                    "lighting": "studio_3point",
                    "style_constraints": "Cinematic photorealistic",
                    "scene_description": "Macro of the mug",
                    "prompt_6part": "Generate a [9:16] aspect ratio cinematic commercial shot. Character: [KOL_MA].",
                    "estimated_duration": 5.0,
                }
            ],
            "slideshow_risk": {"average_score": 0.8, "verdict": "PASSED"},
        },
    )
    return artifacts


@pytest.fixture()
def run_tree(tmp_path: Path) -> dict:
    """A temp base_dir holding one telemetry-backed workspace run and one legacy run."""
    base_dir = tmp_path / "output"
    base_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = build_workspace_run(base_dir)
    legacy_root = build_legacy_run(base_dir)
    return {
        "base_dir": base_dir,
        "workspace_root": workspace_root,
        "legacy_root": legacy_root,
        "workspace_run_id": "fashion_apparel/campaign_demo",
        "legacy_run_id": "campaign_legacy",
    }
