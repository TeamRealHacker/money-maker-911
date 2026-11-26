"""♾️ Infinite Zoom Physics Loop: endless stair zoom, deeper sounds per step, every seed wins."""
import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_zoom_reaches_target_and_wins():
    cfg = MergeConfig(mode="zoom", seed=5, zoom_target=10)
    sim = render.simulate(cfg)
    assert sim.won and sim.broken == sim.total == 10


def test_zoom_is_deterministic():
    a = render.simulate(MergeConfig(mode="zoom", seed=9, zoom_target=8))
    b = render.simulate(MergeConfig(mode="zoom", seed=9, zoom_target=8))
    assert a.finished_at == b.finished_at and a.stats() == b.stats()


def test_zoom_sounds_get_deeper_and_slower():
    sim = render.simulate(MergeConfig(mode="zoom", seed=2, zoom_target=12))
    merges = [ev for ev in sim.events if ev.kind == "merge" and ev.pitch is not None]
    assert len(merges) >= 5
    pitches = [ev.pitch for ev in merges]
    assert all(p2 < p1 for p1, p2 in zip(pitches, pitches[1:])), pitches
    # the step rhythm slows down: the last merge comes later than the first one
    gaps = [b.vt - a.vt for a, b in zip(merges, merges[1:])]
    assert gaps[-1] > gaps[0]


def test_zoom_settings_finish():
    for kw in (dict(zoom_target=4), dict(zoom_target=30), dict(zoom_growth=1.1),
               dict(zoom_step_time=0.4), dict(zoom_stars=0), dict(zoom_ball_spin=0)):
        sim = render.simulate(MergeConfig(mode="zoom", seed=1, until_finished=True, **kw))
        assert sim.won, kw


def test_zoom_persists_seamlessness():
    """The loop's screen state at the end of a step equals its start: the camera math returns the
    same zoom ratio relative to the landing point every step."""
    sim = render.simulate(MergeConfig(mode="zoom", seed=7, zoom_target=6))
    assert sim.won
    g = sim.g
    assert sim.C1 == pytest.approx((0.26 * sim.W, 0.52 * sim.W))
    landing = sim._landing()
    assert (landing[0] - sim.C1[0]) * g == pytest.approx(sim.A[0])
    assert (landing[1] - sim.C1[1]) * g == pytest.approx(sim.A[1])
