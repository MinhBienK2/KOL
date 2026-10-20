# 0004. Independent Quality Verification Gates

## Context
Autonomous video generation without automated verification yields silent defects: incorrect aspect ratios, corrupt audio streams, frame tearing, character drift, or broken continuity between adjacent scenes. Releasing videos without verification breaks production trust.

## Decision
Establish three decoupled verification gates prior to releasing final artifacts:
1. Technical Integrity Gate: Uses `ffprobe` to verify video dimensions (1080x1920 for 9:16 vertical video), container standards (H.264 video, AAC 48kHz audio), duration alignment, and nonzero stream bitrates.
2. Character Consistency Gate: Verifies that identity markers across early and late presenter shots match `character.json` profile constraints.
3. Continuity Gate: Verifies rhythm and absence of jump-cut disruptions across scene transitions.
Failing any critical gate halts the pipeline and triggers targeted regeneration.

## Consequences
- No defective master renders reach the publication artifact catalog.
- Release manifests provide explicit audit trails in `render_report.json` and `publish_log.json`.

## Amendment: Media Quality Gate and enforced halting
- An additional gate, the Media Quality Gate, runs `blackdetect`, `freezedetect` and `ebur128` over the master in one ffmpeg pass. It fails on more than 1s of black picture, a frozen hold of 2s or more (or over 20% of the runtime held on still frames), silence, integrated loudness outside -14 LUFS ± 3, or true peak above 0 dBTP. The Technical Integrity Gate alone proved only that the container was well formed.
- Halting is enforced: when any gate fails, `render_report.json` is written with `overall_status: FAILED`, any `publish_log.json` and thumbnail from an earlier PASSED attempt are not refreshed (the stale log is removed), the run is recorded as failed at stage 8, and `tools/director.py` exits with code 3 so an agent can tell a rejected master from a crashed stage.
- Not yet implemented: perceptual face-identity similarity (the Character Consistency Gate still checks keyframe files and watermark cleaning, not embeddings).

## Amendment: placeholder audit, identity pre-flight audit and the DRAFT status
- **Loudness reads stage 7.** When `audio_mix_report.json` exists and is not older than the master, the Media Quality Gate takes its `compliant` verdict as the loudness authority (the composer's stricter -14 LUFS +/- 1 LU and true-peak test) instead of the +/- 3 LUFS window. The master is still measured, and a report more than 1 LU away from the measurement is rejected as not describing this file. A missing, stale or malformed report falls back to measuring.
- **Identity Pre-flight Gate** (`identity_preflight_gate`) audits stage 4's `identity_preflight.json`: `ok: false` or any `errors` fails; `warnings` (low-resolution references) pass but are listed in the gate details; a missing report passes with a warning (runs predating the pre-flight).
- **Prompt Ledger Audit Gate** (`prompt_ledger_audit_gate`) flags every shot whose Prompt Ledger entry has `degraded_from` set (R2V degraded to a first frame), a placeholder `mode` (`LOCAL_FFMPEG`, `FFMPEG`, `PLACEHOLDER`) or `tts_fallback`; stage 6's `tts_fallback` telemetry items and voice stems that are digital silence for a beat with spoken text count too. The ledger is the live telemetry snapshot overlaid on `prompt_ledger.json` (the director only writes that file after stage 8 passes).
- **Decision: DRAFT, not FAILED.** A master whose only failing gate is the Prompt Ledger Audit is a complete, watchable preview, but it contains generated placeholders and must not be released. Its `overall_status` is `DRAFT`; any other failing gate makes it `FAILED` (which outranks DRAFT). Both halt the pipeline exactly like FAILED did: stage 8 fails, no `publish_log.json` or thumbnail is written, a stale log is removed, and the director's exit code is 3. Distinguishing them lets an operator or agent see that the fix is to regenerate the degraded shots or stems (re-run stage 5 or 6) rather than to repair a defective render.
- The gate count is now 8 (`VERIFICATION_GATE_COUNT`).
