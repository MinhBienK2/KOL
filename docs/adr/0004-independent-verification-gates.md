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
