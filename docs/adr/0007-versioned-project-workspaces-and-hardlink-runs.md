# 0007. Versioned Project Workspaces and Hardlink Runs

## Context

Previously, the pipeline produced outputs in an unversioned, fragmented multi-tree layout:
- Loose MP4, WAV, and thumbnail files accumulated directly in the `output/` root.
- Intermediary files were scattered across global directories (`output/artifacts/`, `output/audio/`, `output/keyframes/`, `output/raw_clips/`, `output/synced_clips/`).
- While `output/projects/{topic}/{project_id}/` was introduced in ADR 0006, it lacked creative revision versioning. Modifying a script, audio stem, or keyframe either overwrote previous master renders or produced ambiguous unversioned file collisions ("media soup").
- User requirements for full lifecycle isolation dictated that each project must be completely self-contained, isolated by topic, and support iterative creative revisions (`v1`, `v2`, etc.) without losing earlier work or needlessly re-rendering unaffected diffusion clips.

## Decision

1. **Top-Level Projects Hierarchy**:
   All commercial video projects reside under the top-level repository root directory:
   ```
   projects/{topic}/{project_id}/
   ```
   where `{topic}` is drawn from the authoritative `Topic Catalog` (e.g., `fashion_apparel`, `tech_gadgets`, `beauty_skincare`, `home_lifestyle`, `general_commercial`).

2. **In-Project Versioning (`runs/{version}/`)**:
   Each project contains:
   - `project.json`: Project-level metadata (title, topic, active_version, creation timestamp).
   - `input/`: Raw user materials, reference photos, specifications.
   - `runs/{version}/`: Discrete, immutable execution directories (`runs/v1/`, `runs/v2/`, etc.) encapsulating the full end-to-end flow:
     - `master.mp4`: Final 1080x1920 commercial master video.
     - `thumbnail.jpg`: Commercial poster frame.
     - `prompt_ledger.json`: The exact API models, motion/image prompts, aspect ratios, durations, and task IDs sent to AI models (not user chat history).
     - `artifacts/`: The 7 canonical JSON artifacts (`brief.json`, `script.json`, `scene_plan.json`, `asset_manifest.json`, `edit_decisions.json`, `render_report.json`, `publish_log.json`, `storyboard_contact_sheet.jpg`).
     - `keyframes/`: Clean 9:16 keyframes with Telea inpainting applied.
     - `media/`: Subdirectories for `raw_clips/`, `synced_clips/`, and `audio/`.
     - `telemetry/`: `state.json` snapshot and append-only `events.jsonl` activity feed.

3. **Hardlink Asset Inheritance**:
   When branching to a new version (e.g., `v2` after tweaking audio or script), unaffected media assets from `v1` are hardlinked into `v2` (falling back to file copy if across filesystems). This ensures `v2` is 100% self-contained as an independent snapshot while consuming zero additional disk space for reused diffusion clips.

4. **In-Place Resume vs Creative Branching**:
   - Technical failures (network drop, API timeout, rate limits) resume in-place within the active version (`runs/vX/`) via `--from-stage`.
   - Creative revisions (prompt/script/audio adjustments) trigger a new discrete version (`runs/v(X+1)/`).

5. **Clean Slate & Git Tracking**:
   - The legacy `output/` directory is purged.
   - `.gitignore` ignores binary media (`*.mp4`, `*.wav`, `media/`, `keyframes/`) while tracking project metadata, prompt ledgers, and canonical JSON artifacts in Git.

## Consequences

- **Zero Collision & Isolation**: No project or version can overwrite another project's assets.
- **Complete Reproducibility**: Each run records its full generation parameters in `prompt_ledger.json` alongside canonical artifacts.
- **Storage Efficiency**: Hardlinks eliminate redundant storage for re-used diffusion video clips across revisions.
- **Supervisor Dashboard Compatibility**: The supervisor dashboard discovers both project metadata and individual versioned runs seamlessly.
