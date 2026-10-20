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
