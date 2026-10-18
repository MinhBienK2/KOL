"""Tests for pipeline.telemetry: the frozen run-state / event-log contract.

Only consumer-visible behaviour is covered: what lands in ``state.json``, what lands in
``events.jsonl``, how the readers filter, and the fail-safe / no-op / thread-safety
guarantees the pipeline relies on. Everything is deterministic (``tmp_path`` only, no
network, no wall-clock racing).
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

from pipeline import telemetry

#: Event vocabulary frozen by docs/adr/0005-run-telemetry-and-supervisor-dashboard.md
DOCUMENTED_EVENT_TYPES = {
    "run_start",
    "run_complete",
    "run_failed",
    "stage_start",
    "stage_progress",
    "stage_message",
    "stage_complete",
    "stage_failed",
    "stage_skipped",
    "log",
    "note",
    "artifact",
    "prompt",
    "api_call",
}


@pytest.fixture(autouse=True)
def _isolated_recorder():
    """Force the process-wide recorder to ``None`` so tests never leak into each other."""
    previous = telemetry.current()
    telemetry.use(None)
    try:
        yield
    finally:
        telemetry.use(previous)


def _recorder(root: Path, project_id: str = "campaign_cherry_dress_01", topic: str = "fashion_apparel"):
    """RunTelemetry whose base_dir is ``root`` (telemetry dir is ``root/telemetry``)."""
    return telemetry.RunTelemetry(project_id, topic, telemetry_dir=root / "telemetry", base_dir=root)


def _disk_state(recorder: telemetry.RunTelemetry) -> dict:
    return json.loads(recorder.state_path.read_text(encoding="utf-8"))


def _stage(state: dict, number: int) -> dict:
    return next(entry for entry in state["stages"] if entry["stage"] == number)


def _events(recorder: telemetry.RunTelemetry) -> list:
    """Parse events.jsonl line by line (a corrupt/interleaved line raises here)."""
    return [json.loads(line) for line in recorder.events_path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------- 1. start_run


def test_start_run_persists_running_state_and_increments_run_index(tmp_path):
    """start_run writes state.json as running, bumps run_index, and keeps first_started_at."""
    recorder = _recorder(tmp_path)
    recorder.start_run(campaign_id="campaign_cherry_dress_01", product_name="Cherry Dress")

    assert recorder.state_path.exists()
    state = _disk_state(recorder)
    assert state["schema_version"] == telemetry.SCHEMA_VERSION
    assert state["status"] == telemetry.RUN_RUNNING
    assert state["run_index"] == 1
    assert state["first_started_at"]
    assert state["first_started_at"] == state["last_started_at"]
    assert state["finished_at"] is None and state["elapsed_seconds"] is None
    assert state["current_stage"] is None
    assert state["run_meta"]["campaign_id"] == "campaign_cherry_dress_01"
    assert state["run_meta"]["product_name"] == "Cherry Dress"
    assert len(state["stages"]) == telemetry.TOTAL_STAGES == 8
    assert [entry["status"] for entry in state["stages"]] == [telemetry.STAGE_PENDING] * 8
    assert _events(recorder)[-1]["type"] == "run_start"

    first_started_at = state["first_started_at"]
    recorder.start_run(campaign_id="campaign_cherry_dress_01")

    state = _disk_state(recorder)
    assert state["run_index"] == 2
    assert state["first_started_at"] == first_started_at
    assert state["elapsed_seconds"] is None
    assert [event["seq"] for event in _events(recorder)] == [1, 2]


# ------------------------------------------------------------- 2. stage transitions/progress


def test_stage_lifecycle_transitions_reach_snapshot_and_disk(tmp_path):
    """start_stage -> stage_progress -> complete_stage is visible in snapshot() and state.json."""
    recorder = _recorder(tmp_path)
    recorder.start_run()

    recorder.start_stage(3, "Staging storyboard", total=4)

    stage = _stage(_disk_state(recorder), 3)
    assert stage["status"] == telemetry.STAGE_RUNNING
    assert stage["started_at"] and stage["finished_at"] is None
    assert stage["progress"] == {"current": 0, "total": 4, "percent": 0.0, "unit": None, "label": None}
    assert stage["key"] == "storyboard_staging"
    assert _disk_state(recorder)["current_stage"] == 3
    assert _stage(recorder.snapshot(), 3)["message"] == "Staging storyboard"

    recorder.stage_progress(3, 1, label="shot_01", unit="shots", message="Staging shot 1/4")

    stage = _stage(_disk_state(recorder), 3)
    assert stage["status"] == telemetry.STAGE_RUNNING
    assert stage["progress"] == {"current": 1, "total": 4, "percent": 25.0, "unit": "shots", "label": "shot_01"}
    assert stage["message"] == "Staging shot 1/4"
    assert stage["finished_at"] is None

    recorder.complete_stage(3)

    on_disk = _disk_state(recorder)
    stage = _stage(on_disk, 3)
    assert stage["status"] == telemetry.STAGE_COMPLETED
    assert stage["finished_at"] and stage["duration_seconds"] is not None and stage["duration_seconds"] >= 0
    assert stage["progress"] == {"current": 4, "total": 4, "percent": 100.0, "unit": "shots", "label": "shot_01"}
    assert stage["error"] is None
    assert on_disk["current_stage"] is None
    assert _stage(on_disk, 4)["status"] == telemetry.STAGE_PENDING


def test_log_lines_reach_event_log_and_flush_syncs_state(tmp_path):
    """Every log line is appended to events.jsonl; flush() reconciles the throttled state.json."""
    recorder = _recorder(tmp_path)
    recorder.start_run()
    for index in range(5):
        recorder.log(f"line {index}")

    assert [event["text"] for event in _events(recorder) if event["type"] == "log"] == [f"line {index}" for index in range(5)]

    recorder.flush()
    state = _disk_state(recorder)
    assert state["counters"]["events"] == 6
    assert state["last_event"]["seq"] == 6 and state["last_event"]["text"] == "line 4"
    assert state["status"] == telemetry.RUN_RUNNING


def test_progress_percent_math_and_items(tmp_path):
    """percent is None for a missing/zero total, inherits a previous total, and items dedup by id."""
    recorder = _recorder(tmp_path)
    recorder.start_stage(5)

    recorder.stage_progress(5, 3)
    assert _stage(recorder.snapshot(), 5)["progress"] == {
        "current": 3,
        "total": None,
        "percent": None,
        "unit": None,
        "label": None,
    }

    recorder.stage_progress(5, 3, 0)
    progress = _stage(recorder.snapshot(), 5)["progress"]
    assert progress["total"] is None and progress["percent"] is None and progress["current"] == 3

    recorder.stage_progress(5, 3, 8)
    assert _stage(recorder.snapshot(), 5)["progress"]["percent"] == 37.5

    recorder.stage_progress(5, 3)
    progress = _stage(recorder.snapshot(), 5)["progress"]
    assert progress["total"] == 8 and progress["percent"] == 37.5

    recorder.stage_progress(5, 8, 8)
    assert _stage(recorder.snapshot(), 5)["progress"]["percent"] == 100.0

    recorder.stage_progress(5, 1, 8, item={"id": "shot_01", "status": "rendered"})
    recorder.stage_progress(5, 2, 8, item={"id": "shot_01", "status": "retried"})
    recorder.stage_progress(5, 3, 8, item={"id": "shot_02", "status": "rendered"})
    assert _stage(_disk_state(recorder), 5)["items"] == [
        {"id": "shot_01", "status": "retried"},
        {"id": "shot_02", "status": "rendered"},
    ]


# --------------------------------------------------------------- 3. fail_stage / skip_stage


def test_fail_and_skip_stage_do_not_disturb_other_stages(tmp_path):
    """fail_stage records the error, skip_stage clears progress, siblings stay untouched."""
    recorder = _recorder(tmp_path)
    recorder.start_run()
    recorder.start_stage(2, total=4)
    recorder.stage_progress(2, 2)
    recorder.start_stage(4, total=6)
    recorder.stage_progress(4, 1, label="keyframe shot_01")

    recorder.fail_stage(2, "Renderer crashed: HTTP 500", status=500)

    on_disk = _disk_state(recorder)
    failed = _stage(on_disk, 2)
    assert failed["status"] == telemetry.STAGE_FAILED
    assert failed["error"] == "Renderer crashed: HTTP 500"
    assert failed["message"] == "FAILED: Renderer crashed: HTTP 500"
    assert failed["finished_at"] and failed["duration_seconds"] is not None

    recorder.skip_stage(6, "already completed in a previous run")
    recorder.skip_stage(1)

    on_disk = _disk_state(recorder)
    skipped = _stage(on_disk, 6)
    assert skipped["status"] == telemetry.STAGE_SKIPPED
    assert skipped["message"] == "already completed in a previous run"
    assert skipped["progress"] is None
    assert _stage(on_disk, 1)["message"] == "Skipped (already completed in a previous run)"

    assert _stage(on_disk, 2)["status"] == telemetry.STAGE_FAILED
    stage4 = _stage(on_disk, 4)
    assert stage4["status"] == telemetry.STAGE_RUNNING
    assert stage4["progress"]["current"] == 1 and stage4["progress"]["label"] == "keyframe shot_01"
    assert on_disk["current_stage"] == 4
    assert _stage(on_disk, 3)["status"] == telemetry.STAGE_PENDING
    assert [event["type"] for event in _events(recorder) if event["type"] == "stage_failed"] == ["stage_failed"]


# ------------------------------------------------------------------------- 4. event log


def test_event_log_is_monotonic_jsonl_and_readers_honour_filters(tmp_path):
    """events.jsonl is one JSON object per line with strictly increasing seq and known types."""
    recorder = _recorder(tmp_path)
    artifact = tmp_path / "brief.json"
    artifact.write_text("{}", encoding="utf-8")

    recorder.start_run(campaign_id="campaign_cherry_dress_01")
    recorder.start_stage(1, total=2)
    recorder.stage_progress(1, 1, label="brief")
    recorder.stage_message(1, "brief drafted")
    recorder.complete_stage(1)
    recorder.start_stage(2, total=3)
    recorder.skip_stage(2, "resume")
    recorder.log("rendering shot_01")
    recorder.log("API call failed, retrying", level="warning")
    recorder.note("chose archetype", archetype="fashion_apparel")
    recorder.register_artifact(artifact, stage=1)
    recorder.record_prompt("shot_01", "prompt text", model="hailuo-2.3")
    recorder.record_api_call("hailuo", endpoint="/v1/videos", status=200, ok=True, duration_seconds=3.2)
    recorder.fail_stage(3, "storyboard exploded")
    recorder.finish_run(False, summary="aborted")

    raw_lines = recorder.events_path.read_text(encoding="utf-8").splitlines()
    assert raw_lines and all(line.strip() for line in raw_lines)
    events = [json.loads(line) for line in raw_lines]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert [event["type"] for event in events] == [
        "run_start",
        "stage_start",
        "stage_progress",
        "stage_message",
        "stage_complete",
        "stage_start",
        "stage_skipped",
        "log",
        "log",
        "note",
        "artifact",
        "prompt",
        "api_call",
        "stage_failed",
        "run_failed",
    ]
    assert {event["type"] for event in events} <= DOCUMENTED_EVENT_TYPES
    for event in events:
        assert set(event) == {"seq", "ts", "type", "stage", "level", "text", "payload"}
        assert isinstance(event["payload"], dict)
        assert event["ts"].endswith("Z")

    counters = _disk_state(recorder)["counters"]
    assert counters == {"events": len(events), "errors": 2, "warnings": 1}
    assert _disk_state(recorder)["last_event"]["seq"] == events[-1]["seq"]
    assert _disk_state(recorder)["status"] == telemetry.RUN_FAILED
    assert _disk_state(recorder)["elapsed_seconds"] is not None

    assert telemetry.read_events(recorder.events_path) == events
    assert [event["seq"] for event in telemetry.read_events(recorder.events_path, since=2)] == list(
        range(3, len(events) + 1)
    )
    assert [event["seq"] for event in telemetry.read_events(recorder.events_path, limit=3)] == [
        event["seq"] for event in events[-3:]
    ]
    assert telemetry.read_events(recorder.events_path, since=len(events)) == []
    assert telemetry.read_events(tmp_path / "missing" / "events.jsonl") == []

    assert [event["seq"] for event in telemetry.tail_events(recorder.events_path, limit=2)] == [
        event["seq"] for event in events[-2:]
    ]
    warnings = telemetry.tail_events(recorder.events_path, limit=50, levels=["warning"])
    assert [event["text"] for event in warnings] == ["API call failed, retrying"]
    errors = telemetry.tail_events(recorder.events_path, limit=50, levels=["error"])
    assert {event["type"] for event in errors} == {"stage_failed", "run_failed"}
    tailed = telemetry.tail_events(recorder.events_path, since=events[2]["seq"], limit=50, levels=["error", "warning"])
    assert [event["type"] for event in tailed] == ["log", "stage_failed", "run_failed"]


def test_finish_run_success_marks_completed_and_emits_run_complete(tmp_path):
    """finish_run(ok=True) closes the run as completed with an elapsed time."""
    recorder = _recorder(tmp_path)
    recorder.start_run()
    recorder.finish_run(True, summary="Pipeline completed")

    state = _disk_state(recorder)
    assert state["status"] == telemetry.RUN_COMPLETED
    assert state["finished_at"] is not None
    assert state["elapsed_seconds"] is not None and state["elapsed_seconds"] >= 0

    event = _events(recorder)[-1]
    assert event["type"] == "run_complete"
    assert event["level"] is None
    assert event["text"] == "Pipeline completed"


# ------------------------------------------------------------------------- 5. artifacts


def test_register_artifact_classifies_kind_and_attaches_to_owning_stage(tmp_path):
    """register_artifact records rel_path/size/kind and lists the file under its stage."""
    run_root = tmp_path / "run"
    run_root.mkdir()
    recorder = _recorder(run_root)

    expected_kinds = {
        "brief.json": "json",
        "raw_video_clip.mp4": "video",
        "keyframe_shot_01.JPG": "image",
        "voice_shot_01.wav": "audio",
        "subtitles.srt": "text",
        "storyboard.zip": "file",
    }
    for name, kind in expected_kinds.items():
        path = run_root / name
        path.write_bytes(b"payload")
        record = recorder.register_artifact(path, stage=4)
        assert record["kind"] == kind
        assert record["rel_path"] == name
        assert record["size_bytes"] == path.stat().st_size
        assert record["exists"] is True
        assert record["stage"] == 4
        assert record["label"] == name
        assert record["written_at"].endswith("Z")

    on_disk = _disk_state(recorder)
    assert set(on_disk["artifact_index"]) == set(expected_kinds)
    assert _stage(on_disk, 4)["artifacts"] == list(expected_kinds)
    assert all(entry["artifacts"] == [] for entry in on_disk["stages"] if entry["stage"] != 4)
    assert [event["type"] for event in _events(recorder)] == ["artifact"] * len(expected_kinds)


def test_register_artifact_handles_relative_missing_and_outside_paths(tmp_path):
    """Relative paths resolve against base_dir; missing/outside files are recorded truthfully."""
    run_root = tmp_path / "run"
    run_root.mkdir()
    recorder = _recorder(run_root)

    relative = recorder.register_artifact("assets/portrait.png", stage=4)
    assert relative["rel_path"] == "assets/portrait.png"
    assert relative["exists"] is False
    assert relative["size_bytes"] is None
    assert relative["kind"] == "image"

    loose = run_root / "scene_plan.json"
    loose.write_text("{}", encoding="utf-8")
    recorder.register_artifact(loose)

    outside = tmp_path / "outside.txt"
    outside.write_text("hello", encoding="utf-8")
    external = recorder.register_artifact(outside, stage=4)
    assert external["rel_path"] == str(outside.resolve())
    assert external["exists"] is True

    on_disk = _disk_state(recorder)
    assert on_disk["artifact_index"]["scene_plan.json"]["stage"] is None
    assert all("scene_plan.json" not in entry["artifacts"] for entry in on_disk["stages"])
    assert "assets/portrait.png" in _stage(on_disk, 4)["artifacts"]
    assert telemetry.artifact_kind("mystery") == "file"


# --------------------------------------------------------------------------- 6. prompts


def test_record_prompt_merges_updates_and_counts_attempts(tmp_path):
    """Prompt records merge by shot_id: later fields win, earlier extras survive, attempts only on request."""
    recorder = _recorder(tmp_path)
    recorder.record_prompt("shot_01", "first prompt", model="hailuo-2.3", aspect_ratio="9:16", duration_requested=6)

    first = recorder.snapshot()["prompts"]["shot_01"]
    assert first["shot_id"] == "shot_01"
    assert first["stage"] == 5
    assert first["prompt"] == "first prompt"
    assert first["attempts"] == 0
    assert first["first_seen_at"] == first["updated_at"]
    assert first["model"] == "hailuo-2.3" and first["aspect_ratio"] == "9:16"

    recorder.record_prompt(
        "shot_01",
        "second prompt",
        task_id="task-42",
        output_rel_path="raw_video_clips/shot_01.mp4",
        size_bytes=1234,
        attempt_increment=1,
    )

    second = recorder.snapshot()["prompts"]["shot_01"]
    assert second["prompt"] == "second prompt"
    assert second["stage"] == 5
    assert second["attempts"] == 1
    assert second["first_seen_at"] == first["first_seen_at"]
    assert second["updated_at"] >= first["updated_at"]
    assert second["task_id"] == "task-42"
    assert second["output_rel_path"] == "raw_video_clips/shot_01.mp4" and second["size_bytes"] == 1234
    assert second["model"] == "hailuo-2.3"
    assert second["aspect_ratio"] == "9:16"
    assert second["duration_requested"] == 6

    recorder.record_prompt("shot_01", "second prompt", attempt_increment=2, task_id=None)
    third = recorder.snapshot()["prompts"]["shot_01"]
    assert third["attempts"] == 3
    assert third["task_id"] == "task-42"
    assert third["first_seen_at"] == first["first_seen_at"]
    assert "attempt_increment" not in third

    recorder.record_prompt("shot_02", "other shot")
    prompts = recorder.snapshot()["prompts"]
    assert set(prompts) == {"shot_01", "shot_02"}
    assert prompts["shot_02"]["attempts"] == 0
    assert _disk_state(recorder)["prompts"] == prompts
    assert [event["type"] for event in _events(recorder)] == ["prompt"] * 4


# ----------------------------------------------------------------------- 7. api calls


def test_record_api_call_redacts_credentials_and_keeps_newest_200(tmp_path):
    """API calls are stored/published with credentials redacted and trimmed to the newest 200."""
    recorder = _recorder(tmp_path)
    recorder.record_api_call(
        "hailuo",
        endpoint="/v1/video_generation",
        method="POST",
        status=200,
        ok=True,
        duration_seconds=12.3456,
        shot_id="shot_01",
        request={
            "api_key": "sk-live-abc123",
            "model_name": "hailuo-2.3",
            "auth_header": "Bearer topsecretvalue",
            "nested": {"Authorization": "Bearer nestedsecret"},
            "items": ["sk-inline-secret", "plain"],
        },
        response={"task_id": "t1", "raw_token": "response-secret", "data": {"status": "ok"}},
    )

    persisted = _disk_state(recorder)["api_calls"][-1]
    assert persisted["name"] == "hailuo"
    assert persisted["request"]["api_key"] == "***REDACTED***"
    assert persisted["request"]["auth_header"] == "***REDACTED***"
    assert persisted["request"]["nested"]["Authorization"] == "***REDACTED***"
    assert persisted["request"]["items"] == ["***REDACTED***", "plain"]
    assert persisted["request"]["model_name"] == "hailuo-2.3"
    assert persisted["response"]["raw_token"] == "***REDACTED***"
    assert persisted["response"]["data"]["status"] == "ok"
    assert persisted["duration_seconds"] == 12.346
    assert persisted["status"] == 200 and persisted["ok"] is True and persisted["shot_id"] == "shot_01"

    raw_events = recorder.events_path.read_text(encoding="utf-8")
    for secret in ("sk-live-abc123", "topsecretvalue", "nestedsecret", "sk-inline-secret", "response-secret"):
        assert secret not in raw_events

    event = _events(recorder)[-1]
    assert event["type"] == "api_call"
    assert event["text"] == "POST /v1/video_generation -> 200"
    assert event["level"] is None
    assert "request" not in event["payload"] and "response" not in event["payload"]
    assert event["payload"]["name"] == "hailuo" and event["payload"]["duration_seconds"] == 12.346

    for index in range(205):
        recorder.record_api_call(f"call-{index:03d}", endpoint="/v1/ping", status=200, ok=True)

    calls = _disk_state(recorder)["api_calls"]
    assert telemetry.MAX_API_CALLS_KEPT == 200
    assert len(calls) == 200
    assert calls[0]["name"] == "call-005"
    assert calls[-1]["name"] == "call-204"
    assert [call["name"] for call in calls] == [f"call-{index:03d}" for index in range(5, 205)]


def test_record_api_call_marks_failures_as_warnings(tmp_path):
    """A failed API call is logged as a warning-level event with ok=False."""
    recorder = _recorder(tmp_path)
    recorder.record_api_call("hailuo", endpoint="/v1/videos", status=429, ok=False, shot_id="shot_01")

    event = _events(recorder)[-1]
    assert event["level"] == "warning"
    assert event["text"] == "POST /v1/videos -> 429"
    assert _disk_state(recorder)["api_calls"][-1]["ok"] is False
    assert _disk_state(recorder)["counters"]["warnings"] == 1


# --------------------------------------------------------------------------- 8. resume


def test_second_recorder_resumes_stages_prompts_and_event_sequence(tmp_path):
    """A recorder reopened on the same telemetry dir keeps history and continues the seq counter."""
    run_root = tmp_path / "run"
    run_root.mkdir()
    first = _recorder(run_root)
    first.start_run(campaign_id="campaign_cherry_dress_01")
    first.start_stage(1, total=4)
    first.complete_stage(1)
    first.record_prompt("shot_01", "first prompt", model="hailuo-2.3")
    first.record_api_call("researcher", endpoint="/v1/search", status=200, ok=True)
    first.finish_run(True)

    before = _events(first)
    assert before[-1]["type"] == "run_complete"
    prior_state = _disk_state(first)
    assert prior_state["run_index"] == 1

    second = _recorder(run_root)
    resumed = second.snapshot()
    assert resumed["run_index"] == 1
    assert resumed["first_started_at"] == prior_state["first_started_at"]
    assert _stage(resumed, 1)["status"] == telemetry.STAGE_COMPLETED
    assert resumed["prompts"]["shot_01"]["prompt"] == "first prompt"
    assert resumed["prompts"]["shot_01"]["model"] == "hailuo-2.3"
    assert resumed["api_calls"][-1]["name"] == "researcher"

    second.start_run(mode="resume", campaign_id="campaign_cherry_dress_01")
    second.start_stage(2, total=3)
    second.complete_stage(2)
    second.record_prompt("shot_01", "first prompt", attempt_increment=1)

    after = _events(second)
    assert [event["seq"] for event in after] == list(range(1, len(after) + 1))
    assert after[: len(before)] == before
    assert after[len(before)]["seq"] == before[-1]["seq"] + 1
    assert after[len(before)]["type"] == "run_start"

    final = _disk_state(second)
    assert final["run_index"] == 2
    assert final["first_started_at"] == prior_state["first_started_at"]
    assert _stage(final, 1)["status"] == telemetry.STAGE_COMPLETED
    assert _stage(final, 2)["status"] == telemetry.STAGE_COMPLETED
    assert final["prompts"]["shot_01"]["attempts"] == 1


# ----------------------------------------------------------------------- 9. fail-safety


def test_unusable_telemetry_dir_never_raises_and_counts_write_errors(tmp_path):
    """A file where the telemetry dir should be degrades to counted write errors, never an exception."""
    blocked = tmp_path / "telemetry_is_a_file"
    blocked.write_text("not a directory", encoding="utf-8")
    recorder = telemetry.RunTelemetry(
        "campaign_cherry_dress_01", "fashion_apparel", telemetry_dir=blocked, base_dir=tmp_path
    )

    recorder.start_run(campaign_id="c1")
    recorder.start_stage(5, total=2)
    recorder.stage_progress(5, 1)
    recorder.record_prompt("shot_01", "prompt")
    recorder.record_api_call("hailuo", request={"api_key": "sk-x"}, status=200, ok=True)
    recorder.register_artifact(tmp_path / "brief.json", stage=1)
    recorder.note("still alive")
    recorder.complete_stage(5)
    recorder.fail_stage(6, "boom")
    recorder.skip_stage(7)
    recorder.log("done")
    recorder.finish_run(True)
    recorder.flush()

    assert recorder.write_errors > 0
    assert telemetry.read_events(recorder.events_path) == []
    assert blocked.is_file()
    assert blocked.read_text(encoding="utf-8") == "not a directory"

    with telemetry.use_recorder(recorder):
        telemetry.log("mirror")
        telemetry.stage_progress(5, 2, 2)
        telemetry.record_api_call("mirror-api")
        telemetry.record_prompt("shot_02", "prompt")
        telemetry.register_artifact(tmp_path / "script.json")
        telemetry.complete_stage(5)

    assert recorder.write_errors > 0
    assert recorder.snapshot()["counters"]["events"] > 0


# --------------------------------------------------------------------------- 10. no-ops


def test_module_helpers_are_noops_without_active_recorder(tmp_path):
    """Without a recorder every mirror is a silent no-op that writes nothing anywhere."""
    assert telemetry.current() is None
    assert telemetry.active() is False

    telemetry.start_run(campaign_id="c1")
    telemetry.start_stage(1, "stage", total=3)
    telemetry.stage_progress(1, 1, 3)
    telemetry.stage_message(1, "hello")
    telemetry.complete_stage(1)
    telemetry.fail_stage(1, "err")
    telemetry.skip_stage(1, "why")
    telemetry.log("text")
    telemetry.log("text", level="error", stage=1)
    telemetry.note("note", key="value")
    telemetry.register_artifact(tmp_path / "brief.json", stage=1)
    telemetry.record_prompt("shot_01", "prompt")
    telemetry.record_api_call("api", endpoint="/v1", status=200, ok=True)
    telemetry.finish_run(True, summary="ok")

    original_stdout = sys.stdout
    with telemetry.capture_console() as handle:
        assert handle is None
        assert sys.stdout is original_stdout
        print("not recorded")
    assert sys.stdout is original_stdout

    assert list(tmp_path.iterdir()) == []


def test_use_recorder_installs_and_restores_previous_recorder(tmp_path):
    """use_recorder swaps the active recorder, restores it on exit and on exception, and nests."""
    outer = _recorder(tmp_path / "outer")
    inner = _recorder(tmp_path / "inner")
    assert telemetry.current() is None

    telemetry.use(outer)
    assert telemetry.active() is True
    telemetry.log("to outer")

    with telemetry.use_recorder(inner):
        assert telemetry.current() is inner
        telemetry.log("to inner")
        with telemetry.use_recorder(None):
            assert telemetry.current() is None and telemetry.active() is False
            telemetry.log("dropped")
        assert telemetry.current() is inner
    assert telemetry.current() is outer

    with pytest.raises(RuntimeError):
        with telemetry.use_recorder(inner):
            assert telemetry.current() is inner
            raise RuntimeError("stage exploded")
    assert telemetry.current() is outer

    telemetry.use(None)
    assert telemetry.current() is None
    assert [event["text"] for event in _events(outer)] == ["to outer"]
    assert [event["text"] for event in _events(inner)] == ["to inner"]


# ---------------------------------------------------------------------- 11. thread safety


def test_concurrent_progress_and_log_calls_keep_event_log_intact(tmp_path):
    """8 threads x 25 progress+log pairs yield a gapless event sequence and parseable state.json."""
    recorder = _recorder(tmp_path)
    recorder.start_run()
    recorder.start_stage(5, total=25)

    workers = 8
    steps = 25
    barrier = threading.Barrier(workers)
    failures: list = []

    def worker(worker_id: int) -> None:
        try:
            barrier.wait(timeout=30)
            for index in range(steps):
                recorder.stage_progress(
                    5,
                    index + 1,
                    25,
                    unit="shots",
                    label=f"worker {worker_id}",
                    item={"id": f"{worker_id}-{index}", "status": "rendered"},
                )
                recorder.log(f"worker {worker_id} step {index}")
        except Exception as exc:  # pragma: no cover - reported through the assertion below
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(worker_id,)) for worker_id in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert failures == []
    assert [thread.is_alive() for thread in threads] == [False] * workers

    raw_lines = recorder.events_path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in raw_lines]
    assert len(raw_lines) == 2 + workers * steps * 2
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert [event["type"] for event in events[:2]] == ["run_start", "stage_start"]
    assert {event["type"] for event in events[2:]} == {"stage_progress", "log"}
    assert all(event["stage"] == 5 for event in events[2:])
    assert len({event["text"] for event in events if event["type"] == "log"}) == workers * steps

    # log-only bursts are throttled on disk (STATE_WRITE_MIN_INTERVAL); flush() reconciles it.
    recorder.flush()
    state = _disk_state(recorder)
    assert state["counters"]["events"] == len(events)
    progress = _stage(state, 5)["progress"]
    assert progress["total"] == 25 and progress["unit"] == "shots"
    assert 1 <= progress["current"] <= 25
    assert len(_stage(state, 5)["items"]) == workers * steps


# ------------------------------------------------------------------- 12. console capture


def test_capture_console_mirrors_lines_and_restores_streams(tmp_path):
    """capture_console tees print() lines into the event log and always restores stdout/stderr."""
    recorder = _recorder(tmp_path)
    original_out, original_err = sys.stdout, sys.stderr

    with telemetry.use_recorder(recorder):
        with telemetry.capture_console():
            assert sys.stdout is not original_out and sys.stderr is not original_err
            print("stage 5 rendering shot 01")
            print("retrying request", file=sys.stderr)
        assert sys.stdout is original_out
        assert sys.stderr is original_err

        with pytest.raises(RuntimeError):
            with telemetry.capture_console():
                print("partial line without newline", end="")
                raise RuntimeError("stage exploded")
        assert sys.stdout is original_out
        assert sys.stderr is original_err

    assert sys.stdout is original_out and sys.stderr is original_err

    logs = [event for event in _events(recorder) if event["type"] == "log"]
    assert "stage 5 rendering shot 01" in [event["text"] for event in logs]
    stderr_event = next(event for event in logs if event["text"] == "retrying request")
    assert stderr_event["level"] == "error"
    assert any(event["text"] == "partial line without newline" for event in logs)
    assert all(event["type"] in DOCUMENTED_EVENT_TYPES for event in _events(recorder))
