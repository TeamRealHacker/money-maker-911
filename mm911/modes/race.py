"""🏁 Race: your pictures race down a field of pegs to the finish line. First one across wins.
Built on the Plinko arena (real gravity, pegs, sounds, particles, slow-mo, export). Racer i wears picture i."""
from __future__ import annotations

import dataclasses

import pymunk

from .plinko import PlinkoSim
from .merge import SoundEvent, Popup


class RaceSim(PlinkoSim):
    def __init__(self, cfg, seed: int | None = None):
        cfg = dataclasses.replace(cfg, plinko_rows=cfg.race_rows, plinko_peg_radius=cfg.race_peg_radius,
                                  plinko_ball_radius=cfg.race_ball_radius, plinko_gravity=cfg.race_gravity,
                                  plinko_slots=3)
        self.winner = -1
        self.order: list[int] = []
        super().__init__(cfg, seed)
        self.counter_text = cfg.race_counter_text
        self.final_text = cfg.race_final_text
        self.constant_speed = False
        self.space.damping = 0.03                              # terminal velocity: a watchable 8-10 s race

    def _build_bricks(self) -> None:
        super()._build_bricks()
        self.total = 1
        for s in list(self.space.shapes):                     # no slot dividers: a finish line instead
            if isinstance(s, pymunk.Segment) and abs(s.a.y - self.slot_top) < 1e-6 and s.a.x == s.b.x:
                self.space.remove(s)
        self.finish_y = self.slot_top

    def _add_ball(self, pos=None, from_vel=None):
        raise RuntimeError("racers are added at start")

    def _spawn_racers(self) -> None:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        n = c.race_racers
        r = c.plinko_ball_radius
        span = x1 - x0 - 4 * r
        for i in range(n):
            x = x0 + 2 * r + span * (i + 0.5) / n + self.rng.uniform(-0.2, 0.2) * span / n
            ball = super(PlinkoSim, self)._add_ball((x, self.drop_y - self.rng.uniform(0, 1.5) * r))
            ball.index = i % max(1, c.tiers)
            ball.racer = i
            ball.shape.elasticity = self.rng.uniform(0.42, 0.62)
            ball.shape.filter = pymunk.ShapeFilter(group=1)
            ball.shape.body.velocity = (self.rng.uniform(-80, 80), 0)

    def step(self, dt: float) -> None:
        c = self.cfg
        if not self.balls and self.finished_at is None and self.vt == 0:
            self._spawn_racers()
        super(PlinkoSim, self).step(dt)                       # Breaker step (physics, particles, slow-mo)
        for ball in self.balls:
            body = ball.shape.body
            if self.finished_at is None and body.position.y >= self.finish_y and ball.racer not in self.order:
                self.order.append(ball.racer)
                self._finish(ball)
            if self.finished_at is None:
                n = self._stuck.get(id(ball), 0) + dt
                if body.velocity.length < 40:
                    self._stuck[id(ball)] = n
                    if n > 0.35:
                        body.apply_impulse_at_local_point((self.rng.choice((-1, 1)) * 240, -50))
                        self._stuck[id(ball)] = 0.0
                else:
                    self._stuck[id(ball)] = 0.0
        self.popups = [pu for pu in self.popups if self.vt - pu.born < pu.life]

    def _finish(self, ball) -> None:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        p = ball.shape.body.position
        self.winner = ball.racer
        self.finished_at = self.vt
        self.final_pos = (p.x, p.y)
        self.broken = 1
        self._last_break_vt = self.vt
        self.popups.append(Popup(min(x1 - 70, max(x0 + 70, p.x)), p.y - 60, f"#{ball.racer + 1}", self.vt, ball.index % max(1, c.tiers)))
        self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
        if c.slowmo_final:
            self._slow(c.slowmo_factor, c.slowmo_seconds)
        if c.shake_strength > 0:
            self.shake = max(self.shake, c.shake_strength * 2.0)
        self._pop(p.x, p.y, 70, ball.index % max(1, c.tiers))

    def _radius(self) -> float:
        return self.cfg.race_ball_radius

    @property
    def score(self) -> float:
        return 0.0

    def stats(self) -> dict:
        return {"winner": self.winner + 1, "racers": self.cfg.race_racers}
