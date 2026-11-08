import struct
from mm911.config import MergeConfig
from mm911.midi import read_melody
from mm911.modes.registry import sim_for


def test_midi_reader(tmp_path):
    ev = b""
    for n in (60, 62, 64):
        ev += b"\x00\x90" + bytes([n, 90]) + b"\x60\x80" + bytes([n, 0])
    ev += b"\x00\xff\x2f\x00"
    p = tmp_path / "t.mid"
    p.write_bytes(b"MThd" + struct.pack(">IHHH", 6, 0, 1, 96) + b"MTrk" + struct.pack(">I", len(ev)) + ev)
    assert read_melody(str(p)) == [60, 62, 64]
    assert read_melody(str(tmp_path / "missing.mid")) == []


def test_rhythmic_plays_notes():
    cfg = MergeConfig(mode="rhythmic", seed=3)
    sim = sim_for(cfg)
    for _ in range(600):
        sim.step(1 / 60)
    assert sim.note_i > 5
