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

**Audio Strategy Routing**:
Dynamic stem selection between On-Camera Speech, Off-Camera Voiceover, Pure Music + SFX Beat-Sync, and ASMR Foley Hybrid.
_Avoid_: Monolithic dubbing, silence on non-speech shots

**DramaClaw Spatial Scene Contract**:
Explicit staging contract establishing camera choreography, lighting color temperature (Kelvin), depth zones, and spatial anchors across continuous shots.
_Avoid_: Floating camera, disjointed lighting cuts

**OpenMontage Slideshow Risk Gate**:
A 6-dimension automated evaluator scoring repetition, decorative visuals, weak motion, weak shot intent, typography overreliance, and unsupported cinematic claims to prevent static photo slideshow outputs.
_Avoid_: Ken Burns slideshow, static image zoompan
