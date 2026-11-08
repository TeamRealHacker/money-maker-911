"""Tiny MIDI reader (standard .mid files, no dependencies) + a few built-in public-domain melodies for
the Rhythmic mode. A melody is a list of Note(t, pitch, dur) with t / dur in seconds."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Note:
    t: float
    pitch: int
    dur: float = 0.25


# (midi pitch, beats). Public-domain tunes, played at the given BPM.
_SONGS: dict[str, tuple[float, list[tuple[int, float]]]] = {}


def _song(name: str, bpm: float, text: str) -> None:
    notes = []
    for tok in text.split():
        p, _, b = tok.partition(":")
        notes.append((int(p), float(b) if b else 1.0))
    _SONGS[name] = (bpm, notes)


_song("ode_to_joy", 112,
      "64 64 65 67 67 65 64 62 60 60 62 64 64:1.5 62:.5 62:2 "
      "64 64 65 67 67 65 64 62 60 60 62 64 62:1.5 60:.5 60:2 "
      "62 62 64 60 62 64:.5 65:.5 64 60 62 64:.5 65:.5 64 62 60 62 55:2 "
      "64 64 65 67 67 65 64 62 60 60 62 64 62:1.5 60:.5 60:3")
_song("twinkle", 104,
      "60 60 67 67 69 69 67:2 65 65 64 64 62 62 60:2 67 67 65 65 64 64 62:2 "
      "67 67 65 65 64 64 62:2 60 60 67 67 69 69 67:2 65 65 64 64 62 62 60:3")
_song("fur_elise", 120,
      "76:.5 75:.5 76:.5 75:.5 76:.5 71:.5 74:.5 72:.5 69:1 60:.5 64:.5 69:.5 71:1 64:.5 68:.5 71:.5 72:1 "
      "64:.5 76:.5 75:.5 76:.5 75:.5 76:.5 71:.5 74:.5 72:.5 69:1 60:.5 64:.5 69:.5 71:1 64:.5 72:.5 71:.5 69:2")
_song("jingle_bells", 132,
      "64 64 64:2 64 64 64:2 64 67 60:1.5 62:.5 64:4 "
      "65 65 65:1.5 65:.5 65 64 64 64:.5 64:.5 64 62 62 64 62:2 67:2 "
      "64 64 64:2 64 64 64:2 64 67 60:1.5 62:.5 64:4 "
      "65 65 65:1.5 65:.5 65 64 64 64:.5 64:.5 67 67 65 62 60:4")
_song("scale_up", 150, "60 62 64 65 67 69 71 72 71 69 67 65 64 62 60:2")

SONG_NAMES = list(_SONGS)


def builtin(name: str) -> list[Note]:
    bpm, notes = _SONGS.get(name) or _SONGS["ode_to_joy"]
    spb = 60.0 / bpm
    out, t = [], 0.0
    for p, b in notes:
        out.append(Note(round(t, 4), p, b * spb))
        t += b * spb
    return out


def _vlq(data: bytes, i: int) -> tuple[int, int]:
    v = 0
    for _ in range(4):
        b = data[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            break
    return v, i


def parse_midi(data: bytes) -> list[Note]:
    """All note-on events of a standard MIDI file as Notes (seconds), tempo map applied, drums skipped.
    Raises ValueError on anything that is not a readable MIDI file."""
    if data[:4] != b"MThd" or len(data) < 14:
        raise ValueError("not a MIDI file")
    _, ntrk, div = struct.unpack(">HHH", data[8:14])
    hdr_len = struct.unpack(">I", data[4:8])[0]
    if div & 0x8000:
        raise ValueError("SMPTE timing is not supported")
    div = max(1, div)
    i = 8 + hdr_len
    tempos: list[tuple[int, int]] = [(0, 500000)]
    raw: list[tuple[int, int, int]] = []      # (tick, pitch, channel) note-ons
    offs: dict[tuple[int, int, int], int] = {}
    ends: list[tuple[int, int, int, int]] = []
    for ti in range(ntrk):
        if data[i:i + 4] != b"MTrk":
            break
        ln = struct.unpack(">I", data[i + 4:i + 8])[0]
        j, end = i + 8, min(len(data), i + 8 + ln)
        i = i + 8 + ln
        tick, status = 0, 0
        open_: dict[tuple[int, int], int] = {}
        while j < end:
            d, j = _vlq(data, j)
            tick += d
            b = data[j]
            if b >= 0x80:
                status = b
                j += 1
            elif status == 0:
                raise ValueError("bad MIDI data")
            if status == 0xFF:
                typ = data[j]
                ln2, j = _vlq(data, j + 1)
                if typ == 0x51 and ln2 == 3:
                    tempos.append((tick, int.from_bytes(data[j:j + 3], "big") or 500000))
                j += ln2
                if typ == 0x2F:
                    break
            elif status in (0xF0, 0xF7):
                ln2, j = _vlq(data, j)
                j += ln2
            else:
                kind, ch = status & 0xF0, status & 0x0F
                n = 1 if kind in (0xC0, 0xD0) else 2
                a = data[j]
                b2 = data[j + 1] if n == 2 else 0
                j += n
                if kind == 0x90 and b2 > 0:
                    raw.append((tick, a, ch))
                    open_[(ch, a)] = len(raw) - 1
                elif kind == 0x80 or (kind == 0x90 and b2 == 0):
                    k = open_.pop((ch, a), None)
                    if k is not None:
                        ends.append((k, tick, 0, 0))
    tempos.sort(key=lambda x: x[0])
    # tick -> seconds through the tempo map
    marks = []     # (tick, seconds at tick, µs per beat)
    sec, last_tick, cur = 0.0, 0, 500000
    for tk, us in tempos:
        sec += (tk - last_tick) * cur / div / 1e6
        marks.append((tk, sec, us))
        last_tick, cur = tk, us

    def to_sec(tk: int) -> float:
        m = marks[0]
        for mk in marks:
            if mk[0] <= tk:
                m = mk
            else:
                break
        return m[1] + (tk - m[0]) * m[2] / div / 1e6

    end_of = {k: tk for k, tk, _, _ in ends}
    notes = []
    for k, (tk, p, ch) in enumerate(raw):
        if ch == 9:
            continue
        t = to_sec(tk)
        t2 = to_sec(end_of[k]) if k in end_of else t + 0.25
        notes.append(Note(round(t, 4), p, max(0.05, t2 - t)))
    notes.sort(key=lambda n: (n.t, -n.pitch))
    return notes


def melody(notes: list[Note], min_gap: float = 0.08) -> list[Note]:
    """One note per beat: chords keep their highest note, notes closer than min_gap are dropped."""
    out: list[Note] = []
    for n in notes:
        if out and n.t - out[-1].t < min_gap:
            if n.pitch > out[-1].pitch and abs(n.t - out[-1].t) < 0.03:
                out[-1] = n
            continue
        out.append(n)
    return out


def load_song(path: str, name: str) -> list[Note]:
    """The notes for a config: the .mid file when it reads, else the built-in song `name`."""
    if path:
        try:
            ns = melody(parse_midi(Path(path).read_bytes()))
            if len(ns) >= 2:
                t0 = ns[0].t
                return [Note(round(n.t - t0, 4), n.pitch, n.dur) for n in ns]
        except (OSError, ValueError, IndexError, struct.error):
            pass
    return builtin(name)
