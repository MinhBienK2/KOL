"""HTTP API tests for the supervisor dashboard (FastAPI app built on a synthetic run tree)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.server import create_app
from pipeline import telemetry as telemetry_module

RUN_ID = "fashion_apparel/campaign_demo"
LEGACY_ID = "campaign_legacy"


@pytest.fixture()
def client(run_tree: dict) -> TestClient:
    return TestClient(create_app(run_tree["base_dir"]))


def test_health_reports_base_dir_and_run_count(client: TestClient, run_tree: dict):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["runs"] == 2
    assert Path(payload["base_dir"]).resolve() == run_tree["base_dir"].resolve()


def test_runs_listing_includes_both_layouts(client: TestClient):
    response = client.get("/api/runs")
    assert response.status_code == 200
    run_ids = {item["run_id"] for item in response.json()["runs"]}
    assert run_ids == {RUN_ID, LEGACY_ID}


def test_run_view_exposes_stages_prompts_and_publish_log(client: TestClient):
    response = client.get(f"/api/runs/{RUN_ID}")
    assert response.status_code == 200
    view = response.json()

    assert len(view["stages"]) == 8
    assert view["prompts"][0]["model"] == "MiniMax-Hailuo-2.3"
    assert "Framing: [WIDE_SHOT]" in view["prompts"][0]["prompt"]
    assert view["publish_log"]["title"]
    assert view["render_report"]["verification_gates"][0]["passed"] is True
    assert view["events"]["last_seq"] > 0


def test_unknown_run_returns_404(client: TestClient):
    assert client.get("/api/runs/nope/missing").status_code == 404


def test_artifact_endpoint_returns_parsed_json(client: TestClient):
    response = client.get(f"/api/runs/{RUN_ID}/artifact?name=scene_plan.json")
    assert response.status_code == 200
    assert response.json()["shots"][0]["shot_id"] == "shot_01"

    missing = client.get(f"/api/runs/{RUN_ID}/artifact?name=does_not_exist.json")
    assert missing.status_code == 404


def test_file_endpoint_serves_images_and_videos(client: TestClient):
    image = client.get(f"/api/runs/{RUN_ID}/file?path=artifacts/storyboard_contact_sheet.jpg")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/jpeg")
    assert len(image.content) > 0

    video = client.get(f"/api/runs/{RUN_ID}/file?path=media/raw_clips/shot_01.mp4")
    assert video.status_code == 200
    assert video.headers["content-type"].startswith("video/mp4")


def test_file_endpoint_supports_range_requests(client: TestClient):
    response = client.get(
        f"/api/runs/{RUN_ID}/file?path=media/raw_clips/shot_01.mp4",
        headers={"Range": "bytes=0-99"},
    )
    assert response.status_code == 206
    assert len(response.content) == 100
    assert response.headers["content-range"].startswith("bytes 0-99/")


def test_file_endpoint_rejects_traversal_and_missing_files(client: TestClient):
    escape = client.get(f"/api/runs/{RUN_ID}/file?path=../../../../etc/passwd")
    assert escape.status_code == 403

    missing = client.get(f"/api/runs/{RUN_ID}/file?path=artifacts/nope.json")
    assert missing.status_code == 404


def test_events_endpoint_honours_since(client: TestClient, run_tree: dict, tmp_path: Path):
    root = run_tree["workspace_root"]
    recorder = telemetry_module.RunTelemetry(
        "campaign_demo",
        "fashion_apparel",
        telemetry_dir=root / telemetry_module.TELEMETRY_DIRNAME,
        base_dir=root,
    )
    with telemetry_module.use_recorder(recorder):
        recorder.start_run(note="live-smoke")
        recorder.start_stage(6, message="audio")
        recorder.stage_progress(6, 1, 2, unit="shots", label="shot_01")

    first = client.get(f"/api/runs/{RUN_ID}/events?since=0&limit=500").json()
    assert first["events"], "events must be readable"
    assert first["last_seq"] == first["events"][-1]["seq"]
    assert any(event["type"] == "stage_progress" for event in first["events"])
    assert any(event.get("text") == "audio" for event in first["events"])

    tail = client.get(f"/api/runs/{RUN_ID}/events?since={first['last_seq']}").json()
    assert tail["events"] == []

    only_warnings = client.get(f"/api/runs/{RUN_ID}/events?since=0&limit=500&levels=warning").json()
    assert all((event.get("level") or "") == "warning" for event in only_warnings["events"])


def test_view_model_covers_legacy_run(client: TestClient):
    response = client.get(f"/api/runs/{LEGACY_ID}")
    assert response.status_code == 200
    view = response.json()
    assert view["run"]["source"] == "artifacts"
    assert view["prompts"][0]["prompt"].startswith("Generate a [9:16]")


def test_index_serves_dashboard_ui(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert json.dumps("api/runs")[1:-1] in response.text
