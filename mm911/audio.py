"""Sound: load any clip (Myinstants mp3, wav, ogg...), pitch it per event, mix into one track."""
from __future__ import annotations

import logging
import os
import subprocess
import wave
from pathlib import Path

import numpy as np

from .ffmpeg import ffmpeg_exe

SR = 44100
LOG = logging.getLogger("mm911")


def builtin_pop(duration: float = 0.12) -> np.ndarray:
    """A soft 'bloop' made from scratch (no copyright)."""
    t = np.linspace(0, duration, int(SR * duration), endpoint=False)
    freq = 520 * np.exp(-t * 9)  + 180          # falling pitch
    phase = 2 * np.pi * np.cumsum(freq) / SR
    env = np.exp(-t * 28) * (1 - np.exp(-t * 900))
    sig = np.sin(phase) * env + 0.25 * np.sin(2 * phase) * env
    return (sig / np.max(np.abs(sig)) * 0.9).astype(np.float32)


_DECODE_CACHE: dict = {}


def _decode(path: str, max_seconds: float | None) -> np.ndarray:
    """Decode any audio/video file to mono float32 @44.1k with FFmpeg (cached per file)."""
    st = Path(path).stat()
    key = (path, st.st_mtime, st.st_size, max_seconds)
    if key in _DECODE_CACHE:
        return _DECODE_CACHE[key]
    cmd = [ffmpeg_exe(), "-v", "error", "-i", path]
    if max_seconds:
        cmd += ["-t", str(max_seconds)]
    cmd += ["-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    creation = 0x08000000 if os.name == "nt" else 0
    raw = subprocess.run(cmd, capture_output=True, check=True, timeout=120, creationflags=creation).stdout
    data = np.frombuffer(raw, dtype=np.float32).copy()
    if len(_DECODE_CACHE) > 16:
        _DECODE_CACHE.clear()
    _DECODE_CACHE[key] = data
    return data


def load_sound(path: str) -> np.ndarray:
    """The pop / merge sound: first 3 s of any clip (Myinstants mp3, wav, ogg, m4a, even a video),
    leading silence trimmed, normalised. Broken or missing files fall back to the built-in pop
    instead of failing the whole render."""
    if not path or not Path(path).exists():
        return builtin_pop()
    try:
        data = _decode(path, 6)
    except Exception as e:
        LOG.warning("could not decode sound %s: %s", path, e)
        return builtin_pop()
    if data.size == 0 or not np.isfinite(data).all() or np.max(np.abs(data)) < 1e-4:
        return builtin_pop()
    idx = int(np.argmax(np.abs(data) > 0.02 * np.max(np.abs(data))))  # trim leading silence
    data = data[idx: idx + SR * 3]                  # cap at 3 s
    fade = min(len(data), int(SR * 0.01))           # tiny fade-out: no click when it's cut
    if fade > 1:
        data[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    peak = np.max(np.abs(data)) or 1.0
    return (data / peak * 0.9).astype(np.float32)


def load_music(path: str, max_seconds: float = 600) -> np.ndarray:
    """Background music: the WHOLE track (the old code cut music to a 3 s loop), normalised.
    Empty array when missing or unreadable."""
    if not path or not Path(path).exists():
        return np.zeros(0, dtype=np.float32)
    try:
        data = _decode(path, max_seconds)
    except Exception as e:
        LOG.warning("could not decode music %s: %s", path, e)
        return np.zeros(0, dtype=np.float32)
    if data.size == 0 or not np.isfinite(data).all():
        return np.zeros(0, dtype=np.float32)
    peak = np.max(np.abs(data)) or 1.0
    return (data / peak * 0.9).astype(np.float32)


def wav_bytes(data: np.ndarray) -> bytes:
    """16-bit mono WAV in memory (used by the app to let you listen to your sound)."""
    import io
    pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return bio.getvalue()


def demo_track(sample: np.ndarray, volume: float = 1.0) -> np.ndarray:
    """What the sound will sound like in a video: a few drops, rising merges, then the final."""
    tr = AudioTrack(3.2)
    t = 0.0
    for tier in range(0, 6):
        tr.add(sample, t, -4.0 + tier * 1.6, 0.35 * volume); t += 0.12
        tr.add(sample, t, tier * 1.6, volume); t += 0.28
    tr.add(sample, t + 0.1, 7.0 + 8 * 1.6, 1.3 * volume)
    return tr.mixed(3.2)


def pitch(sample: np.ndarray, semitones: float) -> np.ndarray:
    """Pitch by resampling (higher = shorter), like a turntable speed-up."""
    if abs(semitones) < 1e-3:
        return sample
    ratio = 2 ** (semitones / 12)
    n = max(1, int(len(sample) / ratio))
    x = np.linspace(0, len(sample) - 1, n)
    return np.interp(x, np.arange(len(sample)), sample).astype(np.float32)


class AudioTrack:
    """Collects timed sound events, then writes one WAV."""

    def __init__(self, seconds: float):
        self.buf = np.zeros(int(SR * (seconds + 3)), dtype=np.float32)
        self._cache: dict[tuple[int, int], np.ndarray] = {}

    def add(self, sample: np.ndarray, at: float, semitones: float = 0.0, volume: float = 1.0) -> None:
        key = (id(sample), int(round(semitones * 10)))
        s = self._cache.get(key)
        if s is None:
            s = pitch(sample, semitones)
            self._cache[key] = s
        i = int(at * SR)
        if i >= len(self.buf):
            return
        end = min(len(self.buf), i + len(s))
        self.buf[i:end] += s[: end - i] * volume

    def add_music(self, music: np.ndarray, volume: float) -> None:
        if music.size == 0:
            return
        reps = int(np.ceil(len(self.buf) / len(music)))
        self.buf += np.tile(music, reps)[: len(self.buf)] * volume

    def mixed(self, seconds: float) -> np.ndarray:
        data = self.buf[: int(SR * seconds)].copy()
        peak = np.max(np.abs(data)) if data.size else 0
        if peak > 0.98:                            # soft limiter
            data = np.tanh(data / peak * 1.5) * 0.95
        return data

    def write(self, path: str, seconds: float) -> None:
        data = self.mixed(seconds)
        pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
