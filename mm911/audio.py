"""Sound: load any clip (Myinstants mp3, wav, ogg...), pitch it per event, mix into one track."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from .ffmpeg import ffmpeg_exe

SR = 44100


def builtin_pop(duration: float = 0.12) -> np.ndarray:
    """A soft 'bloop' made from scratch (no copyright)."""
    t = np.linspace(0, duration, int(SR * duration), endpoint=False)
    freq = 520 * np.exp(-t * 9)  + 180          # falling pitch
    phase = 2 * np.pi * np.cumsum(freq) / SR
    env = np.exp(-t * 28) * (1 - np.exp(-t * 900))
    sig = np.sin(phase) * env + 0.25 * np.sin(2 * phase) * env
    return (sig / np.max(np.abs(sig)) * 0.9).astype(np.float32)


def load_sound(path: str) -> np.ndarray:
    """Decode any audio file to mono float32 @44.1k using FFmpeg."""
    if not path or not Path(path).exists():
        return builtin_pop()
    cmd = [ffmpeg_exe(), "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    data = np.frombuffer(raw, dtype=np.float32).copy()
    if data.size == 0:
        return builtin_pop()
    data = data[: SR * 3]                          # cap long clips at 3 s
    # trim leading silence
    idx = np.argmax(np.abs(data) > 0.02)
    data = data[idx:]
    peak = np.max(np.abs(data)) or 1.0
    return (data / peak * 0.9).astype(np.float32)


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

    def write(self, path: str, seconds: float) -> None:
        data = self.buf[: int(SR * seconds)]
        peak = np.max(np.abs(data)) if data.size else 0
        if peak > 0.98:                            # soft limiter
            data = np.tanh(data / peak * 1.5) * 0.95
        pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
