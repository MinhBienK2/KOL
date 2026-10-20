# 0008. Character Sheet Reference-to-Video (R2V) & Directorial Dispatch

## Context
Commercial TVC production requires consistent character identity across disparate camera angles, actions, and costumes. Previous implementations (ADR 0002, ADR 0006) relied primarily on Image-to-Video (I2V) using single padded First Frames with legacy fragmented turnaround crops. This caused two key limitations:
1. When forcing multi-angle action or dynamic movement (Model shots), I2V's static First Frame constrained the subject's kinematics, producing stiff, unnatural motion.
2. In contrast, running pure Reference-to-Video (R2V) across direct talking-head presenters caused unpredictable head angles and floating gaze, breaking downstream neural lip-sync synchronization.
3. Multi-turnaround asset catalogs suffered from fragmented, low-resolution sub-crops and baked-in emotional expressions that biased diffusion output.

## Decision
1. **Strict 2-Asset Identity Locking Contract**:
   - Each character identity/wardrobe state is defined by strictly two canonical assets:
     - `face_anchor`: An isolated high-resolution close-up portrait locking facial geometry and eye details.
     - `character_sheet`: A multi-panel turnaround grid (5–6 panels: front, 3/4, side profile, rear, close-up, half-body) with empty hands and uniform wardrobe, rendered at 2K/4K resolution.
   - One sheet per outfit: each outfit is a single sheet at `assets/characters/<persona_id>/outfits/<outfit_id>.png`, declared as one `identities` entry in `character.json`; the top-level `character_sheet` names the default outfit.
   - Deprecate legacy fragmented crops (`turnaround_bust`, `turnaround_body`, `full_body_standings`) and expression reference images.
2. **Expression Neutrality**:
   - Both `face_anchor` and `character_sheet` strictly remain emotionally neutral.
   - Facial acting and emotional intensity are exclusively delegated to kinetic prompt descriptions, preventing baked-in expression bias from distorting neutral scenes.
3. **Directorial Dispatch Routing**:
   - The Director and Storyboard engines route each shot based on its `character_role`:
     - `Presenter` (speech beats requiring lip-sync): Routed to **I2V** with an authoritative First Frame to fix head orientation, gaze, and closed mouth posture for downstream Wav2Lip/SadTalker sync.
     - `Model` (visual acting, movement flow, kinetic b-roll): Routed to **R2V** with dual references (`character_sheet` + `face_anchor`) to unlock dynamic 3D body motion while preserving identity.
     - `Product-Only` (macro cinematography): Strictly quarantined under Product Isolation, routing exclusively to Product Hero assets.
4. **Two-Tier Character Sheet Integrity Gate**:
   - **Pre-flight Gate**: Verifies asset completeness, minimum resolution (>= 1080p / 2K), and dual-anchor integrity before initiating diffusion jobs, preventing API credit waste.
   - **Post-flight Gate (Stage 8)**: Audits telemetry prompt ledgers to guarantee 100% character shot anchor binding and 0% product shot leakage.
5. **Multi-Character Architecture**:
   - Establish `kol_main` (Mai Ly) as the primary flagship KOL based on the Warmly Lit Bob Portrait identity across all production campaigns.

## Consequences
- Character shots achieve full kinetic freedom for model shots while maintaining absolute facial stability for presenter lip-sync.
- Clean 2-asset structure simplifies wardrobe additions and eliminates fragmented crop maintenance.
- API spending is protected by pre-flight validation gates.
