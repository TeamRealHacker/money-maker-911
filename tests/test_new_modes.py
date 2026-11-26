"""🎳 Tower Stack, Bubble Pop, Hole Eater, Bowling Strike (v0.23.0): every seed finishes,
every setting stays finishable, and runs are deterministic."""
import pytest

from mm911 import render
from mm911.config import MergeConfig


# ---------- 🎳 bowling ----------
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_bowling_clears_every_pin(seed):
    sim = render.simulate(MergeConfig(mode="bowling", seed=seed))
    assert sim.won and sim.broken == sim.total and sim.stats()["throws"] <= sim.cfg.bowling_max_throws


def test_bowling_is_deterministic():
    a = render.simulate(MergeConfig(mode="bowling", seed=4))
    b = render.simulate(MergeConfig(mode="bowling", seed=4))
    assert a.finished_at == b.finished_at


@pytest.mark.parametrize("kw", [dict(bowling_pin_hp=2), dict(bowling_speed=800),
                                dict(bowling_pin_spread=1.4), dict(bowling_rows=6)])
def test_bowling_settings_finish(kw):
    sim = render.simulate(MergeConfig(mode="bowling", seed=1, until_finished=True,
                                      bowling_max_throws=30, **kw))
    assert sim.won, kw


# ---------- 🏗️ tower stack ----------
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_stacker_reaches_the_target(seed):
    sim = render.simulate(MergeConfig(mode="stacker", seed=seed))
    assert sim.won and sim.broken == sim.total and sim.stats()["misses"] == 0


def test_stacker_is_deterministic_and_stacks_real_blocks():
    a = render.simulate(MergeConfig(mode="stacker", seed=8))
    b = render.simulate(MergeConfig(mode="stacker", seed=8))
    assert a.finished_at == b.finished_at
    # every settled block sits on the one below (the tower actually stacks)
    tops = sorted(a.bricks, key=lambda bk: bk.y)
    for below, above in zip(tops, tops[1:]):
        assert abs(above.y - below.y) >= a.cfg.stacker_block_h * 0.5


def test_stacker_sloppy_drops_topple():
    """Three sloppy drops in a row bring the tower down (forced through the settle path so the
    mechanic is tested deterministically; at default settings every seed stacks clean)."""
    sim = render.simulate(MergeConfig(mode="stacker", seed=1, stacker_target=3))
    for _ in range(sim.cfg.stacker_miss_limit):
        if sim.falling is not None:
            sim.space.remove(sim.falling.body, sim.falling.shape)
            sim.falling = None
        sim._drop_block()
        sim._settle(sim.falling, clean=False)
    assert sim.toppled and not sim.won and sim.finished_at is not None


# ---------- 🫧 bubble pop ----------
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_bubble_pops_every_bubble(seed):
    sim = render.simulate(MergeConfig(mode="bubble", seed=seed))
    assert sim.won and sim.broken == sim.total


def test_bubble_is_deterministic():
    a = render.simulate(MergeConfig(mode="bubble", seed=6))
    b = render.simulate(MergeConfig(mode="bubble", seed=6))
    assert a.finished_at == b.finished_at


@pytest.mark.parametrize("kw", [dict(bubble_target=5), dict(bubble_speed=400),
                                dict(bubble_ball_speed=1500), dict(bubble_wobble=0)])
def test_bubble_settings_finish(kw):
    sim = render.simulate(MergeConfig(mode="bubble", seed=1, until_finished=True, **kw))
    assert sim.won, kw


# ---------- 🕳️ hole eater ----------
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_hole_eats_every_ball(seed):
    sim = render.simulate(MergeConfig(mode="hole", seed=seed))
    assert sim.won and sim.broken == sim.total and sim.stats()["eaten"] == sim.total


def test_hole_is_deterministic_and_grows():
    a = render.simulate(MergeConfig(mode="hole", seed=5))
    b = render.simulate(MergeConfig(mode="hole", seed=5))
    assert a.finished_at == b.finished_at
    assert a.stats()["hole_r"] > a.cfg.hole_radius


def test_hole_settings_finish():
    for kw in (dict(hole_balls=8), dict(hole_balls=60), dict(hole_flee=1.0),
               dict(hole_growth=0.1), dict(hole_speed=120)):
        sim = render.simulate(MergeConfig(mode="hole", seed=1, until_finished=True, **kw))
        assert sim.won, kw
