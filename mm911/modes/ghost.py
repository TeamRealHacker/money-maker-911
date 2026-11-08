"""👻 Ghost Escape: Escape in the dark. Only a ghostly light around the ball shows the rings, and every few
seconds the ring in front turns into a ghost for a moment (the ball floats through it). Escape every ring
for the ending. Settings: escape_* (rings, ball, spin ...) + ghost_* (darkness, light, phasing)."""
from __future__ import annotations

import math

import pymunk

from .escape import EscapeSim
from .merge import SoundEvent

SOLID = pymunk.ShapeFilter()
GHOST = pymunk.ShapeFilter(mask=0)


class GhostSim(EscapeSim):
    def __init__(self, cfg, seed: int | None = None):
        self.phase_until: dict[int, float] = {}
        self.next_phase = cfg.ghost_phase_every
        self.phases = 0
        super().__init__(cfg, seed)

    def _set_filter(self, ring, f) -> None:
        for s in ring.shapes:
            s.filter = f

    def _phase_ring(self):
        alive = self.alive_rings()
        return alive[0] if alive else None

    def step(self, dt: float) -> None:
        c = self.cfg
        ring = self._phase_ring()
        if ring is not None and c.ghost_phase_every > 0:
            if ring.index in self.phase_until:
                ring_ghost = self.phase_until[ring.index]
                d = math.hypot(self.ball.body.position.x - self.cx, self.ball.body.position.y - self.cy)
                touching = abs(d - ring.radius) < self.ball.radius + c.escape_ring_thickness / 2 + 2
                if self.vt >= ring_ghost and not touching:
                    del self.phase_until[ring.index]
                    self._set_filter(ring, SOLID)
                    self.next_phase = self.vt + c.ghost_phase_every
                else:
                    self._set_filter(ring, GHOST)   # also covers walls rebuilt by the assist
            elif self.vt >= self.next_phase:
                self.phase_until[ring.index] = self.vt + c.ghost_phase_len
                self.phases += 1
                self._set_filter(ring, GHOST)
                self.events.append(SoundEvent(self.t, self.best_tier, "drop", vt=self.vt,
                                              pitch=c.escape_pitch_low - 5))
        super().step(dt)

    def is_ghost(self, ring) -> bool:
        return ring.escaped_vt is None and ring.index in self.phase_until

    def stats(self) -> dict:
        return {"escaped": self.escaped, "rings": len(self.rings), "bounces": self.bounces, "ghost_phases": self.phases}
