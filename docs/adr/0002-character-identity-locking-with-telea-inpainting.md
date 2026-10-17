# 0002. Character Identity Locking with Telea Inpainting

## Context
AI-generated presenters suffer from severe facial morphing, altered bone structures, and unwanted AI watermarks that degrade commercial trust. Single-prompt generation fails to maintain facial identity across disparate angles and emotional expressions.

## Decision
Inherit DramaClaw's identity locking architecture using `character.json` with composite reference anchors (portrait face anchor, 4-panel bust turnaround, 3-panel body turnaround, and 2x3 expression grid) uploaded to MiniMax OSS as multi-subject references. To eradicate platform watermarks cleanly without blurring the active video frame, apply OpenCV Telea inpainting (`cv2.inpaint` with `cv2.INPAINT_TELEA`) across targeted bottom-right watermark coordinates prior to feeding images into Image-to-Video models.

## Consequences
- Character identity remains locked within single-character visual tolerance across all shots.
- Clean keyframes prevent watermark artifacts from propagating or smearing during video diffusion.
