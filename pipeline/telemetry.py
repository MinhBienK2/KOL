"""Pipeline run telemetry: durable run state, structured event log, video-prompt ledger.

Single source of truth for "what is the agent doing right now, and what did it produce?".

Two durable outputs per run, both under ``{run_root}/telemetry/``:

* ``state.json``  — atomically rewritten snapshot (stages, progress, artifacts, prompts).
* ``events.jsonl`` — append-only event stream consumed by the live dashboard feed.

Design rules:

1. Telemetry is **fail-safe**: instrumentation MUST never break a render. Every public
   entry point swallows its own exceptions and increments ``counters.errors``.
2. Telemetry is **thread-safe**: ``video_engine`` renders shots concurrently.
3. Telemetry is **optional**: with no active recorder all module-level helpers are no-ops,
   so stage modules and unit tests keep working standalone.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, NamedTuple, Optional, Sequence, Tuple, Union

SCHEMA_VERSION = 1

TELEMETRY_DIRNAME = "telemetry"
STATE_FILENAME = "state.json"
EVENTS_FILENAME = "events.jsonl"

RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_UNKNOWN = "unknown"

STAGE_PENDING = "pending"
STAGE_RUNNING = "running"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"

MAX_API_CALLS_KEPT = 200
STATE_WRITE_MIN_INTERVAL = 0.05


class StageSpec(NamedTuple):
    """Canonical identity of one pipeline stage."""

    stage: int
    key: str
    title: str


STAGE_CATALOG: Tuple[StageSpec, ...] = (
    StageSpec(1, "research_briefing", "Competitor Research & Strategic Creative Briefing"),
    StageSpec(2, "scriptwriting", "Multi-Archetype High-Conversion Scriptwriting"),
    StageSpec(3, "storyboard_staging", "DramaClaw Spatial Storyboard & OpenMontage Slideshow Risk Gate"),
    StageSpec(4, "identity_keyframes", "KOL Identity Locking & Clean Keyframe Staging"),
    StageSpec(5, "video_diffusion", "Genuine Video Diffusion Generation (Hailuo-2.3)"),
    StageSpec(6, "audio_lip_sync", "Neural TTS Audio & Lip-Sync Alignment"),
    StageSpec(7, "composition", "Final FFmpeg Multi-Track Composition & Audio Ducking"),
    StageSpec(8, "verification_publish", "Independent Quality Verification Gates & Packaging"),
)
TOTAL_STAGES = len(STAGE_CATALOG)
_STAGE_SPECS: Dict[int, StageSpec] = {spec.stage: spec for spec in STAGE_CATALOG}

#: Canonical artifacts that unambiguously prove a stage finished (used by the dashboard
#: to derive stage status for runs recorded before telemetry existed).
STAGE_PRIMARY_ARTIFACTS: Dict[int, Tuple[str, ...]] = {
    1: ("brief.json",),
    2: ("script.json",),
    3: ("scene_plan.json",),
    4: ("asset_manifest.json",),
    5: (),
    6: (),
    7: ("edit_decisions.json",),
    8: ("render_report.json",),
}

VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg"}
TEXT_SUFFIXES = {".txt", ".srt", ".md", ".log", ".csv"}


_STAGE_NUMBERS: Dict[str, int] = {spec.key: spec.stage for spec in STAGE_CATALOG}


def stage_spec(stage: int) -> StageSpec:
    """Return the :class:`StageSpec` for ``stage`` (synthesizes one for unknown stages)."""
    return _STAGE_SPECS.get(stage) or StageSpec(stage, f"stage_{stage}", f"Stage {stage}")


def stage_number(key: str) -> int:
    """Return the stage number for a catalog key (e.g. ``"video_diffusion"`` -> ``5``)."""
    return _STAGE_NUMBERS.get(key, 0)


def now_iso() -> str:
    """UTC timestamp in the artifact convention used across the repo (``...Z``)."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


_SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|authorization|password|cookie|bearer)", re.I)
_SECRET_VALUE_RE = re.compile(r"^(sk-|Bearer\s)", re.I)


def redact(value: Any) -> Any:
    """Recursively redact credentials from request/response payloads before persisting."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            if _SECRET_KEY_RE.search(str(key)):
                out[str(key)] = "***REDACTED***"
            else:
                out[str(key)] = redact(item)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str) and _SECRET_VALUE_RE.match(value):
        return "***REDACTED***"
    return value


def artifact_kind(path: Union[str, Path]) -> str:
    """Classify an artifact by suffix into json/video/image/audio/text/file."""
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "file"


def _blank_stage(spec: StageSpec) -> Dict[str, Any]:
    return {
        "stage": spec.stage,
        "key": spec.key,
        "title": spec.title,
        "status": STAGE_PENDING,
        "started_at": None,
        "finished_at": None,
        "duration_seconds": None,
        "progress": None,
        "message": None,
        "error": None,
        "items": [],
        "artifacts": [],
    }


class RunTelemetry:
    """Records one project run and persists it as ``state.json`` + ``events.jsonl``."""

    def __init__(
        self,
        project_id: str,
        topic: Optional[str] = None,
        *,
        telemetry_dir: Union[str, Path],
        base_dir: Optional[Union[str, Path]] = None,
        run_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.project_id = str(project_id)
        self.topic = str(topic) if topic else None
        self.telemetry_dir = Path(telemetry_dir)
        self.base_dir = Path(base_dir).resolve() if base_dir else self.telemetry_dir.resolve().parent
        self.state_path = self.telemetry_dir / STATE_FILENAME
        self.events_path = self.telemetry_dir / EVENTS_FILENAME

        self._lock = threading.RLock()
        self._seq = 0
        self._last_state_write = 0.0
        self._write_errors = 0

        self.state: Dict[str, Any] = self._initial_state()
        self._load_existing()
        if run_meta:
            self.state["run_meta"].update(redact(run_meta))

    # ------------------------------------------------------------------ setup

    def _initial_state(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "project_id": self.project_id,
            "topic": self.topic,
            "status": RUN_UNKNOWN,
            "run_index": 0,
            "run_meta": {},
            "workspace_root": None,
            "artifacts_dir": None,
            "master_video_path": None,
            "thumbnail_path": None,
            "first_started_at": None,
            "last_started_at": None,
            "finished_at": None,
            "elapsed_seconds": None,
            "current_stage": None,
            "stages": [_blank_stage(spec) for spec in STAGE_CATALOG],
            "artifact_index": {},
            "prompts": {},
            "api_calls": [],
            "counters": {"events": 0, "errors": 0, "warnings": 0},
            "last_event": None,
        }

    def _load_existing(self) -> None:
        """Resume from a previous run of the same project (keeps completed stages)."""
        try:
            if not self.state_path.exists():
                return
            with open(self.state_path, "r", encoding="utf-8") as handle:
                previous = json.load(handle)
            if not isinstance(previous, dict):
                return
            for key in (
                "run_index",
                "artifact_index",
                "prompts",
                "api_calls",
                "first_started_at",
                "stages",
                "counters",
            ):
                if key in previous:
                    self.state[key] = previous[key]
            self._seq = int((previous.get("last_event") or {}).get("seq") or 0)
        except Exception:
            self._write_errors += 1

    # ---------------------------------------------------------------- persist

    def _stage_entry(self, stage: int) -> Optional[Dict[str, Any]]:
        for entry in self.state["stages"]:
            if entry.get("stage") == stage:
                return entry
        spec = stage_spec(stage)
        entry = _blank_stage(spec)
        self.state["stages"].append(entry)
        self.state["stages"].sort(key=lambda item: item.get("stage") or 0)
        return entry

    def _write_state(self, force: bool = False) -> None:
        if not force and (time.monotonic() - self._last_state_write) < STATE_WRITE_MIN_INTERVAL:
            return
        try:
            self.telemetry_dir.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.state, ensure_ascii=False, indent=2, default=str)
            tmp_path = self.state_path.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.state_path)
            self._last_state_write = time.monotonic()
        except Exception:
            self._write_errors += 1

    def _append_event(self, event: Dict[str, Any]) -> None:
        try:
            self.telemetry_dir.mkdir(parents=True, exist_ok=True)
            with open(self.events_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        except Exception:
            self._write_errors += 1

    def _emit(
        self,
        event_type: str,
        *,
        stage: Optional[int] = None,
        text: Optional[str] = None,
        level: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Append one event and refresh the state snapshot. Never raises."""
        try:
            with self._lock:
                self._seq += 1
                event = {
                    "seq": self._seq,
                    "ts": now_iso(),
                    "type": event_type,
                    "stage": stage,
                    "level": level,
                    "text": text,
                    "payload": payload or {},
                }
                self.state["counters"]["events"] = self._seq
                if level == "error":
                    self.state["counters"]["errors"] += 1
                elif level == "warning":
                    self.state["counters"]["warnings"] += 1
                self.state["last_event"] = {
                    "seq": event["seq"],
                    "ts": event["ts"],
                    "type": event_type,
                    "stage": stage,
                    "level": level,
                    "text": text,
                }
                self._append_event(event)
                self._write_state(force=event_type != "log")
                return event
        except Exception:
            self._write_errors += 1
            return None

    def flush(self) -> None:
        """Force the state snapshot to disk (called at stage boundaries and run end)."""
        with self._lock:
            self._write_state(force=True)

    def snapshot(self) -> Dict[str, Any]:
        """Deep copy of the current state (safe to serialize)."""
        with self._lock:
            return json.loads(json.dumps(self.state, ensure_ascii=False, default=str))

    # ------------------------------------------------------------------ run

    def start_run(self, **meta: Any) -> None:
        """Open a new run attempt on this project."""
        with self._lock:
            self.state["run_index"] = int(self.state.get("run_index") or 0) + 1
            self.state["run_meta"].update(redact(meta))
            self.state["status"] = RUN_RUNNING
            self.state["last_started_at"] = now_iso()
            self.state["finished_at"] = None
            self.state["elapsed_seconds"] = None
            if not self.state.get("first_started_at"):
                self.state["first_started_at"] = self.state["last_started_at"]
            for key in ("workspace_root", "artifacts_dir", "master_video_path", "thumbnail_path"):
                if meta.get(key):
                    self.state[key] = str(meta[key])
        self._emit(
            "run_start",
            text=f"Run #{self.state['run_index']} started for project '{self.project_id}'",
            payload=dict(self.state["run_meta"]),
        )
        self.flush()

    def finish_run(self, ok: bool, summary: Optional[str] = None, **extra: Any) -> None:
        """Close the run attempt with its terminal status."""
        with self._lock:
            self.state["status"] = RUN_COMPLETED if ok else RUN_FAILED
            self.state["finished_at"] = now_iso()
            started = self.state.get("last_started_at") or self.state.get("first_started_at")
            self.state["elapsed_seconds"] = _elapsed_seconds(started, self.state["finished_at"])
            if extra:
                self.state["run_meta"].update(redact(extra))
        self._emit(
            "run_complete" if ok else "run_failed",
            text=summary or ("Pipeline completed" if ok else "Pipeline failed"),
            level=None if ok else "error",
            payload={"elapsed_seconds": self.state["elapsed_seconds"], **redact(extra)},
        )
        self.flush()

    # ---------------------------------------------------------------- stages

    def start_stage(self, stage: int, message: Optional[str] = None, total: Optional[int] = None) -> None:
        """Mark a stage as running."""
        with self._lock:
            entry = self._stage_entry(stage)
            if entry is None:
                return
            entry["status"] = STAGE_RUNNING
            entry["started_at"] = now_iso()
            entry["finished_at"] = None
            entry["duration_seconds"] = None
            entry["error"] = None
            if message:
                entry["message"] = message
            if total is not None:
                entry["progress"] = {"current": 0, "total": int(total), "percent": 0.0, "unit": None, "label": None}
            self.state["current_stage"] = stage
        self._emit(
            "stage_start",
            stage=stage,
            text=message or f"Stage {stage} started: {stage_spec(stage).title}",
            payload={"total": total} if total is not None else {},
        )

    def stage_progress(
        self,
        stage: int,
        current: int,
        total: Optional[int] = None,
        *,
        label: Optional[str] = None,
        unit: Optional[str] = None,
        message: Optional[str] = None,
        item: Optional[Dict[str, Any]] = None,
        **extra: Any,
    ) -> None:
        """Record ``current/total`` progress inside a stage (per-shot loops, retries...)."""
        with self._lock:
            entry = self._stage_entry(stage)
            if entry is None:
                return
            previous = entry.get("progress") or {}
            resolved_total = int(total if total is not None else previous.get("total") or 0) or None
            percent = round(100.0 * current / resolved_total, 2) if resolved_total else None
            entry["progress"] = {
                "current": int(current),
                "total": resolved_total,
                "percent": percent,
                "unit": unit or previous.get("unit"),
                "label": label or previous.get("label"),
            }
            if message:
                entry["message"] = message
            if item:
                entry["items"] = [existing for existing in entry["items"] if existing.get("id") != item.get("id")]
                entry["items"].append(redact(item))
        self._emit(
            "stage_progress",
            stage=stage,
            text=message or label or f"Stage {stage}: {current}/{resolved_total or '?'}",
            payload={
                "current": int(current),
                "total": resolved_total,
                "percent": percent,
                "label": label,
                "unit": unit,
                "item": redact(item) if item else None,
                **redact(extra),
            },
        )

    def stage_message(self, stage: int, text: str, level: str = "info", **extra: Any) -> None:
        """Attach a human-readable status line to a stage without changing progress."""
        with self._lock:
            entry = self._stage_entry(stage)
            if entry is not None:
                entry["message"] = text
        self._emit("stage_message", stage=stage, text=text, level=level, payload=redact(extra) or {})

    def complete_stage(self, stage: int, message: Optional[str] = None, **extra: Any) -> None:
        """Mark a stage as successfully finished."""
        with self._lock:
            entry = self._stage_entry(stage)
            if entry is None:
                return
            entry["status"] = STAGE_COMPLETED
            entry["finished_at"] = now_iso()
            entry["duration_seconds"] = _elapsed_seconds(entry.get("started_at"), entry["finished_at"])
            entry["error"] = None
            if message:
                entry["message"] = message
            progress = entry.get("progress")
            if progress:
                progress["current"] = progress.get("total") or progress.get("current")
                progress["percent"] = 100.0
            if self.state.get("current_stage") == stage:
                self.state["current_stage"] = None
        self._emit(
            "stage_complete",
            stage=stage,
            text=message or f"Stage {stage} completed",
            payload={"duration_seconds": entry["duration_seconds"], **redact(extra)},
        )
        self.flush()

    def fail_stage(self, stage: int, error: str, **extra: Any) -> None:
        """Mark a stage as failed."""
        with self._lock:
            entry = self._stage_entry(stage)
            if entry is None:
                return
            entry["status"] = STAGE_FAILED
            entry["finished_at"] = now_iso()
            entry["duration_seconds"] = _elapsed_seconds(entry.get("started_at"), entry["finished_at"])
            entry["error"] = str(error)
            entry["message"] = f"FAILED: {error}"
        self._emit(
            "stage_failed",
            stage=stage,
            text=str(error),
            level="error",
            payload={"duration_seconds": entry["duration_seconds"], **redact(extra)},
        )
        self.flush()

    def skip_stage(self, stage: int, reason: Optional[str] = None) -> None:
        """Mark a stage as intentionally skipped (resumed run)."""
        with self._lock:
            entry = self._stage_entry(stage)
            if entry is None:
                return
            entry["status"] = STAGE_SKIPPED
            entry["message"] = reason or "Skipped (already completed in a previous run)"
            entry["progress"] = None
        self._emit("stage_skipped", stage=stage, text=entry["message"])
        self.flush()

    # ------------------------------------------------------------------ logs

    def log(self, text: str, level: str = "info", stage: Optional[int] = None) -> None:
        """Record a raw log line (used by console capture and manual instrumentation)."""
        text = (text or "").rstrip("\n")
        if not text:
            return
        if level == "info":
            level = _infer_level(text)
        with self._lock:
            resolved_stage = stage if stage is not None else self.state.get("current_stage")
        self._emit("log", stage=resolved_stage, text=text, level=level)

    def note(self, text: str, **extra: Any) -> None:
        """Record an unstructured but significant note (decisions, fallbacks)."""
        self._emit("note", text=text, payload=redact(extra) or {})

    # ------------------------------------------------------------- artifacts

    def register_artifact(
        self,
        path: Union[str, Path],
        *,
        stage: Optional[int] = None,
        kind: Optional[str] = None,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record a file produced by the pipeline so the dashboard can list/serve it."""
        try:
            resolved = Path(path)
            if not resolved.is_absolute():
                resolved = (self.base_dir / resolved).resolve()
            else:
                resolved = resolved.resolve()
            rel_path = _relative_or_absolute(resolved, self.base_dir)
            size_bytes: Optional[int] = None
            exists = resolved.exists()
            if exists and resolved.is_file():
                try:
                    size_bytes = resolved.stat().st_size
                except OSError:
                    size_bytes = None
            record = {
                "name": resolved.name,
                "rel_path": rel_path,
                "abs_path": str(resolved),
                "kind": kind or artifact_kind(resolved),
                "size_bytes": size_bytes,
                "exists": exists,
                "stage": stage,
                "label": label or resolved.name,
                "written_at": now_iso(),
            }
            with self._lock:
                self.state["artifact_index"][rel_path] = record
                entry = self._stage_entry(stage) if stage else None
                if entry is not None and rel_path not in entry["artifacts"]:
                    entry["artifacts"].append(rel_path)
            self._emit("artifact", stage=stage, text=f"Artifact written: {rel_path}", payload=record)
            return record
        except Exception:
            self._write_errors += 1
            return None

    # ---------------------------------------------------------------- prompts

    def record_prompt(self, shot_id: str, prompt: str, *, stage: int = 5, **extra: Any) -> None:
        """Register the exact generation prompt used for a shot's video/keyframe."""
        try:
            with self._lock:
                existing = self.state["prompts"].get(shot_id) or {}
                record = {
                    "shot_id": shot_id,
                    "stage": stage,
                    "prompt": prompt,
                    "updated_at": now_iso(),
                    "attempts": int(existing.get("attempts") or 0) + int(extra.pop("attempt_increment", 0) or 0),
                }
                for key, value in (existing or {}).items():
                    if key in ("shot_id", "stage", "prompt", "updated_at", "attempts"):
                        continue
                    record.setdefault(key, value)
                for key, value in extra.items():
                    if value is not None:
                        record[key] = redact(value)
                record["first_seen_at"] = existing.get("first_seen_at") or record["updated_at"]
                self.state["prompts"][shot_id] = record
            self._emit(
                "prompt",
                stage=stage,
                text=f"Prompt registered for {shot_id} ({len(prompt or '')} chars)",
                payload=redact({k: v for k, v in record.items() if k != "prompt"}),
            )
        except Exception:
            self._write_errors += 1

    # -------------------------------------------------------------- api calls

    def record_api_call(
        self,
        name: str,
        *,
        endpoint: Optional[str] = None,
        method: str = "POST",
        request: Optional[Dict[str, Any]] = None,
        response: Optional[Any] = None,
        status: Optional[Union[int, str]] = None,
        ok: Optional[bool] = None,
        duration_seconds: Optional[float] = None,
        stage: Optional[int] = None,
        shot_id: Optional[str] = None,
    ) -> None:
        """Record an external API interaction (secrets redacted)."""
        try:
            record = {
                "name": name,
                "endpoint": endpoint,
                "method": method,
                "status": status,
                "ok": ok,
                "duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
                "shot_id": shot_id,
                "request": redact(request) if request else None,
                "response": redact(response) if response is not None else None,
                "ts": now_iso(),
            }
            with self._lock:
                self.state["api_calls"].append(record)
                if len(self.state["api_calls"]) > MAX_API_CALLS_KEPT:
                    self.state["api_calls"] = self.state["api_calls"][-MAX_API_CALLS_KEPT:]
            self._emit(
                "api_call",
                stage=stage,
                level=None if ok is not False else "warning",
                text=f"{method} {endpoint or name} -> {status if status is not None else 'ok'}",
                payload={k: v for k, v in record.items() if k not in ("request", "response")},
            )
        except Exception:
            self._write_errors += 1

    # ------------------------------------------------------------------ intro

    @property
    def write_errors(self) -> int:
        """Number of swallowed telemetry write errors (diagnostic only)."""
        with self._lock:
            return self._write_errors


def _relative_or_absolute(path: Path, base_dir: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def _elapsed_seconds(started_at: Optional[str], finished_at: Optional[str]) -> Optional[float]:
    if not started_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        return round((end - start).total_seconds(), 3)
    except Exception:
        return None


_ERROR_RE = re.compile(r"\b(error|failed|failure|traceback|exception|critical)\b", re.I)
_WARN_RE = re.compile(r"\b(warn|retry|retrying|fallback|degraded|skipped)\b", re.I)


def _infer_level(text: str) -> str:
    if _ERROR_RE.search(text):
        return "error"
    if _WARN_RE.search(text):
        return "warning"
    return "info"


# ---------------------------------------------------------------------------
# Active recorder plumbing
# ---------------------------------------------------------------------------

_active: Optional[RunTelemetry] = None
_active_lock = threading.RLock()


def use(recorder: Optional[RunTelemetry]) -> None:
    """Install ``recorder`` as the process-wide active recorder (``None`` disables)."""
    global _active
    with _active_lock:
        _active = recorder


@contextmanager
def use_recorder(recorder: Optional[RunTelemetry]) -> Iterator[Optional[RunTelemetry]]:
    """Context manager installing ``recorder`` and restoring the previous one."""
    global _active
    with _active_lock:
        previous = _active
        _active = recorder
    try:
        yield recorder
    finally:
        with _active_lock:
            _active = previous


def current() -> Optional[RunTelemetry]:
    """Return the active recorder, or ``None`` when telemetry is disabled."""
    with _active_lock:
        return _active


def active() -> bool:
    """Whether a recorder is currently installed."""
    return current() is not None


def start_run(**meta: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.start_run(**meta)


def finish_run(ok: bool, summary: Optional[str] = None, **extra: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.finish_run(ok, summary, **extra)


def start_stage(stage: int, message: Optional[str] = None, total: Optional[int] = None) -> None:
    recorder = current()
    if recorder is not None:
        recorder.start_stage(stage, message, total)


def stage_progress(stage: int, current_value: int, total: Optional[int] = None, **kwargs: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.stage_progress(stage, current_value, total, **kwargs)


def stage_message(stage: int, text: str, level: str = "info", **extra: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.stage_message(stage, text, level, **extra)


def complete_stage(stage: int, message: Optional[str] = None, **extra: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.complete_stage(stage, message, **extra)


def fail_stage(stage: int, error: str, **extra: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.fail_stage(stage, error, **extra)


def skip_stage(stage: int, reason: Optional[str] = None) -> None:
    recorder = current()
    if recorder is not None:
        recorder.skip_stage(stage, reason)


def log(text: str, level: str = "info", stage: Optional[int] = None) -> None:
    recorder = current()
    if recorder is not None:
        recorder.log(text, level, stage)


def note(text: str, **extra: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.note(text, **extra)


def register_artifact(path: Union[str, Path], **kwargs: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.register_artifact(path, **kwargs)


def record_prompt(shot_id: str, prompt: str, **kwargs: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.record_prompt(shot_id, prompt, **kwargs)


def record_api_call(name: str, **kwargs: Any) -> None:
    recorder = current()
    if recorder is not None:
        recorder.record_api_call(name, **kwargs)


# ---------------------------------------------------------------------------
# Console capture
# ---------------------------------------------------------------------------


class _TeeStream(io.TextIOBase):
    """Mirror writes to the original stream and forward complete lines to telemetry."""

    def __init__(self, original: Any, emit: Any) -> None:
        self._original = original
        self._emit = emit
        self._buffer = ""

    def write(self, data: str) -> int:  # type: ignore[override]
        if data:
            try:
                self._buffer += data
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    self._emit(line)
            except Exception:
                pass
            try:
                self._original.write(data)
            except Exception:
                pass
        return len(data or "")

    def flush(self) -> None:  # type: ignore[override]
        try:
            self._original.flush()
        except Exception:
            pass

    def isatty(self) -> bool:  # type: ignore[override]
        try:
            return bool(self._original.isatty())
        except Exception:
            return False

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self._original, "encoding", "utf-8")

    def fileno(self) -> int:  # type: ignore[override]
        return self._original.fileno()


@contextmanager
def capture_console() -> Iterator[None]:
    """Mirror ``stdout``/``stderr`` lines into the active recorder's event log."""
    import sys

    recorder = current()
    if recorder is None:
        yield
        return

    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout = _TeeStream(original_out, lambda line: recorder.log(line))
    sys.stderr = _TeeStream(original_err, lambda line: recorder.log(line, level="error"))
    try:
        yield
    finally:
        for stream, original in ((sys.stdout, original_out), (sys.stderr, original_err)):
            pending = getattr(stream, "_buffer", "")
            if pending.strip():
                recorder.log(pending)
        sys.stdout, sys.stderr = original_out, original_err


# ---------------------------------------------------------------------------
# Event reading (dashboard side)
# ---------------------------------------------------------------------------


def read_events(
    events_path: Union[str, Path],
    since: int = 0,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return parsed events with ``seq > since`` (malformed lines are skipped)."""
    path = Path(events_path)
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if not isinstance(event, dict):
                    continue
                if int(event.get("seq") or 0) <= since:
                    continue
                events.append(event)
    except Exception:
        return events
    if limit is not None and limit >= 0 and len(events) > limit:
        events = events[-limit:]
    return events


def tail_events(
    events_path: Union[str, Path],
    since: int = 0,
    limit: int = 200,
    levels: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Return the newest ``limit`` events after ``since``, optionally filtered by level."""
    events = read_events(events_path, since=since, limit=None)
    if levels:
        allowed = {level.lower() for level in levels}
        events = [event for event in events if str(event.get("level") or "info").lower() in allowed]
    if limit >= 0:
        events = events[-limit:]
    return events
