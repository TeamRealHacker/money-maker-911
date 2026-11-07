"""🍉 Merge Evolution: items drop into a container and merge up tiers until the Final Form."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import pymunk

from ..config import MergeConfig


@dataclass
class Ball:
    shape: pymunk.Circle
    tier: int
    born: float
    pop: float = 0.0          # grow-in animation 0..1


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: tuple
    size: float


@dataclass
class SoundEvent:
    t: float
    tier: int
    kind: str  # "drop" | "merge" | "final"


def container_points(shape: str, cx: float, cy: float, r: float, n: int = 64) -> list[tuple[float, float]]:
    """Outline of the container as a closed polygon (clockwise, screen coords y-down)."""
    pts = []
    if shape == "circle":
        for i in range(n):
            a = 2 * math.pi * i / n
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    elif shape in ("hexagon", "octagon", "square"):
        k = {"hexagon": 6, "octagon": 8, "square": 4}[shape]
        off = math.pi / k if shape != "hexagon" else 0
        for i in range(k):
            a = 2 * math.pi * i / k + off
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    elif shape == "heart":
        for i in range(n):
            t = 2 * math.pi * i / n
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            pts.append((cx + x * r / 16.5, cy + y * r / 16.5 + r * 0.08))
    elif shape == "star":
        for i in range(10):
            a = -math.pi / 2 + math.pi * i / 5
            rr = r if i % 2 == 0 else r * 0.62
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    else:
        return container_points("circle", cx, cy, r, n)
    return pts


class MergeSim:
    def __init__(self, cfg: MergeConfig, seed: int | None = None):
        self.cfg = cfg
        self.rng = random.Random(cfg.seed if seed is None else seed)
        self.space = pymunk.Space()
        self.space.gravity = (0, cfg.gravity)
        self.space.iterations = 20
        self.t = 0.0
        self.balls: list[Ball] = []
        self.particles: list[Particle] = []
        self.events: list[SoundEvent] = []
        self.best_tier = 0
        self.merges = 0
        self.finished_at: float | None = None
        self.final_pos: tuple[float, float] | None = None
        self._next_spawn = 0.4
        self._pending: list[tuple[pymunk.Shape, pymunk.Shape]] = []
        self.cx = cfg.width / 2
        self.cy = cfg.height * 0.53
        self.angle = 0.0
        self._build_container()
        for tier in range(cfg.tiers):
            self.space.on_collision(tier + 1, tier + 1, pre_solve=self._on_same)
        self.spout_x = self.cx
        self.fill_cap = 0.8

    # ---------- setup ----------
    def _build_container(self) -> None:
        c = self.cfg
        self.wall_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        self.wall_body.position = (self.cx, self.cy)
        self.space.add(self.wall_body)
        pts = container_points(c.container_shape, 0, 0, c.container_radius)
        self.outline_local = pts
        self.walls = []
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            seg = pymunk.Segment(self.wall_body, a, b, c.container_thickness / 2)
            seg.friction = c.friction
            seg.elasticity = c.bounce
            self.walls.append(seg)
        self.space.add(*self.walls)
        self.wall_body.angular_velocity = math.radians(c.container_spin)

    def outline_world(self) -> list[tuple[float, float]]:
        ca, sa = math.cos(self.wall_body.angle), math.sin(self.wall_body.angle)
        return [(self.cx + x * ca - y * sa, self.cy + x * sa + y * ca) for x, y in self.outline_local]

    # ---------- gameplay ----------
    def _on_same(self, arbiter: pymunk.Arbiter, space: pymunk.Space, data) -> None:
        a, b = arbiter.shapes
        self._pending.append((a, b))

    def _spawn_tier(self) -> int:
        c = self.cfg
        # lots of forms (10-15): drop bigger items too, otherwise the Final Form is unreachable in 60 s
        extra = max(0, c.tiers - 7) + max(0, c.tiers - 10)
        hi = max(1, min(c.spawn_max_tier + extra, c.tiers - 1))
        # weight small tiers more; slowly allow bigger drops as time goes on
        boost = min(2, int(self.t / 20))
        weights = [1.0 / (1 + i) ** 1.2 for i in range(min(hi + boost, c.tiers - 1))]
        return self.rng.choices(range(len(weights)), weights)[0]

    def add_ball(self, tier: int, x: float, y: float, vel=(0, 0)) -> Ball:
        c = self.cfg
        r = c.tier_radius(tier)
        mass = 1.0 * (tier + 1) ** 1.6
        body = pymunk.Body(mass, pymunk.moment_for_circle(mass, 0, r))
        body.position = (x, y)
        body.velocity = vel
        shape = pymunk.Circle(body, r)
        shape.friction = c.friction
        shape.elasticity = c.bounce
        shape.collision_type = tier + 1
        self.space.add(body, shape)
        ball = Ball(shape, tier, self.t)
        self.balls.append(ball)
        return ball

    def _fill_ratio(self) -> float:
        area = sum(math.pi * b.shape.radius ** 2 for b in self.balls)
        return area / (math.pi * self.cfg.container_radius ** 2)

    def _spawn(self) -> None:
        c = self.cfg
        tier = self._spawn_tier()
        r = c.tier_radius(tier)
        span = c.container_radius * 0.35
        self.spout_x = self.cx + math.sin(self.t * 1.7) * span * 0.6 + self.rng.uniform(-span, span) * 0.4
        y = self.cy - c.container_radius * 0.72 + r
        self.add_ball(tier, self.spout_x, y, (self.rng.uniform(-40, 40), 120))
        self.events.append(SoundEvent(self.t, tier, "drop"))

    def _process_merges(self) -> None:
        if not self._pending:
            return
        alive = {id(b.shape): b for b in self.balls}
        used = set()
        for a, b in self._pending:
            if id(a) in used or id(b) in used:
                continue
            ba, bb = alive.get(id(a)), alive.get(id(b))
            if not ba or not bb or ba.tier != bb.tier:
                continue
            used.add(id(a)); used.add(id(b))
            tier = ba.tier
            pa, pb = a.body.position, b.body.position
            mid = ((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)
            vel = ((a.body.velocity.x + b.body.velocity.x) / 2, (a.body.velocity.y + b.body.velocity.y) / 2)
            for s in (a, b):
                self.space.remove(s.body, s)
            self.balls = [x for x in self.balls if x.shape is not a and x.shape is not b]
            self.merges += 1
            new_tier = tier + 1
            self._burst(mid, new_tier, 10 + new_tier * 3)
            if new_tier >= self.cfg.tiers - 1:
                nb = self.add_ball(self.cfg.tiers - 1, *mid, vel)
                self.best_tier = max(self.best_tier, self.cfg.tiers - 1)
                self.events.append(SoundEvent(self.t, self.cfg.tiers - 1, "final"))
                if self.finished_at is None:
                    self.finished_at = self.t
                    self.final_pos = mid
                    self._burst(mid, self.cfg.tiers - 1, 120)
            else:
                nb = self.add_ball(new_tier, *mid, vel)
                self.best_tier = max(self.best_tier, new_tier)
                self.events.append(SoundEvent(self.t, new_tier, "merge"))
            nb.pop = 0.0
        self._pending.clear()

    def _burst(self, pos, tier: int, n: int) -> None:
        r = self.cfg.tier_radius(tier)
        for _ in range(n):
            a = self.rng.uniform(0, 2 * math.pi)
            s = self.rng.uniform(150, 600) * (1 + tier * 0.08)
            self.particles.append(Particle(pos[0] + math.cos(a) * r * 0.5, pos[1] + math.sin(a) * r * 0.5,
                                           math.cos(a) * s, math.sin(a) * s,
                                           self.rng.uniform(0.4, 0.9), (tier,), self.rng.uniform(4, 10)))

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        dt *= self.cfg.speed
        if self.finished_at is None and self.t >= self._next_spawn and self._fill_ratio() < self.fill_cap:
            self._spawn()
            self._next_spawn = self.t + self.cfg.spawn_interval * self.rng.uniform(0.8, 1.2)
        sub = 4
        for _ in range(sub):
            self.space.step(dt / sub)
            self._process_merges()
        # keep anything that escaped (fast spin) inside
        lim = self.cfg.container_radius * 1.4
        for b in list(self.balls):
            p = b.shape.body.position
            if math.hypot(p.x - self.cx, p.y - self.cy) > lim:
                self.space.remove(b.shape.body, b.shape)
                self.balls.remove(b)
        for b in self.balls:
            b.pop = min(1.0, b.pop + dt * 6)
        for p in self.particles:
            p.x += p.vx * dt; p.y += p.vy * dt
            p.vy += 900 * dt; p.vx *= 0.97
            p.life -= dt
        self.particles = [p for p in self.particles if p.life > 0]
        self.t += dt

    @property
    def done(self) -> bool:
        c = self.cfg
        if self.finished_at is not None:
            return self.t >= self.finished_at + c.end_hold_seconds
        return self.t >= c.max_seconds

    @property
    def won(self) -> bool:
        return self.finished_at is not None
