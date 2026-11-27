"""🪐 Orbit 3D: the tunnel clears every hoop, every seed finishes, and the mode is cheap.

The last point is a real acceptance criterion for this mode ("no lag"): these tests decode a run
and assert it stays inside a frame budget instead of leaving it to the eye.
"""
import time

import pytest

from mm911 import render
from mm911.config import MergeConfig
from mm911.modes.registry import MODES, renderer_for, sim_for


def test_orbit3d_is_registered_under_its_own_name():
    assert MODES["orbit3d"] == "🪐 Orbit 3D"
    cfg = MergeConfig(mode="orbit3d")
    assert type(sim_for(cfg)).__name__ == "Orbit3DSim"
    assert type(renderer_for(cfg)).__name__ == "Orbit3DRenderer"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_orbit3d_clears_every_hoop(seed):
    sim = render.simulate(MergeConfig(mode="orbit3d", seed=seed))
    assert sim.won and sim.broken == sim.total == sim.cfg.orbit_rings


def test_orbit3d_is_deterministic():
    a = render.simulate(MergeConfig(mode="orbit3d", seed=7))
    b = render.simulate(MergeConfig(mode="orbit3d", seed=7))
    assert a.finished_at == b.finished_at and a.stats() == b.stats()


@pytest.mark.parametrize("kw", [dict(orbit_rings=2), dict(orbit_rings=40),
                                dict(orbit_speed_deg=300), dict(orbit_ball_y=0),
                                dict(orbit_trail=0), dict(orbit_fog=0.9),
                                dict(orbit_camera_dist=260), dict(orbit_camera_dist=2400)])
def test_orbit3d_settings_still_finish(kw):
    sim = render.simulate(MergeConfig(mode="orbit3d", seed=1, until_finished=True, **kw))
    assert sim.won, kw


def test_orbit3d_clamps_its_own_settings():
    cfg = MergeConfig(mode="orbit3d", orbit_rings=999, orbit_fog=9.0, orbit_ring_thickness=0,
                      orbit_camera_dist=1, orbit_trail=-5, orbit_ball_radius=1)
    cfg.clamp()
    assert (cfg.orbit_rings, cfg.orbit_fog, cfg.orbit_ring_thickness) == (40, 0.9, 1)
    assert (cfg.orbit_camera_dist, cfg.orbit_trail, cfg.orbit_ball_radius) == (260.0, 0, 8.0)


def test_orbit3d_hoops_stay_ahead_of_the_camera():
    """The tunnel is scenery: the live hoops are always in front of the eye, in order, and the
    nearest one is a fixed distance ahead of the ball (that constant framing is the whole shot)."""
    cfg = MergeConfig(mode="orbit3d", seed=3, max_seconds=10)
    sim = sim_for(cfg)
    dt = 1 / cfg.fps
    for _ in range(int(cfg.fps * 4)):
        sim.step(dt)
        live = [r for r in sim.orbit_rings if r.cleared_vt is None]
        if not live:
            break
        eye_z = sim.ball_z + sim.back            # the eye trails the ball, toward the viewer
        assert all(r.z < eye_z for r in live), "a hoop ended up behind the camera"
        depths = sorted((r.z for r in live), reverse=True)
        assert depths == [r.z for r in sorted(live, key=lambda r: -r.z)]
        assert abs(max(depths) - (sim.ball_z - sim.near_z)) < sim.near_z * 0.02


def test_orbit3d_frame_cost_is_small():
    """"No lag" as a test: a full 720x1280 frame must decode far faster than real time."""
    cfg = MergeConfig(mode="orbit3d", seed=1, max_seconds=12, fps=30)
    cfg.clamp()
    sim = sim_for(cfg)
    ren = renderer_for(cfg, 1.0)
    for _ in range(12):                       # warm the caches (fonts, background, sprites)
        sim.step(1 / cfg.fps)
        ren.draw(sim)
    t0 = time.perf_counter()
    frames = 30
    for _ in range(frames):
        sim.step(1 / cfg.fps)
        ren.draw(sim)
    per_frame = (time.perf_counter() - t0) / frames
    assert per_frame < 0.02, f"{per_frame * 1000:.1f} ms per frame"


def test_orbit3d_renderer_never_allocates_a_growing_cache():
    cfg = MergeConfig(mode="orbit3d", seed=1, max_seconds=12, fps=30)
    cfg.clamp()
    sim = sim_for(cfg)
    ren = renderer_for(cfg, 1.0)
    sizes = []
    for i in range(90):
        sim.step(1 / cfg.fps)
        ren.draw(sim)
        if i in (30, 60, 89):
            sizes.append(len(ren._sprite))
    assert max(sizes) < 400, sizes
