"""🎵 Rhythmic: Escape where every bounce plays the next note of a melody (a .mid file, or Ode to Joy).
The ball escapes ring by ring while the song plays itself; each note is a pitch shift of your pop sound."""
from __future__ import annotations

from .escape import EscapeSim
from .merge import SoundEvent
from ..midi import DEFAULT_MELODY, read_melody


class RhythmicSim(EscapeSim):
    def __init__(self, cfg, seed: int | None = None):
        mel = read_melody(cfg.rhythm_midi) if cfg.rhythm_midi else []
        self.melody = mel or list(DEFAULT_MELODY)
        self.note_i = 0
        super().__init__(cfg, seed)

    def next_pitch(self) -> float:
        n = self.melody[self.note_i % len(self.melody)]
        self.note_i += 1
        return float(n - self.cfg.rhythm_base_note + self.cfg.rhythm_transpose)

    def _on_bounce(self, arbiter, space, data) -> None:
        before = len(self.events)
        super()._on_bounce(arbiter, space, data)
        for k in range(before, len(self.events)):
            e = self.events[k]
            if e.kind == "drop":
                e.pitch = self.next_pitch()

    def stats(self) -> dict:
        return {"escaped": self.escaped, "rings": len(self.rings), "bounces": self.bounces, "notes": self.note_i}
