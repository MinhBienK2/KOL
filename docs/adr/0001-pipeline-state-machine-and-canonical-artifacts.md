# 0001. Pipeline State Machine and Canonical Artifacts

## Context
Commercial video generation requires coordination across ideation, copywriting, storyboard layout, asset creation, video rendering, speech generation, and final post-production assembly. Without a formal state machine and rigid artifact schemas, failures in intermediate stages contaminate subsequent renders and prevent deterministic recovery.

## Decision
Adopt OpenMontage's 7-stage instruction-driven pipeline architecture adapted into an 8-step unified commercial pipeline for KOL. Every stage emits a typed, canonical artifact persisted on disk (`brief.json`, `script.json`, `scene_plan.json`, `asset_manifest.json`, `edit_decisions.json`, `render_report.json`, `publish_log.json`). Stages cannot advance until their prerequisite artifacts pass validation schemas.

## Consequences
- Every run is reproducible and inspectable from intermediate JSON manifests.
- Pipeline execution can resume from any completed stage without re-rendering expensive video or keyframe assets.
