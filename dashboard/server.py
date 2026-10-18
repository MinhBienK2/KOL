"""Supervisor dashboard HTTP layer: REST + SSE + artifact/file serving + static UI.

Route order matters: the specific ``/events``, ``/stream``, ``/file`` and ``/artifact`` routes are
registered before the bare ``/api/runs/{run_id:path}`` view-model route so that a run id may
contain slashes without swallowing the sub-resources.

No third-party dependencies beyond FastAPI/uvicorn (already used by the pipeline).
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dashboard import runs as runs_module
from pipeline import telemetry as telemetry_module

SSE_POLL_SECONDS = 0.5
SSE_HEARTBEAT_SECONDS = 15.0
SSE_MAX_SECONDS = 3600.0
SSE_BATCH_LIMIT = 500
DEFAULT_EVENT_LIMIT = 1000
MAX_EVENT_LIMIT = 5000
STREAM_CHUNK_SIZE = 1 << 20
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_LEVELS_RE = re.compile(r"^[A-Za-z]+$")

STATIC_DIRNAME = "static"

FALLBACK_INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>KOL Pipeline Supervisor</title></head>
<body>
<h1>KOL Pipeline Supervisor API</h1>
<p>The dashboard UI assets are missing (dashboard/static/index.html). The JSON API is available:</p>
<ul>
  <li><a href="/api/health">/api/health</a></li>
  <li><a href="/api/runs">/api/runs</a></li>
  <li>/api/runs/&lt;run_id&gt;</li>
  <li>/api/runs/&lt;run_id&gt;/events</li>
  <li>/api/runs/&lt;run_id&gt;/stream</li>
  <li>/api/runs/&lt;run_id&gt;/file?path=&lt;rel_path&gt;</li>
  <li>/api/runs/&lt;run_id&gt;/artifact?name=&lt;artifact.json&gt;</li>
</ul>
</body></html>
"""


def _resolve_ref_or_404(run_id: str, base_dir: Optional[Path]) -> runs_module.RunRef:
    try:
        return runs_module.resolve_run(run_id, base_dir)
    except runs_module.RunNotFound:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")


def _parse_range(header: Optional[str], size: int) -> Optional[Tuple[int, int]]:
    """Parse a single ``bytes=`` range header against ``size`` (``None`` when unsatisfiable)."""
    if not header or size <= 0:
        return None
    match = _RANGE_RE.fullmatch(header.strip())
    if not match:
        return None
    start_raw, end_raw = match.group(1), match.group(2)
    if start_raw == "" and end_raw == "":
        return None
    if start_raw == "":
        length = int(end_raw)
        if length <= 0:
            return None
        start = max(0, size - length)
        end = size - 1
    else:
        start = int(start_raw)
        if start >= size:
            return None
        end = int(end_raw) if end_raw else size - 1
        end = min(end, size - 1)
    if start > end:
        return None
    return start, end


def _iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with open(path, "rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(STREAM_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _file_response(path: Path, request: Request) -> Response:
    """Serve a file, honouring a single ``Range`` request (used for video seeking)."""
    try:
        size = path.stat().st_size
    except OSError:
        raise HTTPException(status_code=404, detail="file missing")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    range_header = request.headers.get("range")
    if range_header:
        parsed = _parse_range(range_header, size)
        if parsed is None:
            return Response(
                status_code=416,
                headers={"content-range": f"bytes */{size}", "accept-ranges": "bytes"},
            )
        start, end = parsed
        headers = {
            "content-range": f"bytes {start}-{end}/{size}",
            "accept-ranges": "bytes",
            "content-length": str(end - start + 1),
        }
        return StreamingResponse(_iter_file(path, start, end), status_code=206, media_type=media_type, headers=headers)
    headers = {"accept-ranges": "bytes", "content-length": str(size)}
    return StreamingResponse(_iter_file(path, 0, max(0, size - 1)), media_type=media_type, headers=headers)


def _parse_levels(levels: Optional[str]) -> Optional[List[str]]:
    if not levels:
        return None
    parsed = [level.strip().lower() for level in levels.split(",") if level.strip()]
    parsed = [level for level in parsed if _LEVELS_RE.match(level) and level != "all"]
    return parsed or None


def create_app(
    base_dir: Optional[Union[str, Path]] = None,
    *,
    static_dir: Optional[Union[str, Path]] = None,
) -> FastAPI:
    """Build the supervisor dashboard app over ``base_dir`` (``OUTPUT_DIR`` by default)."""
    resolved_base = runs_module.resolve_base_dir(base_dir)
    app = FastAPI(title="KOL Pipeline Supervisor", version="1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.base_dir = resolved_base

    static_path = Path(static_dir).resolve() if static_dir else (Path(__file__).resolve().parent / STATIC_DIRNAME)
    index_path = static_path / "index.html"
    if static_path.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    # ---------------------------------------------------------------- meta

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        try:
            run_count = len(runs_module.discover_runs(resolved_base))
        except Exception:
            run_count = 0
        return {"ok": True, "base_dir": str(resolved_base), "runs": run_count}

    @app.get("/api/runs")
    def list_runs() -> Dict[str, Any]:
        return {"runs": runs_module.discover_runs(resolved_base)}

    # ------------------------------------------------------------ sub-resources

    @app.get("/api/runs/{run_id:path}/events")
    def run_events(
        run_id: str,
        since: int = Query(0, ge=0),
        limit: int = Query(DEFAULT_EVENT_LIMIT, ge=0),
        levels: Optional[str] = Query(None),
    ) -> Dict[str, Any]:
        run_ref = _resolve_ref_or_404(run_id, resolved_base)
        events = runs_module.read_run_events(run_ref)
        last_seq = 0
        for event in events:
            try:
                last_seq = max(last_seq, int(event.get("seq") or 0))
            except (TypeError, ValueError):
                continue
        allowed = _parse_levels(levels)
        selected: List[Dict[str, Any]] = []
        for event in events:
            try:
                if int(event.get("seq") or 0) <= since:
                    continue
            except (TypeError, ValueError):
                continue
            if allowed is not None and str(event.get("level") or "info").lower() not in allowed:
                continue
            selected.append(event)
        if limit >= 0:
            selected = selected[-limit:] if limit else []
        return {"events": selected, "last_seq": last_seq}

    @app.get("/api/runs/{run_id:path}/stream")
    async def run_stream(
        run_id: str,
        request: Request,
        since: int = Query(0, ge=0),
    ) -> StreamingResponse:
        run_ref = _resolve_ref_or_404(run_id, resolved_base)

        async def event_stream() -> AsyncIterator[str]:
            cursor = int(since)
            events_path = runs_module.run_events_path(run_ref)
            last_size: Optional[int] = None
            last_probe = time.monotonic()
            last_heartbeat = time.monotonic()
            deadline = time.monotonic() + SSE_MAX_SECONDS
            while True:
                if await request.is_disconnected():
                    break
                now = time.monotonic()
                if events_path is None and now - last_probe >= 5.0:
                    events_path = runs_module.run_events_path(run_ref)
                    last_probe = now
                batch: List[Dict[str, Any]] = []
                if events_path is not None:
                    try:
                        size: Optional[int] = events_path.stat().st_size
                    except OSError:
                        size = None
                    if size != last_size:
                        last_size = size
                        batch = telemetry_module.read_events(
                            events_path, since=cursor, limit=SSE_BATCH_LIMIT
                        )
                if batch:
                    for event in batch:
                        try:
                            cursor = max(cursor, int(event.get("seq") or 0))
                        except (TypeError, ValueError):
                            continue
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    last_heartbeat = time.monotonic()
                elif now - last_heartbeat >= SSE_HEARTBEAT_SECONDS:
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.monotonic()
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(SSE_POLL_SECONDS)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "cache-control": "no-cache, no-transform",
                "connection": "keep-alive",
                "x-accel-buffering": "no",
            },
        )

    @app.get("/api/runs/{run_id:path}/file")
    def run_file(run_id: str, request: Request, path: str = Query(...)) -> Response:
        run_ref = _resolve_ref_or_404(run_id, resolved_base)
        try:
            resolved = runs_module.safe_resolve(run_ref, path)
        except runs_module.PathEscape:
            raise HTTPException(status_code=403, detail="path escapes the run root")
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        return _file_response(resolved, request)

    @app.get("/api/runs/{run_id:path}/artifact")
    def run_artifact(run_id: str, name: str = Query(...)) -> Response:
        run_ref = _resolve_ref_or_404(run_id, resolved_base)
        rel_path = runs_module.locate_artifact(run_ref, name)
        if rel_path is None:
            raise HTTPException(status_code=404, detail=f"artifact not found: {name}")
        data = runs_module.load_json(rel_path)
        if data is None:
            raise HTTPException(status_code=404, detail=f"artifact is missing or not valid JSON: {name}")
        return JSONResponse(data)

    # ------------------------------------------------------------- view model

    @app.get("/api/runs/{run_id:path}")
    def run_view(run_id: str) -> Dict[str, Any]:
        run_ref = _resolve_ref_or_404(run_id, resolved_base)
        return runs_module.build_view(run_ref)

    # -------------------------------------------------------------------- UI

    @app.get("/", response_class=HTMLResponse)
    def index() -> Response:
        if index_path.is_file():
            return FileResponse(str(index_path), media_type="text/html")
        return HTMLResponse(FALLBACK_INDEX_HTML)

    return app
