"""Duplicate checker for batches: perceptual hashes of sampled frames.

Each video gets a signature: N frames sampled evenly (skipping the first second, which is the same
hook text + empty container in every video), each reduced to a 64-bit DCT perceptual hash (pHash)
of the whole frame plus one of the busy middle area. Two videos are compared frame by frame; the
similarity is the share of matching hash bits, averaged. Renders of the same settings with a
different seed differ a lot in the middle area; a re-render / near copy (same seed, a tiny tweak)
scores close to 1.0. Signatures are cached in the output folder (`.mm911_hashes.json`) so later
batches into the same folder are checked against earlier videos too.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

from .ffmpeg import ffmpeg_exe

SAMPLES = 8
HASH_FILE = ".mm911_hashes.json"
DEFAULT_THRESHOLD = 0.9          # >= this share of matching bits = "too similar"
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm")


def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    m = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
    m[0] /= np.sqrt(2.0)
    return m


_D32 = _dct_matrix(32)


def phash(gray32: np.ndarray) -> int:
    """64-bit pHash of a 32x32 grey image: low 8x8 DCT terms (no DC) above their median."""
    d = _D32 @ gray32.astype(np.float64) @ _D32.T
    low = d[:8, :8].flatten()[1:]
    bits = low > np.median(low)
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def _duration(path: str) -> float:
    try:
        r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True, text=True, timeout=30)
        for line in r.stderr.splitlines():
            line = line.strip()
            if line.startswith("Duration:"):
                h, m, s = line.split(",")[0].split()[1].split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 0.0


def _grab(path: str, t: float, w: int, h: int) -> np.ndarray | None:
    creation = 0x08000000 if os.name == "nt" else 0
    cmd = [ffmpeg_exe(), "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
           "-vf", f"scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60, creationflags=creation)
    except Exception:
        return None
    if len(r.stdout) != w * h:
        return None
    return np.frombuffer(r.stdout, np.uint8).reshape(h, w)


def signature(path: str, samples: int = SAMPLES) -> list[list[int]]:
    """[[whole-frame hash, middle-area hash], ...] for `samples` evenly spaced frames."""
    dur = _duration(path)
    if dur <= 0:
        return []
    start = min(1.0, dur * 0.1)
    times = [start + (dur - start) * (i + 0.5) / samples for i in range(samples)]
    out = []
    for t in times:
        g = _grab(path, min(t, max(0.0, dur - 0.05)), 64, 112)   # 9:16
        if g is None:
            continue
        whole = _resize32(g)
        mid = _resize32(g[22:90, 4:60])                          # where the action is
        out.append([phash(whole), phash(mid)])
    return out


def _resize32(g: np.ndarray) -> np.ndarray:
    h, w = g.shape
    ys = (np.arange(32) * h / 32).astype(int)
    xs = (np.arange(32) * w / 32).astype(int)
    # area-ish: average of the block starting at each sample
    acc = np.zeros((32, 32), np.float64)
    by, bx = max(1, h // 32), max(1, w // 32)
    for dy in range(by):
        for dx in range(bx):
            acc += g[np.minimum(ys + dy, h - 1)][:, np.minimum(xs + dx, w - 1)]
    return acc / (by * bx)


def similarity(a: list, b: list) -> float:
    """0..1 share of matching hash bits, frame by frame (middle area counts double)."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    tot = 0.0
    for (wa, ma), (wb, mb) in zip(a[:n], b[:n]):
        sw = 1 - bin(wa ^ wb).count("1") / 63
        sm = 1 - bin(ma ^ mb).count("1") / 63
        tot += (sw + 2 * sm) / 3
    return tot / n


def _key(p: Path) -> str:
    try:
        st = p.stat()
        return f"{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        return ""


class HashBook:
    """Signatures of the videos in one output folder (persisted next to them)."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.path = self.folder / HASH_FILE
        try:
            self.data: dict = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}
        # forget videos that were deleted or replaced
        self.data = {k: v for k, v in self.data.items()
                     if isinstance(v, dict) and v.get("k") == _key(self.folder / k)}

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def best_match(self, sig: list, exclude: str = "") -> tuple[str, float]:
        best, score = "", 0.0
        for name, other in self.data.items():
            if name == exclude:
                continue
            s = similarity(sig, other["s"])
            if s > score:
                best, score = name, s
        return best, score

    def add(self, name: str, sig: list) -> None:
        self.data[name] = {"k": _key(self.folder / name), "s": sig}
        self.save()

    def get(self, name: str) -> list | None:
        v = self.data.get(name)
        return v["s"] if v else None


def check(path: str, book: HashBook, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Signature of `path` vs. the book. Returns {"sig", "match", "score", "duplicate"}."""
    sig = signature(path)
    match, score = book.best_match(sig, exclude=Path(path).name)
    return {"sig": sig, "match": match, "score": round(score, 3), "duplicate": bool(sig) and score >= threshold}


def scan_folder(folder: str, threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """All pairs of look-alike videos in a folder (CLI `dedupe`)."""
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in VIDEO_EXTS)
    book = HashBook(folder)
    sigs = {}
    for p in files:
        sigs[p.name] = book.get(p.name) or signature(str(p))
        book.data[p.name] = {"k": _key(p), "s": sigs[p.name]}
    book.save()
    pairs = []
    names = list(sigs)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            s = similarity(sigs[a], sigs[b])
            if s >= threshold:
                pairs.append({"a": a, "b": b, "score": round(s, 3)})
    return sorted(pairs, key=lambda d: -d["score"])
