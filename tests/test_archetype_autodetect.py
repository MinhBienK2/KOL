"""Offline tests: archetype keyword coverage and director-level auto-detection (round 3)."""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from pipeline.archetypes import ProductArchetype, classify_product_archetype
from pipeline.director import run_pipeline
from tools.director import main as cli_main

B = ProductArchetype.BEAUTY_SKINCARE
T = ProductArchetype.TECH_GADGETS
H = ProductArchetype.HOME_LIFESTYLE
F = ProductArchetype.FASHION_APPAREL
G = ProductArchetype.GENERAL_COMMERCIAL


@pytest.mark.parametrize(
    "text,expected",
    [
        # beauty
        ("Son kem lì lên màu chuẩn", B),
        ("Son thỏi dưỡng môi có màu", B),
        ("Phấn phủ kiềm dầu siêu mịn", B),
        ("Kem dưỡng ẩm ban đêm", B),
        ("Sữa rửa mặt dịu nhẹ cho da nhạy cảm", B),
        ("Kem chống nắng SPF50+ không bết dính", B),
        ("Mascara chuốt mi dày cong", B),
        ("Toner cân bằng da", B),
        ("Cushion che khuyết điểm", B),
        ("Nước tẩy trang micellar", B),
        # tech
        ("Tai nghe chống ồn Sonic Air Pro", T),
        ("Tai nghe bluetooth chống ồn chủ động ANC, pin 30 giờ", T),
        ("Củ sạc nhanh 65W GaN", T),
        ("Chuột không dây Logitech", T),
        ("Bàn phím cơ RGB hot-swap", T),
        ("Loa Bluetooth mini chống nước", T),
        ("Sạc dự phòng 20000mAh", T),
        ("Đồng hồ thông minh theo dõi sức khỏe", T),
        # home
        ("Nồi chiên không dầu 6L", H),
        ("Máy lọc không khí cho phòng ngủ", H),
        ("Bình giữ nhiệt Lumina 500ml", H),
        ("Nến thơm tinh dầu sả chanh", H),
        ("Chăn ga gối đệm cotton", H),
        ("Máy hút bụi cầm tay", H),
        # fashion
        ("Váy đầm xòe công sở", F),
        ("Áo khoác dù chống nắng", F),
        ("Quần jean ống rộng", F),
        ("Giày thể thao nữ", F),
        # nothing relevant
        ("Sách dạy nấu ăn", G),
    ],
)
def test_vietnamese_product_names_classify(text, expected):
    assert classify_product_archetype(text) == expected


def test_short_tokens_do_not_fire_inside_words():
    # "son" must not match inside "sonic"; "ao" must not match inside "dao"
    assert classify_product_archetype("Sonic") == G
    assert classify_product_archetype("Dao bếp") != F


@pytest.mark.parametrize(
    "text",
    [
        "Điều quan trọng là đảm bảo chất lượng, màu đậm, vậy nên rất tốt",
        "Sơn tường nội thất chống thấm",
        "Chào bạn, hãy tham khảo thêm tại cửa hàng",
    ],
)
def test_ambiguous_short_tokens_do_not_false_positive(text):
    assert classify_product_archetype(text) not in (F, B)


def test_unaccented_input_still_classifies():
    assert classify_product_archetype("ao khoac nu mua dong") == F
    assert classify_product_archetype("son kem li") == B


# ---------------------------------------------------------------- director auto-detection

STAGE_NAMES = [
    "create_product_brief", "create_product_brief_from_concept", "run_research_pipeline",
    "generate_commercial_script", "generate_scene_plan", "generate_clean_keyframes",
    "render_all_video_clips", "produce_all_audio_and_lip_sync", "compose_master_commercial",
    "run_all_verification_gates",
]

HEADPHONES = ("Tai nghe chống ồn Sonic Air Pro", "Tai nghe bluetooth chống ồn chủ động ANC, pin 30 giờ")


@pytest.fixture
def stub_stages():
    with ExitStack() as stack:
        stack.enter_context(patch("pipeline.workspace.ProjectWorkspace.check_prerequisites", return_value=[]))
        mocks = {
            n: stack.enter_context(patch(f"pipeline.director.{n}", return_value=MagicMock(overall_status="PASSED")))
            for n in STAGE_NAMES
        }
        mocks["run_research_pipeline"].return_value = (MagicMock(), MagicMock())
        mocks["generate_commercial_script"].return_value = MagicMock(beats=[MagicMock()])
        mocks["generate_scene_plan"].return_value = MagicMock(shots=[MagicMock()], slideshow_risk={})
        mocks["generate_clean_keyframes"].return_value = MagicMock(keyframes=[MagicMock()])
        mocks["render_all_video_clips"].return_value = ["clip.mp4"]
        mocks["produce_all_audio_and_lip_sync"].return_value = (["stem.wav"], ["sync.mp4"])
        yield mocks


def _cli(tmp_path, *extra):
    product, desc = HEADPHONES
    return cli_main(["--product", product, "--url", desc, "--out-dir", str(tmp_path),
                     "--video-mode", "ffmpeg", "--json", *extra])


def test_cli_autodetects_topic_before_creating_workspace(tmp_path, stub_stages, capsys):
    assert _cli(tmp_path, "--campaign", "auto1") == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["topic"] == "tech_gadgets"
    assert printed["archetype"] == "tech_gadgets"
    assert printed["archetype_source"] == "auto"
    assert (tmp_path / "projects" / "tech_gadgets" / "auto1").is_dir()
    assert not (tmp_path / "projects" / "general_commercial").exists()
    meta = json.loads((tmp_path / "projects" / "tech_gadgets" / "auto1" / "project.json").read_text("utf-8"))
    assert meta["archetype"] == "tech_gadgets"


def test_cli_explicit_topic_wins_over_detection(tmp_path, stub_stages, capsys):
    assert _cli(tmp_path, "--campaign", "exp1", "--topic", "home_lifestyle") == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["topic"] == "home_lifestyle"
    assert printed["archetype_source"] == "explicit"


def test_cli_existing_workspace_topic_is_kept(tmp_path, stub_stages, capsys):
    (tmp_path / "projects" / "home_lifestyle" / "old1").mkdir(parents=True)
    assert _cli(tmp_path, "--campaign", "old1") == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["topic"] == "home_lifestyle"
    assert printed["archetype_source"] == "workspace"


def test_cli_check_mode_reports_detected_topic_without_writing(tmp_path, capsys):
    assert _cli(tmp_path, "--campaign", "chk1", "--check") == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["topic"] == "tech_gadgets" and printed["archetype_source"] == "auto"
    assert not (tmp_path / "projects").exists()


def test_run_pipeline_autodetects_without_topic_or_workspace(tmp_path, stub_stages):
    product, desc = HEADPHONES
    result: dict = {}
    ok = run_pipeline(campaign_id="auto2", product_name=product, product_url_or_query=desc,
                      video_mode="ffmpeg", output_dir=tmp_path, result=result)
    assert ok is True
    assert (tmp_path / "projects" / "tech_gadgets" / "auto2").is_dir()
    assert result["archetype"] == "tech_gadgets" and result["archetype_source"] == "auto"
    # stage 1 must not run its own (possibly contradictory) detection
    kwargs = stub_stages["run_research_pipeline"].call_args.kwargs
    assert kwargs["archetype"] == ProductArchetype.TECH_GADGETS
    assert kwargs["auto_detect_archetype"] is False


def test_run_pipeline_explicit_general_is_not_overridden(tmp_path, stub_stages):
    product, desc = HEADPHONES
    result: dict = {}
    run_pipeline(campaign_id="exp2", product_name=product, product_url_or_query=desc, topic="general_commercial",
                 video_mode="ffmpeg", output_dir=tmp_path, result=result)
    assert (tmp_path / "projects" / "general_commercial" / "exp2").is_dir()
    assert result["archetype_source"] == "explicit"
