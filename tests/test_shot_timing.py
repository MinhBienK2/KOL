"""Pure unit tests for the per-shot timeline planner (no ffmpeg)."""

import pytest

from pipeline.lip_sync_engine import MAX_SLOWDOWN, plan_shot_timing


def test_long_clip_is_trimmed_to_beat_estimate():
    plan = plan_shot_timing("shot_01", beat_estimated=3.0, voice_seconds=2.0, clip_seconds=6.0)
    assert plan.action == "trim"
    assert plan.target_seconds == pytest.approx(3.0)
    assert (plan.in_point, plan.out_point) == (0.0, pytest.approx(3.0))
    assert plan.slowdown_factor == 1.0 and plan.held_tail_seconds == 0.0


def test_voice_longer_than_estimate_extends_to_voice_using_real_motion():
    plan = plan_shot_timing("shot_02", beat_estimated=2.0, voice_seconds=4.6, clip_seconds=6.0)
    assert plan.action == "trim"
    assert plan.target_seconds == pytest.approx(4.6)
    assert plan.out_point == pytest.approx(4.6)
    assert plan.held_tail_seconds == 0.0


def test_short_clip_gets_gentle_slowdown_not_frozen_frames():
    plan = plan_shot_timing("shot_03", beat_estimated=3.0, voice_seconds=3.5, clip_seconds=3.0)
    assert plan.action == "slowdown"
    assert plan.target_seconds == pytest.approx(3.5)
    assert plan.slowdown_factor == pytest.approx(3.5 / 3.0, abs=1e-3)
    assert plan.held_tail_seconds == 0.0
    assert plan.out_point == pytest.approx(3.0)  # whole clip consumed, played slower


def test_soft_estimate_is_capped_by_clip_length_times_max_slowdown():
    plan = plan_shot_timing("shot_04", beat_estimated=10.0, voice_seconds=2.0, clip_seconds=6.0)
    assert plan.action == "slowdown"
    assert plan.slowdown_factor == pytest.approx(MAX_SLOWDOWN)
    assert plan.target_seconds == pytest.approx(6.0 * MAX_SLOWDOWN)
    assert plan.held_tail_seconds == 0.0


def test_voice_that_cannot_be_covered_by_slowdown_holds_only_the_remainder():
    plan = plan_shot_timing("shot_05", beat_estimated=3.0, voice_seconds=9.0, clip_seconds=6.0)
    assert plan.action == "slowdown_and_hold"
    assert plan.target_seconds == pytest.approx(9.0)  # voice is never cut off
    assert plan.slowdown_factor == pytest.approx(MAX_SLOWDOWN)
    assert plan.held_tail_seconds == pytest.approx(9.0 - 6.0 * MAX_SLOWDOWN)


def test_voice_padding_is_reported_when_voice_is_shorter_than_shot():
    plan = plan_shot_timing("shot_06", beat_estimated=3.0, voice_seconds=1.0, clip_seconds=6.0)
    assert plan.voice_padded_seconds == pytest.approx(2.0)


def test_exact_fit_is_not_modified():
    plan = plan_shot_timing("shot_07", beat_estimated=6.0, voice_seconds=5.0, clip_seconds=6.0)
    assert plan.action == "exact"
    assert plan.slowdown_factor == 1.0


def test_degenerate_clip_raises():
    with pytest.raises(ValueError):
        plan_shot_timing("shot_08", beat_estimated=3.0, voice_seconds=1.0, clip_seconds=0.0)
