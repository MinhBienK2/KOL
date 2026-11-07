"""Tests for pipeline.stage_reviewer and tools.review_stage."""

import json
from pathlib import Path
import pytest

from pipeline.schemas import ScriptArtifact, ScriptBeat
from pipeline.stage_reviewer import (
    PASSING_SCORE_THRESHOLD,
    MAX_REVIEW_ITERATIONS,
    review_script,
    review_storyboard,
    review_keyframes,
    record_stage_review,
    load_review_history,
)


def test_review_script_passes_valid_script():
    script_data = {
        "campaign_id": "test_camp",
        "product_name": "Test Product",
        "target_duration": 15.0,
        "beats": [
            {
                "scene_id": "shot_01_hook",
                "beat_type": "hook",
                "spoken_text": "Bạn đang tìm giải pháp tối ưu cho công việc?",
                "on_screen_text": "GIẢI PHÁP TỐI ƯU",
                "visual_cue": "KOL Mai Ly nhìn thẳng camera",
                "visual_cue_en": "KOL Mai Ly looks directly at camera in bright studio",
                "estimated_duration": 3.0,
            },
            {
                "scene_id": "shot_02_pain",
                "beat_type": "pain",
                "spoken_text": "Bàn làm việc lộn xộn khiến bạn mất tập trung.",
                "on_screen_text": "MẤT TẬP TRUNG",
                "visual_cue": "Góc quay cận cảnh bàn làm việc bừa bộn",
                "visual_cue_en": "Close up shot of messy desk with tangled cables",
                "estimated_duration": 3.0,
            },
            {
                "scene_id": "shot_03_solution",
                "beat_type": "solution",
                "spoken_text": "Đã có giải pháp gọn gàng và tiện lợi.",
                "on_screen_text": "GỌN GÀNG TIỆN LỢI",
                "visual_cue": "KOL giới thiệu sản phẩm thanh lịch",
                "visual_cue_en": "KOL presents the sleek product on a clean desk",
                "estimated_duration": 4.0,
            },
            {
                "scene_id": "shot_04_cta",
                "beat_type": "cta",
                "spoken_text": "Xem ngay chi tiết ở link bên dưới.",
                "on_screen_text": "XEM CHI TIẾT",
                "visual_cue": "KOL mỉm cười chỉ tay xuống",
                "visual_cue_en": "KOL smiles and points toward the link below",
                "estimated_duration": 3.0,
            },
        ],
    }

    res = review_script(script_data, brief={"offers": []})
    assert res.passed is True
    assert res.score >= PASSING_SCORE_THRESHOLD
    assert res.status == "approved"
    assert len(res.problems) == 0


def test_review_script_fails_on_banned_claim_and_missing_hook():
    invalid_script = {
        "campaign_id": "test_camp",
        "product_name": "Test Product",
        "target_duration": 15.0,
        "beats": [
            {
                "scene_id": "shot_01_intro",
                "beat_type": "intro",  # Missing hook
                "spoken_text": "Cam kết giảm giá 50% và bảo hành trọn đời!",
                "on_screen_text": "GIẢM GIÁ",
                "visual_cue": "Cảnh quay",
                "visual_cue_en": "Short scene",
                "estimated_duration": 3.0,
            },
            {
                "scene_id": "shot_02_cta",
                "beat_type": "cta",
                "spoken_text": "Mua ngay đi",
                "on_screen_text": "MUA NGAY",
                "visual_cue": "CTA",
                "visual_cue_en": "Call to action",
                "estimated_duration": 3.0,
            },
        ],
    }

    res = review_script(invalid_script, brief={"offers": []})
    assert res.passed is False
    assert res.status == "needs_revision"
    assert any("Hook" in p for p in res.problems)
    assert any("giảm giá" in p or "bảo hành" in p for p in res.problems)


def test_review_history_iteration_limit(tmp_path):
    art_dir = tmp_path / "artifacts"
    art_dir.mkdir()

    # Iteration 1
    res1 = review_script(
        {"campaign_id": "c1", "product_name": "P", "target_duration": 10, "beats": []},
        brief={},
    )
    hist, can_retry = record_stage_review(art_dir, res1)
    assert res1.iteration == 1
    assert can_retry is True

    # Iteration 2
    res2 = review_script(
        {"campaign_id": "c1", "product_name": "P", "target_duration": 10, "beats": []},
        brief={},
    )
    hist, can_retry = record_stage_review(art_dir, res2)
    assert res2.iteration == 2
    assert can_retry is True

    # Iteration 3
    res3 = review_script(
        {"campaign_id": "c1", "product_name": "P", "target_duration": 10, "beats": []},
        brief={},
    )
    hist, can_retry = record_stage_review(art_dir, res3)
    assert res3.iteration == 3
    assert can_retry is False  # Hit max iterations limit
