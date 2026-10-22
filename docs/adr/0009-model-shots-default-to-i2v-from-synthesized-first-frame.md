# 0009. Model Shots Default to I2V from the Synthesized First Frame

Status: accepted (2026-10-23). Amends ADR 0008, decision 3 (Directorial Dispatch) for the Model role.

## Context

ADR 0008 routed every Model shot to R2V (MiniMax S2V-01 with `character_sheet` + `face_anchor`) for freer body motion.
Since then Stage 4 synthesizes a scene first frame for every shot from the face anchor, the product hero and the shot
prompt, and the First-frame gate requires it. Four preproduction QA rounds (`projects/qa/preprod/ledger.md`, four
products and archetypes) showed what this routing costs in practice:

- S2V-01 receives only the face. The product, set, wardrobe and light are redrawn from text, so a bicycle, lamp,
  tote or jar in a Model shot did not match the hero photo. In every round the director had to override the Model
  shots to `i2v` by hand.
- The synthesized first frame was still paid for and gated for those shots, then not sent.
- The shots Model plays in ads are short (2.5–4 s of a 6 s clip) and rarely need large body motion; the failures
  were wrong products and sets, not stiff motion.

## Decision

1. `_shot_dispatch` routes Presenter **and Model** shots to **I2V** from the synthesized first frame. Product-Only
   still routes to the product hero.
2. R2V is an explicit director's choice: `generation_mode: "r2v"` in `--shot-overrides`, for a shot that needs large
   body motion where the product does not fill the frame. Stage 5 then appends the scene sentences
   (action, SET, LIGHT, WEAR) to the motion prompt (`video_prompt_for`), and `tools/prompt_pack.py` warns
   `r2v_without_product_reference`.
3. On-camera speech can never be R2V (unchanged; Stage 3 refuses it).

## Consequences

- Product, set and wardrobe in Model shots come from a frame QA can approve in the prompt pack, not from text.
- The character sheet is resolved and pre-flighted only when a shot opts into R2V.
- Motion in Model shots is bounded by I2V; directors who need a run, spin or dance opt into R2V per shot.
