"""🌀 Escape mode: physics wins, sounds rise per escape, renders through the shared pipeline."""
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("APPDATA", os.path.join(tempfile.gettempdir(), "mm911_test_appdata"))

from mm911.config import MergeConfig  # noqa: E402
from mm911.modes.escape import EscapeSim, pitch_ladder  # noqa: E402
from mm911.render import render_video, simulate, make_renderer, make_sim, make_thumbnail  # noqa: E402
from mm911.cli import main as cli_main  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_escape_is_winnable_and_deterministic():
    wins = [simulate(MergeConfig(mode="escape", seed=s)).won for s in range(1, 7)]
    assert sum(wins) >= 5
    a = simulate(MergeConfig(mode="escape", seed=3))
    b = simulate(MergeConfig(mode="escape", seed=3))
    assert (a.finished_at, a.bounces) == (b.finished_at, b.bounces)


def test_pitch_rises_per_escape():
    sim = simulate(MergeConfig(mode="escape", seed=2))
    pitches = [e.pitch for e in sim.events if e.kind == "merge"]
    assert len(pitches) == sim.escaped - 1           # the last escape is the "final" event
    assert pitches == sorted(pitches) and pitches[0] < pitches[-1]
    assert any(e.kind == "final" for e in sim.events)
    cfg = MergeConfig(mode="escape")
    assert pitch_ladder(cfg, 0) == cfg.escape_pitch_low
    assert pitch_ladder(cfg, cfg.escape_rings - 1) == cfg.escape_pitch_high


def test_rings_draw_antialiased_with_gaps():
    import pygame
    cfg = MergeConfig(mode="escape", seed=1, bg_mode="solid", bg_colors=["#000000"], escape_ring_glow=0,
                      escape_ring_colors=["#FFFFFF"] * 8, hook="", escape_counter_text="")
    sim = make_sim(cfg)
    rend = make_renderer(cfg, 0.5)
    S = rend.draw(sim)
    arr = pygame.surfarray.array3d(S)[..., 0]
    ring = sim.rings[0]
    import math
    cx, cy, R = sim.cx * 0.5, sim.cy * 0.5, ring.radius * 0.5
    g = ring.gap0 + ring.angle
    # wall opposite the gap is drawn, the middle of the gap is empty
    wx, wy = cx + R * math.cos(g + math.pi), cy + R * math.sin(g + math.pi)
    gx, gy = cx + R * math.cos(g), cy + R * math.sin(g)
    assert arr[int(wx), int(wy)] > 200
    assert arr[int(gx), int(gy)] < 30
    box = arr[int(cx - R) - 8:int(cx + R) + 8, int(cy - R) - 8:int(cy + R) + 8]
    assert ((box > 10) & (box < 245)).sum() > R * 4      # anti-aliased edge pixels all round


def test_escape_render_and_preset(tmp_path):
    cfg = MergeConfig.load(ROOT / "presets" / "escape_rings.json")
    assert cfg.mode == "escape"
    cfg.max_seconds, cfg.fps, cfg.export_resolution = 3, 24, "720p"
    meta = render_video(cfg, str(tmp_path / "e.mp4"))
    assert Path(meta["file"]).stat().st_size > 10_000 and meta["mode"] == "escape"
    assert meta["rings"] == 8 and Path(meta["thumbnail"]).exists()
    th = make_thumbnail(MergeConfig(mode="escape", seed=5), str(tmp_path / "t.jpg"))
    assert th["won"]


def test_cli_mode_flag(tmp_path, capsys):
    cli_main(["render", "--mode", "escape", "--rings", "4", "--seconds", "2", "--fps", "24", "--res", "720p",
              "--no-audio", "--out", str(tmp_path / "c.mp4")])
    out = capsys.readouterr().out
    meta = json.loads(out[out.index("{"):])
    assert meta["mode"] == "escape" and meta["rings"] == 4
