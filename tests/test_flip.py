import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_flip_reaches_target_and_is_deterministic():
    a = render.simulate(MergeConfig(mode="flip", seed=3, until_finished=True))
    b = render.simulate(MergeConfig(mode="flip", seed=3, until_finished=True))
    assert a.won and a.flips == a.total and a.finished_at == b.finished_at


@pytest.mark.parametrize("kw", [dict(flip_balls=1), dict(flip_balls=40), dict(flip_target=2),
                                dict(flip_interval=0.6), dict(flip_gravity=4000), dict(flip_ball_radius=60)])
def test_flip_settings_finish(kw):
    assert render.simulate(MergeConfig(mode="flip", seed=1, until_finished=True, **kw)).won
