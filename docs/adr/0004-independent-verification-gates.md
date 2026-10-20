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
- Perceptual face-identity similarity was not yet implemented here; see the Face Identity Gate amendment below (the Character Consistency Gate itself still checks keyframe files and watermark cleaning only).

## Amendment: placeholder audit, identity pre-flight audit and the DRAFT status
- **Loudness reads stage 7.** When `audio_mix_report.json` exists and is not older than the master, the Media Quality Gate takes its `compliant` verdict as the loudness authority (the composer's stricter -14 LUFS +/- 1 LU and true-peak test) instead of the +/- 3 LUFS window. The master is still measured, and a report more than 1 LU away from the measurement is rejected as not describing this file. A missing, stale or malformed report falls back to measuring.
- **Identity Pre-flight Gate** (`identity_preflight_gate`) audits stage 4's `identity_preflight.json`: `ok: false` or any `errors` fails; `warnings` (low-resolution references) pass but are listed in the gate details; a missing report passes with a warning (runs predating the pre-flight).
- **Prompt Ledger Audit Gate** (`prompt_ledger_audit_gate`) flags every shot whose Prompt Ledger entry has `degraded_from` set (R2V degraded to a first frame), a placeholder `mode` (`LOCAL_FFMPEG`, `FFMPEG`, `PLACEHOLDER`) or `tts_fallback`; stage 6's `tts_fallback` telemetry items and voice stems that are digital silence for a beat with spoken text count too. The ledger is the live telemetry snapshot overlaid on `prompt_ledger.json` (the director only writes that file after stage 8 passes).
- **Decision: DRAFT, not FAILED.** A master whose only failing gate is the Prompt Ledger Audit is a complete, watchable preview, but it contains generated placeholders and must not be released. Its `overall_status` is `DRAFT`; any other failing gate makes it `FAILED` (which outranks DRAFT). Both halt the pipeline exactly like FAILED did: stage 8 fails, no `publish_log.json` or thumbnail is written, a stale log is removed, and the director's exit code is 3. Distinguishing them lets an operator or agent see that the fix is to regenerate the degraded shots or stems (re-run stage 5 or 6) rather than to repair a defective render.
- The gate count is now 8 (`VERIFICATION_GATE_COUNT`).

## Amendment: Face Identity Gate
- **Gap closed.** The Character Consistency Gate proved keyframe files exist, not that the face on screen is the persona. `face_identity_gate` (gate 9, `VERIFICATION_GATE_COUNT = 9`) measures it with OpenCV's built-in DNN models, no insightface: YuNet (`cv2.FaceDetectorYN`) finds the face, SFace (`cv2.FaceRecognizerSF`) embeds it, similarity is the embedding cosine. Implementation: `pipeline/face_identity.py` (`embed_face`, `identity_similarity`, `sample_video_frames`, `verify_shot_identity`).
- **Scope.** Per shot in `scene_plan.json` whose Character Role is `presenter` or `model` (never `product_only`, Product Isolation), the cleaned keyframe and 3 frames sampled across the raw clip (when on disk) are compared with the Face Anchor from `character.json`. A shot fails when the best similarity of any checked medium is below the threshold. A face missing on a `presenter` shot fails; on a `model` shot it is allowed (back view, crop, hands) but any face that is found must still match. Clip similarity is the best over the sampled frames so one head-turn frame cannot fail an otherwise matching clip. Per-shot results are in `details.shots`.
- **Threshold: 0.363 (cosine)**, OpenCV's documented SFace value (tuned on LFW). Calibration on this repo's personas: the same persona (portrait vs. turnaround-sheet face) scores 0.54 (kol_main) and 0.73 (kol_minhanh), identical image 1.00, different personas 0.14-0.33. The documented value sits in that gap, so it is kept; a looser value (e.g. 0.30) would let a different persona (0.33) pass. Generated faces drift more than photographs, so a deployment that sees false failures should override with `KOL_FACE_SIMILARITY_THRESHOLD` after re-measuring, rather than the default being weakened.
- **Models.** `face_detection_yunet_2023mar.onnx` (232,589 B) and `face_recognition_sface_2021dec.onnx` (38,696,353 B) from the public `opencv/opencv_zoo` repo (Git LFS, `media.githubusercontent.com`), downloaded on first use into `$KOL_MODEL_DIR` or `~/.cache/kol/models` and verified by size and SHA-256 (this rejects the LFS pointer text the raw URL returns). `*.onnx` and `assets/models/` are gitignored.
- **Offline.** Downloads go through `pipeline.offline`. Offline (or any download failure) with the models missing raises `FaceModelsUnavailable`; the gate then passes with `details.status = "unverified"` and a reason instead of crashing. The same applies when `scene_plan.json` / `asset_manifest.json` are absent. A Face Anchor with no detectable face, or a missing anchor file, fails the gate.
