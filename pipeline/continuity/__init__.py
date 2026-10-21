"""Continuity production path: one shot bible -> reference-built keyframe -> chained I2V clips.

The 8-stage pipeline builds every shot from archetype templates and uses asset files directly as
first frames. This package is the alternative the director agent drives for single-location
videos: the agent writes a Shot Bible, the anchor keyframe is *generated* from reference images
(assets are references, never frames), and every following clip starts on the hand-off frame of
the clip before it (last frame of N == first frame of N+1). Each step writes an artifact and a
review verdict so the agent can approve it before paying for the next step.
"""
