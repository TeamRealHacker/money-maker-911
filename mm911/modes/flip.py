"""🔄 Gravity Flip: a crowd of pictures tumbles around a box; every few seconds gravity flips (up / down, or
spinning round all four walls) and everything flies to the other side. Each flip plays a higher note, the counter
climbs to the target, FLIPPED! at the end. Wall and ball-to-ball bumps play quiet pitched notes.

Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export), with real gravity."""
from __future__ import annotations

import math

import pymunk

from .breaker import BreakerSim, BBall
from .merge import SoundEvent, Particle

# gravity directions in play order
DIRS = {"down": (0.0, 1.0), "up": (0.0, -1.0), "right": (1.0, 0.0), "left": (-1.0, 0.0)}


def flip_sequence(pattern: str, n: int, rng) -> list[str]:
    """Gravity direction before flip 0..n (index 0 = start). Never the same direction twice in a row."""
    seq = ["down"]
    cyc = ["right", "up", "left", "down"]            # spin: down -> right -> up -> left -> ...
    for i in range(n):
        if pattern == "spin":
            seq.append(cyc[i % 4])
        elif pattern == "random":
            seq.append(rng.choice([d for d in DIRS if d != seq[-1]]))
        else:                                        # updown
            seq.append("up" if seq[-1] == "down" else "down")
    return seq


class FlipSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self.flips = 0
        self.flip_vt = -9.0
        self.dir = "down"
        self._last_note = -9.0
        super().__init__(cfg, seed)
        self.constant_speed = False
        self.seq = flip_sequence(cfg.flip_pattern, self.total, self.rng)
        self.set_dir(self.seq[0])
        self.counter_text = cfg.flip_counter_text
        self.final_text = cfg.flip_final_text
        self._last_break_vt = self.vt
        self.space.on_collision(1, 1, begin=self._on_ball)

    def set_dir(self, d: str) -> None:
        self.dir = d
        gx, gy = DIRS[d]
        g = self.cfg.flip_gravity
        self.space.gravity = (gx * g, gy * g)

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.flip_count))

    def _radius(self) -> float:
        return self.cfg.flip_ball_radius

    def _start_balls(self) -> int:
        return self.cfg.flip_balls

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        r = self._radius()
        if pos is None:                              # a loose heap near the floor (no overlaps at the start)
            i = len(self.balls)
            per = max(1, int((x1 - x0) // (2.2 * r)))
            step = (x1 - x0 - 2.8 * r) / max(1, per - 1)
            pos = (x0 + 1.4 * r + (i % per) * step + self.rng.uniform(-0.15, 0.15) * r,
                   y1 - 1.3 * r - (i // per) * 2.15 * r)
        ball = super()._add_ball(pos)
        ball.shape.elasticity = 0.72
        ball.shape.friction = 0.25
        ball.shape.body.velocity = (self.rng.uniform(-120, 120), self.rng.uniform(-120, 120))
        return ball

    def _on_wall(self, arbiter, space, data) -> None:
        self.hits += 1
        self._note(arbiter.shapes[0].body)

    def _on_ball(self, arbiter, space, data) -> None:
        self.hits += 1
        if arbiter.total_impulse.length > 120:
            self._note(arbiter.shapes[0].body)

    def _note(self, body) -> None:
        """quiet pitched bump (rate-limited so a pile settling is not a buzz)"""
        c = self.cfg
        if self.finished_at is not None or self.vt - self._last_note < 0.05:
            return
        self._last_note = self.vt
        k = self.flips / max(1, self.total)
        self.events.append(SoundEvent(self.t, min(c.tiers - 1, self.flips % c.tiers), "drop", vt=self.vt,
                                      pitch=c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * k
                                      + self.fx.uniform(-1.0, 1.0)))

    def _flip(self) -> None:
        c = self.cfg
        self.flips += 1
        self.broken = self.flips
        self.flip_vt = self.vt
        self._last_break_vt = self.vt
        self.set_dir(self.seq[self.flips])
        gx, gy = DIRS[self.dir]
        for b in self.balls:                         # a little kick the right way, so nothing stays glued down
            b.shape.body.apply_impulse_at_local_point((gx * 90 + self.rng.uniform(-40, 40), gy * 90 + self.rng.uniform(-40, 40)))
        k = self.flips / self.total
        self.events.append(SoundEvent(self.t, min(c.tiers - 1, self.flips % c.tiers), "merge", vt=self.vt,
                                      pitch=c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * k))
        if c.shake_strength > 0:
            self.shake = max(self.shake, c.shake_strength * 0.8)
        x0, y0, x1, y1 = self.arena
        for _ in range(int(round(16 * c.particle_amount))):      # sparks along the wall that is now the floor
            if gx:
                x, y = (x1 if gx > 0 else x0), self.fx.uniform(y0, y1)
            else:
                x, y = self.fx.uniform(x0, x1), (y1 if gy > 0 else y0)
            a = math.atan2(-gy, -gx) + self.fx.uniform(-0.9, 0.9)
            s = self.fx.uniform(120, 420) * c.particle_speed
            life = self.fx.uniform(0.3, 0.7)
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s, life,
                                           (self.flips % c.tiers, self.fx.randrange(max(1, len(c.particle_colors)))),
                                           self.fx.uniform(3, 7), self.fx.uniform(0, 360), self.fx.uniform(-540, 540), life))
        if self.flips >= self.total:
            self.finished_at = self.vt
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            self.final_pos = (cx, cy)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.0)

    def step(self, dt: float) -> None:
        c = self.cfg
        if self.finished_at is None and self.vt >= (self.flips + 1) * c.flip_every:
            self._flip()
        super().step(dt)
        # a ball that squeezes into another ball's overlap and stalls keeps moving anyway (gravity); nothing to nudge

    @property
    def best_tier(self) -> int:
        return min(self.cfg.tiers - 1, self.flips * self.cfg.tiers // max(1, self.total))

    def stats(self) -> dict:
        return {"flips": self.flips, "target": self.total, "balls": len(self.balls)}
