# 0003. Neural TTS and Audio Ducking Composition

## Context
Commercial video demands broadcast-standard audio with clear spoken dialogue, immersive background music, and punchy sound effects. If music volume remains static, voiceover clarity is obscured; conversely, abrupt cuts in background music destroy pacing.

## Decision
Implement a multi-track audio architecture using Neural TTS (Vietnamese voiceover tailored to KOL persona) with per-beat audio stems, paired with an FFmpeg complex filter graph performing automated audio ducking. The background music is attenuated by -24dB during active voiceover segments and ramps back smoothly during pauses. Direct-to-camera presenter shots enforce lip-sync alignment and timing constraints (<50ms offset).

## Consequences
- Voiceover dialogue is punchy and intelligible (-14 LUFS standard) while maintaining energetic music rhythm.
- Audio stems are isolated for modular replacement without requiring video re-render.
