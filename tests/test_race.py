import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_race_has_a_winner_and_is_deterministic():
    runs = [render.simulate(MergeConfig(mode="race", seed=4)) for _ in range(2)]
    assert runs[0].won and runs[0].winner >= 0
    assert (runs[0].winner, runs[0].finished_at) == (runs[1].winner, runs[1].finished_at)
    assert 3 < runs[0].finished_at < 40


@pytest.mark.parametrize("kw", [dict(race_racers=2), dict(race_racers=12), dict(race_rows=4), dict(race_rows=18),
                                dict(race_gravity=700), dict(race_ball_radius=46), dict(race_peg_radius=20)])
def test_race_settings_finish(kw):
    assert render.simulate(MergeConfig(mode="race", seed=2, until_finished=True, **kw)).won
