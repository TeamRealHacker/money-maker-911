import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_snake_reaches_target_and_is_deterministic():
    a = render.simulate(MergeConfig(mode="snake", seed=3, until_finished=True))
    b = render.simulate(MergeConfig(mode="snake", seed=3, until_finished=True))
    assert a.won and a.broken == a.total and a.finished_at == b.finished_at


@pytest.mark.parametrize("seed", range(6))
def test_snake_every_seed_wins(seed):
    assert render.simulate(MergeConfig(mode="snake", seed=seed, until_finished=True)).won


@pytest.mark.parametrize("kw", [dict(snake_target=2), dict(snake_speed=200), dict(snake_turn=1),
                                dict(snake_food_size=16), dict(snake_ball_radius=50), dict(snake_gap=2)])
def test_snake_settings_finish(kw):
    assert render.simulate(MergeConfig(mode="snake", seed=1, until_finished=True, **kw)).won
