"""🎯 Plinko: balls rain through a field of pegs into slots worth different points. The edges pay most. Every peg
hit plays a note, every landing floats a +points popup; reach the target score for the ending.

Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export), with real gravity."""
from __future__ import annotations

import math

import pymunk

from .breaker import BreakerSim, BBall, pitch_ladder
from .merge import SoundEvent, Popup


def slot_values(n: int) -> list[float]:
    """Centre pays 0.5, the edges 5 (more slots = smoother steps), mirrored."""
    c = (n - 1) / 2
    dmax = max(1.0, c)
    base = 10.0 ** (1.0 / dmax)
    vals = [round(0.5 * base ** abs(i - c), 1) for i in range(n)]
    return [int(v) if float(v).is_integer() else v for v in vals]


class PlinkoSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self._dropped = 0
        self._score = 0.0
        self.pegs: list = []
        self.peg_hit: dict = {}
        self.slot_hit: dict = {}
        self._stuck: dict = {}
        self._gone: list = []
        super().__init__(cfg, seed)
        self.constant_speed = False
        self.space.gravity = (0, cfg.plinko_gravity)
        self.counter_text = cfg.plinko_counter_text
        self.final_text = cfg.plinko_final_text
        self.space.on_collision(1, 4, begin=self._on_peg)
        self._last_break_vt = self.vt

    @property
    def score(self) -> float:
        return min(self._score, float(self.total)) if self.finished_at is not None else self._score

    def _start_balls(self) -> int:
        return 0

    def _build_bricks(self) -> None:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        self.bricks = []
        self.total = max(1, int(c.plinko_target))
        W = x1 - x0
        n = c.plinko_slots
        self.slot_w = W / n
        self.slot_top = y1 - 0.11 * (y1 - y0)
        self.values = slot_values(n)
        body = self.space.static_body
        # dividers
        for i in range(1, n):
            x = x0 + i * self.slot_w
            s = pymunk.Segment(body, (x, self.slot_top), (x, y1), 3)
            s.elasticity, s.friction = 0.4, 0.2
            self.space.add(s)
        # pegs: staggered rows
        rows = c.plinko_rows
        gap_x = max(self.slot_w * 0.6, 3.4 * c.plinko_ball_radius)
        top = y0 + 0.16 * (y1 - y0)
        bot = self.slot_top - 0.07 * (y1 - y0)
        step_y = (bot - top) / max(1, rows - 1)
        pr = max(3.0, min(c.plinko_peg_radius, (gap_x - 2.6 * c.plinko_ball_radius) / 2))
        self.peg_r = pr
        for r in range(rows):
            off = (gap_x / 2) if r % 2 else 0.0
            x = x0 + off
            while x <= x1 + 1:
                if x0 + 4 < x < x1 - 4 or r % 2 == 0:
                    sh = pymunk.Circle(body, pr, (x, top + r * step_y))
                    sh.elasticity, sh.friction, sh.collision_type = 0.55, 0.1, 4
                    self.space.add(sh)
                    self.pegs.append((x, top + r * step_y, r, sh))
                x += gap_x
        self._peg_by_shape = {id(p[3]): p for p in self.pegs}
        self.drop_y = y0 + 0.07 * (y1 - y0)

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        r = self._radius()
        expected = self.total * min(1.0, self.vt / max(1.0, 0.7 * c.max_seconds))
        behind = max(0.0, min(1.0, (expected - self._score) / max(1.0, self.total * 0.5)))
        spread = 0.12 + 0.8 * behind                       # drop closer to the edges when behind schedule
        cx = (x0 + x1) / 2
        x = cx + self.rng.uniform(-1, 1) * spread * (x1 - x0 - 4 * r) / 2
        ball = super()._add_ball((x, self.drop_y))
        ball.shape.elasticity = 0.5
        ball.shape.filter = pymunk.ShapeFilter(group=1)
        ball.shape.body.velocity = (self.rng.uniform(-60, 60), 0)
        self._dropped += 1
        return ball

    def _on_peg(self, arbiter, space, data) -> None:
        peg = self._peg_by_shape.get(id(arbiter.shapes[1]))
        if peg is None:
            return
        c = self.cfg
        self.peg_hit[id(peg[3])] = self.vt
        self.hits += 1
        k = peg[2] / max(1, c.plinko_rows - 1)
        self.events.append(SoundEvent(self.t, min(c.tiers - 1, peg[2] % c.tiers), "drop", vt=self.vt,
                                      pitch=c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * (1 - k) * 0.7
                                      + self.fx.uniform(-0.5, 0.5)))

    def _land(self, ball: BBall) -> None:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        p = ball.shape.body.position
        i = max(0, min(c.plinko_slots - 1, int((p.x - x0) / self.slot_w)))
        val = self.values[i]
        self._score += val
        self.broken = min(self.total, int(self._score))
        self._last_break_vt = self.vt
        self.slot_hit[i] = self.vt
        txt = f"+{val:g}"
        self.popups.append(Popup(min(x1 - 70, max(x0 + 70, p.x)), p.y - 30, txt, self.vt, min(c.tiers - 1, i)))
        k = min(1.0, val / self.values[0]) if self.values[0] else 0
        self.events.append(SoundEvent(self.t, min(c.tiers - 1, i), "merge", vt=self.vt,
                                      pitch=pitch_ladder(c, int(self._score), self.total) + (3 if val >= 2 else 0)))
        self._pop(p.x, p.y, 8 + int(val * 2), i)
        if c.shake_strength > 0 and val >= 4:
            self.shake = max(self.shake, c.shake_strength * 0.6)
        self._gone.append(ball)
        ball.landed_vt = self.vt
        if self._score >= self.total and self.finished_at is None:
            self.finished_at = self.vt
            self.final_pos = (p.x, p.y)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.0)
            self._pop(p.x, p.y, 60, i)

    def _pop(self, x: float, y: float, n: int, tier: int) -> None:
        from .merge import Particle
        c = self.cfg
        for _ in range(int(round(n * c.particle_amount))):
            a = self.fx.uniform(math.pi, 2 * math.pi)
            s = self.fx.uniform(120, 480) * c.particle_speed
            life = self.fx.uniform(0.35, 0.8)
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s, life, (tier, self.fx.randrange(max(1, len(c.particle_colors)))),
                                           self.fx.uniform(3, 7), self.fx.uniform(0, 360), self.fx.uniform(-540, 540), life))

    def step(self, dt: float) -> None:
        c = self.cfg
        if self.finished_at is None:
            while self._dropped < c.plinko_balls and self.vt >= self._dropped * c.plinko_interval:
                self._add_ball()
        super().step(dt)
        x0, y0, x1, y1 = self.arena
        r = self._radius()
        for ball in list(self.balls):
            body = ball.shape.body
            p = body.position
            if p.y > self.slot_top + r * 1.1:                      # in a slot: count it, let it sink away
                if ball not in self._gone:
                    self._land(ball)
            if ball in self._gone and (p.y > y1 - r * 0.6 or self.vt - ball.landed_vt > 0.3):
                self.space.remove(ball.shape, body)
                self.balls.remove(ball)
                self._gone.remove(ball)
                continue
            if ball in self._gone:
                continue
            # balanced on a peg: nudge it
            if body.velocity.length < 35:
                n = self._stuck.get(id(ball), 0) + dt
                self._stuck[id(ball)] = n
                if n > 0.4:
                    body.apply_impulse_at_local_point((self.rng.choice((-1, 1)) * 260, -60))
                    self._stuck[id(ball)] = 0.0
            else:
                self._stuck[id(ball)] = 0.0
        self.popups = [pu for pu in self.popups if self.vt - pu.born < pu.life]

    def _radius(self) -> float:
        return self.cfg.plinko_ball_radius

    def stats(self) -> dict:
        return {"score": round(self._score, 1), "target": self.total, "dropped": self._dropped}
