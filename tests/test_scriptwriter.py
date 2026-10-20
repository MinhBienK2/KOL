from pathlib import Path
import json

from pipeline.briefing import create_product_brief
from pipeline.scriptwriter import generate_commercial_script
from pipeline.schemas import ScriptArtifact


def test_generate_commercial_script(tmp_path: Path):
    brief = create_product_brief(output_dir=tmp_path)
    script = generate_commercial_script(brief=brief, output_dir=tmp_path)

    assert script.campaign_id == brief.campaign_id
    assert len(script.beats) == 4
    assert script.beats[0].beat_type == "hook"
    assert script.beats[3].beat_type == "cta"
    assert 15 <= script.target_duration <= 35
    assert all(b.estimated_duration <= 6.0 for b in script.beats)

    out_file = tmp_path / "script.json"
    assert out_file.exists()
    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    loaded = ScriptArtifact.model_validate(data)
    assert len(loaded.beats) == 4
