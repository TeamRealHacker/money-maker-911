"""➕ Accumulate: one ball bounces in a box; every wall hit spawns another ball, so the count explodes
until it reaches the target. Every new ball plays a note a bit higher than the last.

Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export)."""
from __future__ import annotations

import math

import pymunk

from .breaker import BreakerSim, BBall
from .merge import SoundEvent


class AccumulateSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self._pending: list = []
        super().__init__(cfg, seed)
        self.counter_text = cfg.accumulate_counter_text
        self.final_text = cfg.accumulate_final_text
        self.broken = len(self.balls)
        self._last_break_vt = self.vt

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.accumulate_target))

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        c = self.cfg
        ball = super()._add_ball(pos)
        ball.shape.filter = pymunk.ShapeFilter(group=1)      # balls never push each other
        ball.shape.body.velocity = ball.shape.body.velocity  # random direction already set
        return ball

    def _on_wall(self, arbiter, space, data) -> None:
        self.hits += 1
        if self.finished_at is None and len(self.balls) + len(self._pending) < self.total:
            if self.hits % max(1, int(self.cfg.accumulate_every)) == 0:
                self._pending.append(arbiter.shapes[0].body.position)

    def _spawn(self) -> None:
        c = self.cfg
        for pos in self._pending:
            if len(self.balls) >= self.total:
                break
            nb = self._add_ball((pos.x, pos.y))
            n = len(self.balls)
            self.broken = n
            self._last_break_vt = self.vt
            self.events.append(SoundEvent(self.t, min(c.tiers - 1, nb.index * c.tiers // max(1, self.total)),
                                          "merge", vt=self.vt,
                                          pitch=c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low)
                                          * (n / self.total)))
            for _ in range(int(round(5 * c.particle_amount))):
                a = self.fx.uniform(0, 2 * math.pi)
                s = self.fx.uniform(100, 380) * c.particle_speed
                from .merge import Particle
                life = self.fx.uniform(0.3, 0.6)
                self.particles.append(Particle(pos.x, pos.y, math.cos(a) * s, math.sin(a) * s, life,
                                               (nb.index, 0), self.fx.uniform(3, 6), 0.0, 0.0, life))
            if n >= self.total:
                self.finished_at = self.vt
                self.final_pos = (pos.x, pos.y)
                self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
                if c.slowmo_final:
                    self._slow(c.slowmo_factor, c.slowmo_seconds)
                if c.shake_strength > 0:
                    self.shake = max(self.shake, c.shake_strength * 2.2)
        self._pending.clear()

    def step(self, dt: float) -> None:
        self._spawn()
        super().step(dt)

    @property
    def best_tier(self) -> int:
        return self.cfg.tiers - 1 if self.won else min(self.cfg.tiers - 1, len(self.balls) * self.cfg.tiers // self.total)

    def stats(self) -> dict:
        return {"balls": len(self.balls), "target": self.total}
