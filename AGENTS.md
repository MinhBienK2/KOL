# AGENTS.md: AI Director Agent Architecture & Production Harness

## 1. Production Harness Surface (Harness² Integration)
The AI Director Agent operates under a modularized, optimized harness surface:
- **`DIRECTOR_AGENT_PROMPT.md`**: Master unified directorial prompt and state machine.
- **`harness/systemprompt.md`**: Core identity, mission, and 8-stage pipeline orchestration.
- **`harness/guardrails.md`**: Technical standards (1080x1920, H.264/AAC, -14 LUFS, lip-sync <50ms) and 8 Quality Verification Gates (ADR 0004).
- **`harness/tool_guidance.md`**: Strict CLI contract for `tools/director.py`, `--json` interface, and directorial intervention flags.
- **`harness/error_recovery.md`**: Autonomous error diagnosis and recovery protocol across exit codes 0..4, `--from-stage`, `--inject`, and `--new-version`.
- **`harness/scripts/`**: Deterministic helper scripts (`verify_run.py`, `validate_artifact.py`).

## 2. Agent Skills & Governance
- **Issue tracker:** GitHub issues via `gh` CLI. See `docs/agents/issue-tracker.md`.
- **Triage labels:** Canonical triage label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.
- **Domain docs:** Single-context architecture (`CONTEXT.md` and `docs/adr/` at repo root). See `docs/agents/domain.md`.
