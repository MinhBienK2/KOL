# ADR 0009: Stage 5 renders on the ComfyUI gateway (Pika H3 Flex on MiniMax H3)

- Status: Accepted
- Date: 2026-11-07
- Affects: Stage 5 (video), `pipeline/video_engine.py`, `pipeline/comfy_video.py`, `pipeline/comfy_ui2api.py`, `tools/generate_video.py`

## Context

Stage 5 used to render every shot with MiniMax Hailuo-2.3 over HTTP (`/v1/media/video`), with a
separate `S2V-01` model for reference-to-video. That gateway is no longer usable from this
machine: the agent token is rejected (`invalid_api_key`) and `/v1/media/image` no longer exists,
so the video path could not be exercised at all.

The available alternative is the **Comfy Colab Kit gateway** (`https://gate.dongmynghedaibai.com`),
which runs *Pika H3 Flex on MiniMax H3* on a Colab L4 GPU with local weights. It exposes three
official Comfy-Org workflows:

| workflow | meaning |
|---|---|
| `pika-h3-flex-t2v` | text to video (no image) |
| `pika-h3-flex-fl2va` | image to video: first frame, optionally plus a last frame |
| `pika-h3-flex-ref2va` | reference to video: up to 9 reference images (`<Picture 1>`, …) |

Each clip is H.264 plus a **native stereo audio track** (MiniMax H3 renders video and ambience in
one pass).

## Decision

1. **Stage 5 renders on the ComfyUI gateway; MiniMax no longer produces video.** MiniMax keeps
   Stage 6 (TTS/ASR) and can still produce Stage-4 keyframes. The MiniMax video code path
   (`submit_video_job` against `/v1/media/video`) is deleted, not kept behind a flag.
2. **The mode decides the workflow, the data decides the mode:**

   | shot data | mode | workflow |
   |---|---|---|
   | identity-locked first frame (Flow2API frame drawn from the face anchor) | `I2V` | `fl2va` |
   | face anchor but no locked frame | `R2V` | `ref2va` |
   | first frame, no identity intent | `I2V` | `fl2va` |
   | no image at all | `T2V` | `t2v` |

   `KOL_R2V_STRATEGY` keeps its explicit overrides (`subject_reference`, `synth_i2v`,
   `face_anchor_i2v`); the new default `auto` picks per shot as above.
3. **The Prompt Ledger records the prompt that was actually sent.** `ref2va` needs the anchor
   bound to the image (`<Picture 1>`), so the engine composes that binding and records the
   composed text, not the pre-binding prompt.
4. **Resolution and length follow the model's contract.** Pika renders whole seconds between 5
   and 15 on a 17-frame grid (`5s -> 124 frames -> 5.17s`) and wants sizes that are multiples of
   32; the engine therefore computes `width`/`height` from the shot's aspect ratio (or the first
   frame's own size) and `length` from the requested duration.

## Implementation notes

- The gateway serves the workflows as **UI-format** templates with subgraphs, while `POST /prompt`
  only accepts API-format graphs. `pipeline/comfy_ui2api.py` converts them (subgraph expansion,
  `widgets_values_named`, dotted dynamic-input paths such as `values.a`).
- The gateway is behind **Cloudflare Access**: every request needs the agent token *and*
  `CF-Access-Client-Id` / `CF-Access-Client-Secret`. Without them Cloudflare answers with its
  sign-in page (HTTP 200 + HTML), which looks like a broken gateway.
- A queued graph is resumed, not re-paid: the ComfyUI `prompt_id` is stored next to the clip
  (`<shot>.task.json`) exactly like the old MiniMax `task_id`.

## Consequences

- Clips carry audio; Stage 7 can mix that ambience with the voice stem.
- Identity for character shots comes from a *reference image* (`ref2va`), not from a first frame,
  unless Stage 4 produced an identity-locked frame.
- The video cost unit changed: the estimate keys on `Pika-H3-Flex-MiniMax-H3`.
