"""Tiny stdlib MIDI reader: returns the melody (note numbers in play order) of a .mid file."""
from __future__ import annotations

import struct

# Ode to Joy, used when no MIDI file is given
DEFAULT_MELODY = [64, 64, 65, 67, 67, 65, 64, 62, 60, 60, 62, 64, 64, 62, 62,
                  64, 64, 65, 67, 67, 65, 64, 62, 60, 60, 62, 64, 62, 60, 60]


def _vlq(d: bytes, i: int):
    v = 0
    while i < len(d):
        b = d[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            break
    return v, i


def read_melody(path: str, max_notes: int = 2000) -> list[int]:
    """Notes of the busiest non-drum track (chords keep only their top note). [] if unreadable."""
    try:
        d = open(path, "rb").read()
        if d[:4] != b"MThd":
            return []
        hlen = struct.unpack(">I", d[4:8])[0]
        ntr = struct.unpack(">H", d[10:12])[0]
        i = 8 + hlen
        tracks = []
        for _ in range(ntr):
            if d[i:i + 4] != b"MTrk":
                break
            ln = struct.unpack(">I", d[i + 4:i + 8])[0]
            tracks.append(_track(d[i + 8:i + 8 + ln]))
            i += 8 + ln
        tracks = [t for t in tracks if t]
        if not tracks:
            return []
        best = max(tracks, key=len)
        out, last_t = [], None
        for t, n in sorted(best):
            if last_t is not None and abs(t - last_t) < 8:      # same chord: keep the highest
                out[-1] = max(out[-1], n)
            else:
                out.append(n)
            last_t = t
            if len(out) >= max_notes:
                break
        return out
    except Exception:
        return []


def _track(d: bytes):
    i, t, run, notes = 0, 0, 0, []
    while i < len(d):
        dt, i = _vlq(d, i)
        t += dt
        if i >= len(d):
            break
        b = d[i]
        if b == 0xFF:
            ln, j = _vlq(d, i + 2)
            i = j + ln
            continue
        if b in (0xF0, 0xF7):
            ln, j = _vlq(d, i + 1)
            i = j + ln
            continue
        if b & 0x80:
            run = b
            i += 1
        st = run & 0xF0
        if st in (0xC0, 0xD0):
            i += 1
        else:
            a, v = d[i], d[i + 1]
            i += 2
            if st == 0x90 and v > 0 and (run & 0x0F) != 9:
                notes.append((t, a))
    return notes
