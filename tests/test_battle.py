import pygame
import pytest

from mm911 import render
from mm911.config import MergeConfig


@pytest.mark.parametrize("kw", [{}, dict(battle_fighters=2), dict(battle_fighters=15), dict(tiers=3), dict(tiers=15),
                                dict(battle_hp=400, battle_damage=3), dict(battle_radius=110, battle_fighters=8)])
def test_battle_always_has_one_winner(kw):
    for seed in (1, 2, 3):
        sim = render.simulate(MergeConfig(mode="battle", seed=seed, until_finished=True, **kw))
        assert sim.won and len(sim.balls) == 1 and sim.winner is sim.balls[0]
        assert sim.eliminated == sim.total


def test_battle_deterministic_same_winner():
    a = render.simulate(MergeConfig(mode="battle", seed=9))
    b = render.simulate(MergeConfig(mode="battle", seed=9))
    assert a.winner.index == b.winner.index and a.finished_at == b.finished_at


def test_battle_winner_name_in_text():
    c = MergeConfig(mode="battle", seed=3, tiers=4, tier_names=["Ann", "Bob", "Cy", "Di"])
    sim = render.simulate(c)
    assert sim.final_text == f"{c.tier_names[sim.winner.index]} WINS!"
    sim2 = render.simulate(MergeConfig(mode="battle", seed=3, tiers=4))
    assert sim2.final_text == "WINNER!"


def test_battle_bad_values_are_clamped():
    c = MergeConfig.from_dict({"mode": "battle", "battle_fighters": 1, "battle_hp": "x", "battle_damage": -1, "battle_radius": 9999})
    c.clamp()
    assert c.battle_fighters == 2 and c.battle_hp >= 10 and c.battle_damage >= 1 and c.battle_radius <= 120


def test_battle_draws_health_bars_and_video(tmp_path):
    cfg = MergeConfig.load("presets/flag_battle.json")
    cfg.width, cfg.height = 360, 640
    sim = render.make_sim(cfg)
    r = render.make_renderer(cfg, 1.0)
    for _ in range(90):
        sim.step(1 / 60)
    assert r.draw(sim).get_size() == (360, 640)
    out = tmp_path / "b.mp4"
    cfg.max_seconds, cfg.fps = 3, 24
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000


@pytest.mark.parametrize("kw", [{}, dict(weapon_type="sword"), dict(weapon_type="spear", battle_fighters=15),
                                dict(weapon_type="mace", tiers=3), dict(weapon_length=2.0, weapon_spin=3.0)])
def test_weapon_battle_has_one_winner(kw):
    for seed in (1, 2, 3):
        sim = render.simulate(MergeConfig(mode="weapon", seed=seed, until_finished=True, **kw))
        assert sim.won and len(sim.balls) == 1 and sim.eliminated == sim.total


def test_weapon_only_blades_hurt():
    cfg = MergeConfig(mode="weapon", seed=2)
    sim = render.make_sim(cfg)
    for _ in range(600):
        sim.step(1 / 60)
    assert sim.eliminated > 0 and all(b.weapon in ("sword", "spear", "mace") for b in sim.balls)


def test_weapon_bad_values_and_draw():
    c = MergeConfig.from_dict({"mode": "weapon", "weapon_type": "laser", "weapon_length": 99, "weapon_spin": "x"})
    c.clamp()
    assert c.weapon_type == "mixed" and c.weapon_length == 2.0 and c.weapon_spin >= 0.2
    c.width, c.height = 360, 640
    sim = render.make_sim(c)
    r = render.make_renderer(c, 1.0)
    for _ in range(120):
        sim.step(1 / 60)
    assert r.draw(sim).get_size() == (360, 640)


def test_weapon_video_smoke(tmp_path):
    cfg = MergeConfig.load("presets/weapon_battle.json")
    cfg.width, cfg.height, cfg.max_seconds, cfg.fps = 360, 640, 3, 24
    out = tmp_path / "w.mp4"
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000
