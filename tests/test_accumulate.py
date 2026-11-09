from mm911 import render
from mm911.config import MergeConfig


def test_accumulate_reaches_target():
    for seed in (1, 2):
        cfg = MergeConfig(mode="accumulate", seed=seed, accumulate_target=30, accumulate_every=4)
        sim = render.simulate(cfg)
        assert sim.won and len(sim.balls) == 30
