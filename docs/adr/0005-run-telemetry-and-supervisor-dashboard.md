# 0005. Run Telemetry and Live Supervisor Dashboard

## Context

The 8-stage pipeline is only observable through `print()` to a terminal. A supervisor
watching a run cannot answer basic questions without grepping stdout and opening JSON files
by hand:

- Which step is the agent executing right now, and how far along is it (`shot 3/6`)?
- What did each step produce, and where is that file?
- Which exact video/generation prompt was sent for shot `XX`, against which model, with which
  first frame, how many retries, and which task id came back?
- Why did the run stop?

Legacy campaigns on disk (`output/artifacts/campaign_*`) also carry no run history, so every
run is a black box after the fact.

## Decision

Introduce a first-class observability layer, split in two halves that are independently
testable:

1. `pipeline/telemetry.py` — in-pipeline recorder producing durable run state.
2. `dashboard/` — a FastAPI + static-web dashboard that reads that state (and the canonical
   artifacts) and exposes it as a REST/SSE API plus a browser UI.

### 1. Telemetry layout and schemas (frozen contract)

For every run:

```
{workspace.root}/telemetry/state.json     # atomic snapshot, rewritten on every event
{workspace.root}/telemetry/events.jsonl   # append-only structured event stream
```

`workspace.root` = `output/projects/{topic}/{project_id}` for workspace runs, `output/` for
runs without a workspace. Telemetry is gitignored (only `**/artifacts/` is tracked).

`state.json` (schema_version 1) keys:

| Key | Meaning |
|---|---|
| `schema_version` | `1` |
| `project_id`, `topic` | Run identity |
| `status` | `unknown` / `running` / `completed` / `failed` |
| `run_index` | Attempt counter (incremented by `start_run`) |
| `run_meta` | campaign_id, product_name, archetype, video_mode, resume_from_stage, paths |
| `workspace_root`, `artifacts_dir`, `master_video_path`, `thumbnail_path` | Absolute paths |
| `first_started_at`, `last_started_at`, `finished_at`, `elapsed_seconds` | Timing |
| `current_stage` | Stage currently running (or `null`) |
| `stages` | Always 8 entries: `stage,key,title,status,started_at,finished_at,duration_seconds,progress,message,error,items,artifacts` |
| `artifact_index` | `rel_path -> {name,rel_path,abs_path,kind,size_bytes,exists,stage,label,written_at}` |
| `prompts` | `shot_id -> {shot_id,stage,prompt,mode,model,aspect_ratio,duration_requested,first_frame,task_id,attempts,output_rel_path,size_bytes,first_seen_at,updated_at}` |
| `api_calls` | Newest 200 calls: `{name,endpoint,method,status,ok,duration_seconds,shot_id,request,response,ts}` (credentials redacted) |
| `counters` | `{events,errors,warnings}` |
| `last_event` | `{seq,ts,type,stage,level,text}` |

`events.jsonl` — one JSON object per line, strictly monotonic `seq`:

```json
{"seq":42,"ts":"2026-10-18T09:00:00.000000Z","type":"stage_progress","stage":5,"level":null,"text":"shot_02 retrying","payload":{}}
```

Event types: `run_start`, `run_complete`, `run_failed`, `stage_start`, `stage_progress`,
`stage_message`, `stage_complete`, `stage_failed`, `stage_skipped`, `log`, `note`,
`artifact`, `prompt`, `api_call`.

### 2. Stage catalog is single-source-of-truth

`telemetry.STAGE_CATALOG` owns the 8 stage identities (number, key, title); `pipeline/director.py`
renders its banners from it instead of duplicating titles. Modules resolve their stage number via
`telemetry.stage_number("<key>")`.

### 3. Instrumentation rules

- Instrumentation MUST be fail-safe and MUST be a no-op when no recorder is active
  (`with telemetry.use_recorder(recorder)`), so every stage module keeps working standalone
  and all existing unit tests keep passing unchanged.
- `director.run_pipeline` installs the recorder plus `telemetry.capture_console()`, which mirrors
  existing `print()` output into the event log. New instrumentation therefore adds *structure*
  (`stage_*`, `prompt`, `api_call`, `artifact`) on top of the existing console trail.
- Every stage emits `start_stage` / (`stage_progress` …) / `complete_stage|fail_stage`; skipped
  stages in a `--from-stage N` resume emit `stage_skipped` so the UI shows them as intentionally
  skipped rather than pending.
- Thread-safety is mandatory: stage 5 renders shots on a thread pool.

### 4. Dashboard

```
dashboard/
├── runs.py        # run discovery, artifact→stage derivation, view-model builder
├── server.py      # FastAPI app: REST + SSE + file serving + static UI
└── static/        # index.html, app.js, style.css (vanilla JS, no build step)
tools/dashboard.py # CLI: serve / --list / --json
```

Run discovery covers both layouts present on disk:

| Layout | Root | `run_id` |
|---|---|---|
| workspace | `output/projects/{topic}/{project_id}/` | `{topic}/{project_id}` |
| legacy | `output/artifacts/{project_id}/` (dirs only) | `{project_id}` |

Legacy runs have no telemetry, so stage status is derived from canonical artifacts:
1 `brief.json`, 2 `script.json`, 3 `scene_plan.json`, 4 `asset_manifest.json` with keyframes,
5 `raw_video_clips` present, 6 `audio_stems` + `synced_video_clips` present,
7 `edit_decisions.json` + master video file, 8 `render_report.json`.

REST API (all under the run's own root — no path escapes):

| Endpoint | Returns |
|---|---|
| `GET /api/health` | `{ok, base_dir, runs}` |
| `GET /api/runs` | Run summaries for the sidebar |
| `GET /api/runs/{run_id:path}` | Full view model (below) |
| `GET /api/runs/{run_id:path}/events?since=&limit=&levels=` | Structured events after `since` |
| `GET /api/runs/{run_id:path}/stream?since=` | SSE feed of new events + heartbeats |
| `GET /api/runs/{run_id:path}/file?path=` | Artifact/media bytes (Range supported for video) |
| `GET /api/runs/{run_id:path}/artifact?name=` | Parsed JSON artifact |
| `GET /` , `/static/*` | Dashboard UI |

View-model highlights: `run` (identity/status/timing/progress), `stages[8]`, `artifacts[]`,
`prompts[]` (verbatim prompt + auto-split directive segments + API parameters per shot),
`shots[]` (storyboard + script beat + keyframe/clip/synced/voice URLs), `gates[]`, `media[]`,
parsed `brief`/`research`/`concept`/`script`/`scene_plan`/`edit_decisions`/`render_report`/
`publish_log`, and `events` counters. URLs are always
`/api/runs/{run_id}/file?path=<rel_path_within_run_root>`.

UI requirements (supervisor-facing):
- Live banner: current stage, current item (`shot 3/6`), last activity line, elapsed time.
- 8-step stepper with status/duration/progress/message/error and per-stage artifact links.
- Live activity feed (SSE) with level filter and autoscroll.
- Per-step detail panels: research/brief, script beats, storyboard shots with the **exact
  generation prompt per shot** (copy button) plus camera/lighting/color-temp and slideshow-risk,
  keyframe gallery, rendered clips, audio stems, master timeline/edit decisions, verification
  gates, publish metadata.
- Playback of every video/audio artifact and inline preview of images.

### 5. Security

API keys and bearer tokens MUST be redacted before persistence (`telemetry.redact`), and file
serving MUST reject any path resolving outside the run root.

## Consequences

- A supervisor can watch a run live in a browser and reconstruct any past run from
  `state.json` / `events.jsonl` without terminal access.
- Every prompt, API call and retry is auditable after the fact.
- Runs predating telemetry are still fully monitorable through artifact derivation.
- Cost: the pipeline now writes one extra JSON snapshot plus an append-only log per run, and
  stage modules carry thin telemetry calls (no-ops without a recorder).
