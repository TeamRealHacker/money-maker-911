"""🌀 Escape: a ball bounces inside spinning rings, each with a gap. Every time it slips through a gap,
that ring shatters and the next one is in the way. The pitch rises with every escape; escape them all
for the ending.

Shares MergeConfig (settings prefixed escape_*), the sound engine (SoundEvent with a pitch ladder), the
particle / shake / slow-mo / tension juice and the export pipeline with Merge."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pymunk

from .merge import Particle, SoundEvent, Banner


@dataclass
class Ring:
    index: int
    radius: float
    gap: float                 # gap width in radians (grows with the assist)
    gap0: float                # gap centre angle at rest (radians, local)
    body: pymunk.Body
    shapes: list
    escaped_vt: float | None = None
    built_gap: float = 0.0     # gap the wall segments were built with

    @property
    def angle(self) -> float:
        return self.body.angle


def ring_layout(cfg) -> list[float]:
    n = max(1, int(cfg.escape_rings))
    lo, hi = float(cfg.escape_inner_radius), float(cfg.escape_outer_radius)
    if n == 1:
        return [lo]
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def ball_radius(cfg, escaped: int = 0) -> float:
    """Ball size: escape_ball_radius, grown per escape, never bigger than fits through the rings."""
    radii = ring_layout(cfg)
    th = cfg.escape_ring_thickness
    r = cfg.escape_ball_radius * (cfg.escape_ball_growth ** escaped)
    cap = radii[0] - th / 2 - 4
    if escaped < len(radii):
        gap_len = radii[min(escaped, len(radii) - 1)] * math.radians(max(10.0, cfg.escape_gap_deg - cfg.escape_gap_jitter))
        cap = min(cap if escaped == 0 else radii[escaped] - th / 2 - 4, gap_len * 0.42)
    return max(4.0, min(r, cap))


def pitch_ladder(cfg, i: int) -> float:
    """Semitones for the i-th escape: low -> high across all rings."""
    n = max(1, int(cfg.escape_rings))
    k = i / (n - 1) if n > 1 else 1.0
    return cfg.escape_pitch_low + (cfg.escape_pitch_high - cfg.escape_pitch_low) * k


class EscapeSim:
    def __init__(self, cfg, seed: int | None = None):
        cfg.clamp()
        self.cfg = cfg
        s = cfg.seed if seed is None else seed
        self.rng = random.Random(s)
        self.fx = random.Random(s * 7919 + 17)
        self.space = pymunk.Space()
        self.space.gravity = (0, cfg.escape_gravity)
        self.space.iterations = 15
        self.t = 0.0
        self.vt = 0.0
        self.cx = cfg.width / 2
        self.cy = cfg.height * cfg.escape_center_y
        self.particles: list[Particle] = []
        self.events: list[SoundEvent] = []
        self.banners: list[Banner] = []
        self.popups: list = []
        self.escaped = 0
        self.bounces = 0
        self.finished_at: float | None = None
        self.final_pos = None
        self.shake = 0.0
        self.tension = False
        self._slow_until = -1.0
        self._slow_len = 1.0
        self._slow_factor = 1.0
        self._last_escape_vt = 0.0
        self._last_bounce_vt = -1.0
        self.trail: list[tuple[float, float]] = []
        self.rings: list[Ring] = []
        self._build_rings()
        self._build_ball()
        self.space.on_collision(1, 2, begin=self._on_bounce)

    # ---------- setup ----------
    def _build_rings(self) -> None:
        c = self.cfg
        th = c.escape_ring_thickness
        for i, R in enumerate(ring_layout(c)):
            gap = math.radians(max(8.0, c.escape_gap_deg + self.rng.uniform(-c.escape_gap_jitter, c.escape_gap_jitter)))
            gap0 = self.rng.uniform(0, 2 * math.pi)
            body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
            body.position = (self.cx, self.cy)
            spin = c.escape_spin * (1 + i * c.escape_spin_step)
            if c.escape_alternate and i % 2 == 1:
                spin = -spin
            body.angular_velocity = math.radians(spin)
            ring = Ring(i, R, gap, gap0, body, [])
            self.space.add(body)
            ring.shapes = self._segments(ring)
            ring.built_gap = ring.gap
            self.rings.append(ring)

    def _segments(self, ring: Ring) -> list:
        c = self.cfg
        th = c.escape_ring_thickness
        arc = 2 * math.pi - ring.gap
        n = max(8, int(ring.radius * arc / 14))
        a0 = ring.gap0 + ring.gap / 2
        pts = [(ring.radius * math.cos(a0 + arc * k / n), ring.radius * math.sin(a0 + arc * k / n)) for k in range(n + 1)]
        segs = []
        for a, b in zip(pts, pts[1:]):
            s = pymunk.Segment(ring.body, a, b, th / 2)
            s.elasticity = c.escape_bounce
            s.friction = 0.0
            s.collision_type = 2
            segs.append(s)
        self.space.add(*segs)
        return segs

    def _build_ball(self) -> None:
        c = self.cfg
        r = ball_radius(c, 0)
        body = pymunk.Body(1.0, pymunk.moment_for_circle(1.0, 0, r))
        body.position = (self.cx + self.rng.uniform(-r, r), self.cy + self.rng.uniform(-r, r))
        a = self.rng.uniform(0, 2 * math.pi)
        body.velocity = (math.cos(a) * c.escape_ball_speed, math.sin(a) * c.escape_ball_speed)
        shape = pymunk.Circle(body, r)
        shape.elasticity = c.escape_bounce
        shape.friction = 0.0
        shape.collision_type = 1
        self.space.add(body, shape)
        self.ball = shape

    @property
    def ball_r(self) -> float:
        return self.ball.radius

    @property
    def best_tier(self) -> int:
        """Ball look index (the ball evolves through the tier pictures as it escapes)."""
        if not self.cfg.escape_evolve:
            return 0
        return min(self.escaped, self.cfg.tiers - 1)

    def alive_rings(self) -> list[Ring]:
        return [r for r in self.rings if r.escaped_vt is None]

    # ---------- events ----------
    def _on_bounce(self, arbiter, space, data) -> None:
        self.bounces += 1
        if self.vt - self._last_bounce_vt >= 0.06:
            self._last_bounce_vt = self.vt
            tier = self.best_tier
            self.events.append(SoundEvent(self.t, tier, "drop", vt=self.vt,
                                          pitch=pitch_ladder(self.cfg, self.escaped) + self.cfg.escape_bounce_pitch))
        p = arbiter.contact_point_set.points[0].point_a if arbiter.contact_point_set.points else self.ball.body.position
        self._spark(p, 4)

    def _spark(self, pos, n: int) -> None:
        c = self.cfg
        n = int(round(n * c.particle_amount))
        ncol = max(1, len(c.particle_colors))
        for _ in range(n):
            a = self.fx.uniform(0, 2 * math.pi)
            s = self.fx.uniform(80, 260) * c.particle_speed
            life = self.fx.uniform(0.2, 0.45)
            self.particles.append(Particle(pos[0], pos[1], math.cos(a) * s, math.sin(a) * s, life,
                                           (self.escaped, self.fx.randrange(ncol)), self.fx.uniform(2, 5),
                                           self.fx.uniform(0, 360), self.fx.uniform(-720, 720), life))

    def _shatter(self, ring: Ring) -> None:
        c = self.cfg
        n = int(round((50 + ring.radius * 0.25) * c.particle_amount))
        ncol = max(1, len(c.particle_colors))
        for k in range(n):
            a = 2 * math.pi * k / max(1, n) + self.fx.uniform(-0.05, 0.05)
            rel = (a - (ring.gap0 + ring.angle)) % (2 * math.pi)
            if rel < ring.gap / 2 or rel > 2 * math.pi - ring.gap / 2:
                continue   # no wall in the gap
            x, y = self.cx + ring.radius * math.cos(a), self.cy + ring.radius * math.sin(a)
            s = self.fx.uniform(120, 520) * c.particle_speed
            life = self.fx.uniform(0.5, 1.0) * (1.4 if c.particle_style == "confetti" else 1.0)
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s, life,
                                           (ring.index, self.fx.randrange(ncol)), self.fx.uniform(4, 9),
                                           self.fx.uniform(0, 360), self.fx.uniform(-720, 720), life))

    def _escape(self, ring: Ring) -> None:
        c = self.cfg
        ring.escaped_vt = self.vt
        self.space.remove(*ring.shapes)
        self.space.remove(ring.body)
        i = self.escaped
        self.escaped += 1
        self._last_escape_vt = self.vt
        if c.escape_shatter:
            self._shatter(ring)
        last = not self.alive_rings()
        if c.shake_strength > 0:
            self.shake = max(self.shake, c.shake_strength * (2.2 if last else 0.6 + 0.6 * i / max(1, c.escape_rings)))
        if last:
            self.finished_at = self.vt
            p = self.ball.body.position
            self.final_pos = (p.x, p.y)
            self.events.append(SoundEvent(self.t, self.best_tier, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            self._spark((p.x, p.y), 60)
        else:
            self.events.append(SoundEvent(self.t, min(i, c.tiers - 1), "merge", vt=self.vt, pitch=pitch_ladder(c, i)))
            if c.tier_banners and self.escaped >= c.banner_min_tier - 1 and c.escape_evolve and self.escaped < c.tiers:
                self.banners = [Banner(self.best_tier, self.vt)]
        # the ball grows with every escape (escape_ball_growth > 1)
        if c.escape_ball_growth != 1.0:
            r = ball_radius(c, self.escaped)
            if abs(r - self.ball.radius) > 0.01:
                self.ball.unsafe_set_radius(r)

    def _slow(self, factor: float, seconds: float) -> None:
        self._slow_factor = factor
        self._slow_len = max(0.05, seconds)
        self._slow_until = self.vt + self._slow_len

    def time_scale(self) -> float:
        left = self._slow_until - self.vt
        if left <= 0:
            return 1.0
        k = min(1.0, left / (self._slow_len * 0.4))
        return 1.0 + (self._slow_factor - 1.0) * k

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        real_dt = dt
        c = self.cfg
        dt *= c.speed * self.time_scale()
        alive = self.alive_rings()
        # assist: a ring nobody gets through for a while slowly opens its gap (keeps videos winnable)
        if c.escape_assist and alive and self.vt - self._last_escape_vt > c.escape_assist_after:
            ring = alive[0]
            grow = math.radians(c.escape_assist_speed) * dt
            if ring.gap < math.radians(150):
                ring.gap += grow
                if ring.gap - ring.built_gap > math.radians(1.5):   # rebuild the wall every 1.5 degrees
                    self.space.remove(*ring.shapes)
                    ring.shapes = self._segments(ring)
                    ring.built_gap = ring.gap
        sub = 4
        for _ in range(sub):
            self.space.step(dt / sub)
        body = self.ball.body
        # keep the energy up (and bounded): satisfying, never sleepy, never tunnelling
        v = body.velocity.length
        if v < c.escape_min_speed and v > 1e-3:
            body.velocity = body.velocity * (c.escape_min_speed / v)
        elif v > c.escape_max_speed:
            body.velocity = body.velocity * (c.escape_max_speed / v)
        elif v <= 1e-3:
            body.velocity = (0, -c.escape_min_speed)
        # escapes: the ball's centre is past the innermost ring = it went through the gap
        d = math.hypot(body.position.x - self.cx, body.position.y - self.cy)
        for ring in list(alive):
            if d > ring.radius + c.escape_ring_thickness * 0.5:
                self._escape(ring)
            else:
                break
        # free ball after the last ring: keep it on screen (bounce off the frame edges)
        if self.finished_at is not None:
            x, y = body.position
            vx, vy = body.velocity
            r = self.ball.radius
            if x < r or x > c.width - r:
                vx = -vx
            if y < r or y > c.height - r:
                vy = -abs(vy)
            body.velocity = (vx, vy)
        p = body.position
        self.trail.append((p.x, p.y))
        if len(self.trail) > max(0, int(c.escape_trail)):
            self.trail = self.trail[-max(0, int(c.escape_trail)):] if c.escape_trail > 0 else []
        drag = 0.97 if c.particle_style != "confetti" else 0.94
        for pt in self.particles:
            pt.x += pt.vx * dt
            pt.y += pt.vy * dt
            pt.vy += c.particle_gravity * dt * (0.35 if c.particle_style == "confetti" else 1.0)
            pt.vx *= drag
            pt.rot += pt.spin * dt
            pt.life -= dt
        self.particles = [pt for pt in self.particles if pt.life > 0]
        self.banners = [b for b in self.banners if self.vt - b.born < b.life]
        self.shake *= math.exp(-real_dt * 9)
        if self.shake < 0.3:
            self.shake = 0.0
        self.tension = c.near_miss and self.finished_at is None and len(self.alive_rings()) == 1
        self.t += dt
        self.vt += real_dt

    def shake_offset(self) -> tuple[float, float]:
        if not self.shake:
            return 0.0, 0.0
        return self.shake * math.sin(self.vt * 93.0), self.shake * math.cos(self.vt * 71.0)

    @property
    def done(self) -> bool:
        c = self.cfg
        if self.finished_at is not None:
            hold = c.end_hold_seconds + (c.slowmo_seconds * 0.5 if c.slowmo_final else 0.0)
            return self.vt >= self.finished_at + hold
        return self.vt >= (180.0 if c.until_finished else c.max_seconds)

    @property
    def won(self) -> bool:
        return self.finished_at is not None

    @property
    def merges(self) -> int:       # shared metadata name ("events that count")
        return self.escaped

    @property
    def best_combo(self) -> int:
        return 0

    def stats(self) -> dict:
        return {"escaped": self.escaped, "rings": len(self.rings), "bounces": self.bounces}
