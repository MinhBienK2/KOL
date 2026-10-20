import json
from pathlib import Path
from pipeline.briefing import create_product_brief
from pipeline.schemas import BriefArtifact


def test_create_product_brief(tmp_path: Path):
    brief = create_product_brief(
        campaign_id="test_campaign",
        product_name="Test Product",
        output_dir=tmp_path,
    )
    assert brief.campaign_id == "test_campaign"
    assert brief.product_name == "Test Product"
    assert len(brief.pain_points) == 3
    assert len(brief.usps) == 3
    assert brief.presenter.character_tag == "[KOL_MAIN]"
    assert brief.presenter.name == "Mai Ly"

    # Verify file written
    out_file = tmp_path / "brief.json"
    assert out_file.exists()
    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    loaded = BriefArtifact.model_validate(data)
    assert loaded.campaign_id == "test_campaign"
