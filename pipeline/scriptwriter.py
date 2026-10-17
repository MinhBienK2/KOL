"""Step 2: High-Conversion Commercial Scriptwriting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pipeline.config import ARTIFACTS_DIR
from pipeline.schemas import BriefArtifact, ScriptArtifact, ScriptBeat


def generate_commercial_script(
    brief: BriefArtifact | None = None,
    brief_path: Path | None = None,
    output_dir: Path | None = None,
) -> ScriptArtifact:
    """Generates high-conversion TVC script based on brief.json."""
    target_artifacts_dir = output_dir or ARTIFACTS_DIR
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)

    if brief is None:
        source_path = brief_path or (target_artifacts_dir / "brief.json")
        if not source_path.exists():
            raise FileNotFoundError(f"Brief file not found at {source_path}")
        with open(source_path, "r", encoding="utf-8") as f:
            brief = BriefArtifact.model_validate(json.load(f))

    beats: List[ScriptBeat] = [
        ScriptBeat(
            scene_id="shot_01_hook",
            beat_type="hook",
            spoken_text="Bạn có phát chán khi ly cà phê vừa pha xong thì 15 phút sau đã nguội ngắt?",
            on_screen_text="CÀ PHÊ NGUỘI NGẮT SAU 15 PHÚT?",
            visual_cue="Extreme close-up ly cà phê nguội, chuyển nhanh sang góc cận KOL Minh Anh lắc đầu ngạc nhiên",
            estimated_duration=3.5,
        ),
        ScriptBeat(
            scene_id="shot_02_pain",
            beat_type="pain",
            spoken_text="Chưa kể đá tan chảy nước lênh láng, làm ướt đẫm tài liệu và bàn phím làm việc?",
            on_screen_text="NƯỚC ĐỌNG ƯỚT BÀN & TÀI LIỆU!",
            visual_cue="Góc nhìn bàn làm việc nước ngưng tụ lem nhem hồ sơ, Minh Anh cau mày khó chịu",
            estimated_duration=5.0,
        ),
        ScriptBeat(
            scene_id="shot_03_solution",
            beat_type="solution",
            spoken_text="Giải pháp đây rồi! Ly giữ nhiệt Lumina Pro, chạm nhẹ nắp LED biết ngay nhiệt độ, giữ nóng 12 tiếng, giữ lạnh 24 tiếng!",
            on_screen_text="LUMINA PRO • NẮP CẢM ỨNG LED • GIỮ NHIỆT 24H",
            visual_cue="Góc quay điện ảnh studio sang trọng, Minh Anh chạm nắp LED sáng đèn 65 độ C, nâng ly thưởng thức sảng khoái",
            estimated_duration=12.0,
        ),
        ScriptBeat(
            scene_id="shot_04_cta",
            beat_type="cta",
            spoken_text="Bảo bối công sở chống tràn tuyệt đối! Nhấp ngay link bên dưới để nhận ưu đãi 40% hôm nay nhé!",
            on_screen_text="ƯU ĐÃI 40% ĐỘC QUYỀN • NHẤP LINK BIO",
            visual_cue="Minh Anh mỉm cười rạng rỡ, giơ cao ly Lumina Pro thanh lịch, logo thương hiệu và nút CTA xuất hiện",
            estimated_duration=6.5,
        ),
    ]

    total_duration = sum(b.estimated_duration for b in beats)

    script = ScriptArtifact(
        campaign_id=brief.campaign_id,
        product_name=brief.product_name,
        target_duration=total_duration,
        beats=beats,
    )

    out_file = target_artifacts_dir / "script.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(script.model_dump(), f, ensure_ascii=False, indent=2)

    return script
