# Autonomous Commercial Video Pipeline

An autonomous end-to-end commercial video production engine combining OpenMontage orchestration state machines with DramaClaw character identity locking and verification gates.

## Language

### Narrative & Advertising

**TVC**:
Television and digital commercial video format engineered for high conversion across social channels (TikTok, Reels, Shorts).
_Avoid_: Vlog, video clip, movie

**Hook**:
The opening 0–3 second audiovisual shock or provocative problem statement designed to halt viewer scrolling immediately.
_Avoid_: Intro, greeting, preamble

**Pain Point**:
The specific customer frustration dramatized in the script before introducing the product solution.
_Avoid_: Negative feedback, annoyance

**USP**:
Unique Selling Proposition; the key differentiated product features highlighted during the demo beats.
_Avoid_: Selling points, specs list

**CTA**:
Call to Action prompting the viewer to complete a specific commercial action (click link, purchase, limited promo).
_Avoid_: Outro, ending note

### Visual & Generation

**First Frame**:
The canonical high-resolution starting image for an Image-to-Video generation task.
_Avoid_: Thumbnail, cover, preview

**Identity Lock**:
The framework ensuring character facial structure, features, and hair remain invariant across multiple generated shots.
_Avoid_: Face swap, character consistency hack

**Composite Reference**:
A composite visual sheet combining portrait, turnaround panels, and expression grids used as an identity anchor.
_Avoid_: Single reference photo, style guide

**Character Sheet**:
A multi-panel turnaround image capturing a character's physical proportions, hairstyle, and wardrobe across multiple viewing angles with empty hands. One sheet per outfit: each outfit of a character is its own sheet (`assets/characters/<persona_id>/outfits/<outfit_id>.png`), declared as one identity in `character.json`.
_Avoid_: Model sheet, mood board, all-in-one style guide

**Face Anchor**:
An isolated high-resolution close-up portrait used to preserve fine facial geometry and identity fidelity.
_Avoid_: Profile pic, headshot hack, avatar

**R2V**:
Video generation driven by a prompt guided by subject reference images without constraining the initial frame.
_Avoid_: Reference video, S2V, prompt video

**I2V**:
Image-to-Video generation using a locked First Frame and motion prompt to produce short cinematic video clips.
_Avoid_: Text-to-Video, T2V, video diffusion

**Telea Inpainting**:
OpenCV image restoration technique using the Fast Marching Method to remove AI watermark tags from generated keyframes.
_Avoid_: Blur mask, crop, watermark removal

### Audio & Composition

**Lip-sync**:
Frame-accurate synchronization between spoken phonemes and character mouth/lip movement in direct-to-camera presenter shots.
_Avoid_: Dubbing, audio overlay

**Audio Ducking**:
Automatic attenuation of background music volume whenever voiceover speech is actively detected on the timeline.
_Avoid_: Volume sliding, manual fade

**Edit Decision List**:
A structured timeline specification defining sequence, in/out cuts, transitions, audio stems, and caption overlays.
_Avoid_: Edit script, cut plan

**Verification Gate**:
An automated deterministic or perceptual check validating video format, character consistency, or continuity before final release.
_Avoid_: Manual QA, eyeball test

**Media Quality Gate**:
The Verification Gate that scans the master with one ffmpeg pass (`blackdetect`, `freezedetect`, `ebur128`) and rejects black picture, frozen/held still frames, silence, off-target loudness (-14 LUFS ± 3) and clipping.
_Avoid_: Loudness check, black frame check

### Directorial Strategy & Market Intelligence

**Competitor Research & Whitespace Analysis**:
Automated competitive discovery extracting saturated creative clichés and identifying untapped visual angles and viral hooks across TikTok/Reels/Shorts.
_Avoid_: Competitor copying, generic market research

**Directorial Archetype**:
Product-category tailored visual and auditory production methodology (Fashion Lookbook, Tech Teardown, Beauty Glow, Cozy Sanctuary, General DR).
_Avoid_: One-size-fits-all script, hardcoded template

**Character Role Matrix**:
Distinction between Presenter (direct talking-head with lip-sync), Model (visual acting, movement flow, off-camera VO/music only), and Product-Only (macro cinematography with suppressed character references).
_Avoid_: Talking-head obsession, forced face in macro shots

**Directorial Dispatch**:
The automated routing mechanism mapping each shot's Character Role to its optimal generation mode (Presenter to I2V with First Frame, Model to R2V with Character Sheet and Face Anchor, and Product-Only to Product Hero Reference).
_Avoid_: Hardcoded video mode, manual shot toggling

**Audio Strategy Routing**:
Dynamic stem selection between On-Camera Speech, Off-Camera Voiceover, Pure Music + SFX Beat-Sync, and ASMR Foley Hybrid.
_Avoid_: Monolithic dubbing, silence on non-speech shots

**DramaClaw Spatial Scene Contract**:
Explicit staging contract establishing camera choreography, lighting color temperature (Kelvin), depth zones, and spatial anchors across continuous shots.
_Avoid_: Floating camera, disjointed lighting cuts

**OpenMontage Slideshow Risk Gate**:
A 6-dimension automated evaluator scoring repetition, decorative visuals, weak motion, weak shot intent, typography overreliance, and unsupported cinematic claims to prevent static photo slideshow outputs.
_Avoid_: Ken Burns slideshow, static image zoompan

### Observability & Supervision

**Run Telemetry**:
The durable per-run record of pipeline execution: stage status, timing, progress, produced artifacts, generation prompts, and external API calls, written by the pipeline itself.
_Avoid_: Debug prints, terminal scrollback

**Run State Snapshot**:
The atomically rewritten `state.json` describing the current state of a run (stage statuses, progress, artifact index, prompt ledger), read by the supervisor dashboard.
_Avoid_: Status file, progress bar state

**Activity Feed**:
The append-only `events.jsonl` stream of structured pipeline events (stage transitions, progress, artifacts, prompts, API calls, console lines) pushed live to the dashboard over SSE.
_Avoid_: Log file, stdout

**Prompt Ledger**:
The per-shot record of the exact generation prompt sent to the video/keyframe model together with its parameters (mode I2V/T2V, model, aspect ratio, requested duration, first frame, task id, attempts, output file).
_Avoid_: Prompt history, chat log

**Stage Status Derivation**:
Reconstructing each stage's status from the presence of its canonical artifacts, used for runs recorded before Run Telemetry existed.
_Avoid_: Fake telemetry, default status

**Supervisor Dashboard**:
The browser UI that reads a run's telemetry and canonical artifacts to show live stage progress, artifacts, prompts, verification gates, and playback of all produced media.
_Avoid_: Admin panel, monitoring app

**Path Escape**:
A file request that resolves outside the run workspace (and its declared asset roots) and is therefore refused by the dashboard API.
_Avoid_: Directory traversal, unsafe path

### Project & Workspace Architecture

**Project Workspace**:
A self-contained production directory encapsulating all canonical artifacts, keyframes, raw diffusion clips, synced audio, and master video files for a single commercial film campaign under its domain topic (`projects/{topic}/{project_id}/`).
_Avoid_: Fragmented multi-tree output, global temp directory, flat campaign dumping

**Project Iteration (Run Version)**:
A discrete, immutable execution record (`runs/v1/`, `runs/v2/`) within a Project Workspace containing the exact prompt flow, stage artifacts, and media rendered for that specific creative revision.
_Avoid_: In-place overwriting of previous master renders, unversioned media soup
**Topic Catalog**:
The authoritative registry and queryable seam mapping domain archetypes and themes (Fashion Apparel, Tech Gadgets, Beauty Skincare, Home Lifestyle, General Commercial) to wardrobe profiles, photorealistic environments, and active projects.
_Avoid_: Hardcoded category switch-cases, scattered global dictionaries

### Character Consistency & Staging Isolation

**Product Isolation**:
The architectural rule ensuring shots designated as `product_only` strictly exclude human character facial anchors, routing purely to product hero visual references.
_Avoid_: Facial contamination on macro shots, character injection into product b-roll

**Campaign Costume Consistency**:
Uniformly binding character shots within a campaign to the script's canonical styling and costume directive to prevent wardrobe hopping between disparate outfits across scenes without requiring static wardrobe asset catalogs.
_Avoid_: Random costume mixing, hardcoded wardrobe folders

**Expression Neutrality**:
The principle requiring all character visual anchors to remain emotionally neutral, delegating all dynamic acting and facial expressions exclusively to kinetic prompt descriptions.
_Avoid_: Expression sheets, baked-in smiles, emotion swapping

**Character Sheet Integrity Gate**:
A two-tier verification gate enforcing strict pre-flight asset validation (minimum 2K/4K resolution, dual-anchor completeness) and post-flight telemetry lineage auditing across all character shots.
_Avoid_: Asset checklist, image sanity check, manual inspection

**Shot Timing Plan**:
The composer's per-shot decision that a shot lasts `max(beat estimated duration, voice stem length)`, is cut from the start of the generated 6s/10s clip, is slowed at most 1.25x only when the clip is genuinely shorter, and is recorded under `shots` in `edit_decisions.json`. Frozen frames are a last resort, never the default padding.
_Avoid_: Clip padding, freeze-frame fill, tpad

**Draft Master**:
A complete master whose only failing gate is the Prompt Ledger Audit Gate, meaning it contains placeholders (a degraded generation mode, a local ffmpeg stand-in or silent TTS fallback). Reported as `overall_status: DRAFT`: watchable as a preview, never published.
_Avoid_: Partial pass, soft fail, warning-only release

**Face Identity Gate**:
A verification gate that compares the face in each presenter/model shot's keyframe and sampled raw-clip frames against the Face Anchor using YuNet detection and SFace embedding cosine similarity (threshold 0.363, `KOL_FACE_SIMILARITY_THRESHOLD` to override). Fails on a mismatching face or a missing face on a presenter shot; product-only shots are skipped; reports `unverified` (passes) when the models cannot be downloaded offline.
_Avoid_: Keyframe file check, manual likeness review, insightface
