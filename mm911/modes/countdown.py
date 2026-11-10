"""⏳ Countdown Survival: many pictures drift around the arena; on a steady countdown one of them is eliminated
at every tick (note climbs each time) until only one is left: SURVIVOR! Built on the Chain Reaction arena."""
from __future__ import annotations

from .chain import ChainSim
from .merge import SoundEvent


class CountdownSim(ChainSim):
    def __init__(self, cfg, seed: int | None = None):
        super().__init__(cfg, seed)
        self.counter_text = cfg.countdown_counter_text
        self.final_text = cfg.countdown_final_text
        self.total = max(2, int(cfg.countdown_balls))
        self._ignite_at = 0.8
        self._next = self._ignite_at

    def _radius(self) -> float:
        return self.cfg.countdown_ball_radius

    def _start_balls(self) -> int:
        return self.cfg.countdown_balls

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.countdown_balls))

    def _add_ball(self, pos=None):
        b = super()._add_ball(pos)
        a = b.shape.body.velocity
        n = a.length or 1.0
        sp = self.cfg.countdown_speed
        b.shape.body.velocity = (a.x / n * sp, a.y / n * sp)
        return b

    def _chain(self) -> None:
        c = self.cfg
        if self.finished_at is not None or self.vt < self._next:
            return
        if len(self.balls) <= 1:
            return
        gap = max(0.15, (c.countdown_seconds - self._ignite_at) / max(1, self.total - 1))
        self._next = self.vt + gap
        self._pop(self.rng.choice(self.balls))
        if len(self.balls) == 1:                       # the last one standing wins
            b = self.balls[0]
            p = b.shape.body.position
            self.pops = self.total
            self.broken = self.total - 1
            self.finished_at = self.vt
            self.final_pos = (p.x, p.y)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)

    def step(self, dt: float) -> None:
        sp = self.cfg.countdown_speed
        if self.finished_at is None:
            self._chain()
        for b in self.balls:
            v = b.shape.body.velocity
            n = v.length or 1.0
            b.shape.body.velocity = (v.x / n * sp, v.y / n * sp)
        super(ChainSim, self).step(dt)

    def stats(self) -> dict:
        return {"left": len(self.balls), "target": self.total}
