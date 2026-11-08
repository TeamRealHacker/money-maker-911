"""🎵 Rhythmic: MIDI reader, built-in songs, notes land exactly on time, bad MIDI falls back, render,
thumbnail, CLI, batch, sounds."""
import os
import random
import struct
import tempfile
from pathlib import Path

os.environ.setdefault("APPDATA", os.path.join(tempfile.gettempdir(), "mm911_test_appdata"))

import pygame  # noqa: E402
import pytest  # noqa: E402

from mm911 import midi  # noqa: E402
from mm911.batch import make_title, vary  # noqa: E402
from mm911.cli import main as cli_main  # noqa: E402
from mm911.config import MergeConfig  # noqa: E402
from mm911.render import make_renderer, make_sim, make_thumbnail, render_video, simulate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _vlq(v: int) -> bytes:
    b = [v & 0x7F]
    v >>= 7
    while v:
        b.append(0x80 | (v & 0x7F))
        v >>= 7
    return bytes(reversed(b))


def make_midi(pitches, gap=240, div=480, tempo=500000, drums=False, running=False) -> bytes:
    tr = _vlq(0) + b"\xff\x51\x03" + tempo.to_bytes(3, "big")
    for k, p in enumerate(pitches):
        tr += _vlq(0 if k == 0 else gap) + bytes([0x90, p, 80]) + _vlq(gap) + bytes([0x80, p, 0])
    if drums:
        tr += _vlq(0) + bytes([0x99, 38, 90]) + _vlq(10) + bytes([0x89, 38, 0])
    tr += _vlq(0) + b"\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, div) + b"MTrk" + struct.pack(">I", len(tr)) + tr


def test_midi_parser_times_and_pitches():
    notes = midi.parse_midi(make_midi([60, 62, 64, 65], gap=240))      # 240 ticks at 120 bpm = 0.25 s
    assert [n.pitch for n in notes] == [60, 62, 64, 65]
    assert [round(n.t, 3) for n in notes] == [0.0, 0.5, 1.0, 1.5]
    fast = midi.parse_midi(make_midi([60, 62], gap=240, tempo=250000))  # twice as fast
    assert round(fast[1].t, 3) == 0.25


def test_midi_skips_drums_and_bad_files():
    notes = midi.parse_midi(make_midi([60, 62], drums=True))
    assert len(notes) == 2                                              # channel 10 is drums
    for junk in (b"", b"hello world", b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x80\x00", make_midi([60])[:25]):
        try:
            midi.parse_midi(junk)
        except (ValueError, IndexError, struct.error):
            pass
    # a broken / missing file falls back to the built-in song instead of crashing
    for path in ("", "/no/such/file.mid", __file__):
        notes = midi.load_song(path, "twinkle")
        assert len(notes) == len(midi.builtin("twinkle"))
    assert len(midi.builtin("nope")) == len(midi.builtin("ode_to_joy"))


def test_melody_keeps_highest_of_a_chord():
    ns = [midi.Note(0.0, 60), midi.Note(0.0, 67), midi.Note(0.01, 64), midi.Note(0.5, 62)]
    out = midi.melody(ns)
    assert [n.pitch for n in out] == [67, 62]


def test_every_builtin_song_wins_and_lands_notes_on_time():
    for name in midi.SONG_NAMES:
        cfg = MergeConfig(mode="rhythm", rhythm_song=name, seed=2)
        sim = simulate(cfg)
        assert sim.won and sim.played == sim.total and sim.total >= 10
        hits = [e for e in sim.events if e.kind == "merge"]
        assert len(hits) == sim.total
        for e, t in zip(hits, sim.times):                     # sound time == note time (within one step)
            assert abs(e.vt - t / cfg.speed) < 1 / 60 + 1e-6
        assert sim.finished_at <= cfg.max_seconds
    a, b = simulate(MergeConfig(mode="rhythm", seed=5)), simulate(MergeConfig(mode="rhythm", seed=5))
    assert (a.finished_at, a.total) == (b.finished_at, b.total)


def test_long_midi_is_sped_up_or_cut_to_fit(tmp_path):
    p = tmp_path / "long.mid"
    p.write_bytes(make_midi([60 + (i * 7) % 24 for i in range(400)], gap=240))    # 200 s of notes
    cfg = MergeConfig(mode="rhythm", rhythm_midi=str(p), max_seconds=30)
    sim = simulate(cfg)
    assert sim.won and sim.finished_at <= 30 and 20 < sim.total < 400
    cfg = MergeConfig(mode="rhythm", rhythm_midi=str(p), until_finished=True)
    assert simulate(cfg).total == 400                                              # nothing cut


def test_lanes_follow_pitch_and_pitch_events_rise_with_notes():
    cfg = MergeConfig(mode="rhythm", rhythm_song="scale_up", rhythm_lanes=8)
    sim = make_sim(cfg)
    lanes = sim.note_lane
    assert min(lanes) == 0 and max(lanes) == 7
    assert all((a <= b) == (p <= q) or p == q for a, b, p, q in zip(lanes, lanes[1:], sim.pitches, sim.pitches[1:]))
    sim = simulate(cfg)
    ps = [e.pitch for e in sim.events if e.kind == "merge"]
    assert ps[0] == 0 and max(ps) == max(sim.pitches) - min(sim.pitches)


def test_bad_settings_are_clamped():
    cfg = MergeConfig(mode="rhythm", rhythm_lanes=999, rhythm_hop=-3, rhythm_tempo=0, rhythm_floor_y=5,
                      rhythm_ball_radius=-1, rhythm_trail=-4, rhythm_lead=99)
    cfg.clamp()
    assert (cfg.rhythm_lanes, cfg.rhythm_hop, cfg.rhythm_tempo) == (16, 0.2, 0.25)
    assert cfg.rhythm_floor_y == 0.92 and cfg.rhythm_ball_radius == 10 and cfg.rhythm_trail == 0 and cfg.rhythm_lead == 5
    assert simulate(cfg).won
    assert MergeConfig.from_dict({"mode": "rhythm", "rhythm_song": ["x"], "rhythm_lanes": "abc"}).rhythm_lanes == 8


def test_ball_stays_on_screen_and_lands_on_keys():
    cfg = MergeConfig(mode="rhythm", seed=1, rhythm_hop=3.0)
    sim = make_sim(cfg)
    while not sim.done:
        sim.step(1 / 60)
        x, y = sim.pos
        assert 0 < x < cfg.width and cfg.height * 0.25 < y <= sim.floor
    # at each note's time the ball sits exactly on top of that note's key
    sim = make_sim(cfg)
    for k in range(1, sim.total):
        sim.played = k
        sim._update_pos(sim.times[k - 1])
        assert abs(sim.pos[0] - sim.lane_x[sim.note_lane[k - 1]]) < 1e-6 and abs(sim.pos[1] - (sim.floor - sim.ball_r)) < 1e-6


def test_frames_draw_in_every_state():
    cfg = MergeConfig(mode="rhythm", seed=1, bg_mode="solid", bg_colors=["#000000"], hook="", rhythm_counter_text="")
    sim = make_sim(cfg)
    rend = make_renderer(cfg, 0.4)
    arr0 = pygame.surfarray.array3d(rend.draw(sim)).copy()
    for _ in range(60 * 5):
        sim.step(1 / 60)
    arr1 = pygame.surfarray.array3d(rend.draw(sim))
    assert (arr1 != arr0).any() and arr1.max() > 150          # keys, ball and sparks on black
    while sim.finished_at is None:
        sim.step(1 / 60)
    for _ in range(40):
        sim.step(1 / 60)
    assert rend.draw(sim).get_width() == rend.W
    rend.close()


def test_rhythm_render_thumb_cli_batch(tmp_path):
    cfg = MergeConfig.load(ROOT / "presets" / "rhythm_ode.json")
    assert cfg.mode == "rhythm"
    cfg.max_seconds, cfg.fps, cfg.export_resolution, cfg.rhythm_song = 8, 24, "720p", "scale_up"
    meta = render_video(cfg, str(tmp_path / "r.mp4"))
    assert meta["mode"] == "rhythm" and meta["won"] and Path(meta["file"]).stat().st_size > 10_000
    assert cli_main(["thumb", "--mode", "rhythm", "--song", "fur_elise", "--seed", "2", "--out", str(tmp_path / "t.jpg")]) in (0, None)
    assert (tmp_path / "t.jpg").stat().st_size > 5_000
    mid = tmp_path / "s.mid"
    mid.write_bytes(make_midi([60, 64, 67, 72, 67, 64, 60]))
    assert cli_main(["render", "--mode", "rhythm", "--midi", str(mid), "--seconds", "8", "--fps", "24", "--res", "720p",
                     "--out", str(tmp_path / "m.mp4")]) in (0, None)
    assert (tmp_path / "m.mp4").stat().st_size > 10_000
    songs = {vary(MergeConfig(mode="rhythm"), i, random.Random(1), True).rhythm_song for i in range(5)}
    assert songs == set(midi.SONG_NAMES)
    own = vary(MergeConfig(mode="rhythm", rhythm_midi=str(mid)), 1, random.Random(1), True)
    assert own.rhythm_song == "ode_to_joy" and "#shorts" in make_title(MergeConfig(mode="rhythm"))
