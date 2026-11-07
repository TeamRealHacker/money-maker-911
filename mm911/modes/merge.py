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
    chain: int = 0            # how many merges in a row created this ball (combo chain)
    born_vt: float = 0.0      # video time it appeared


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: tuple              # (tier, random index into particle_colors)
    size: float
    rot: float = 0.0
    spin: float = 0.0
    max_life: float = 1.0


@dataclass
class SoundEvent:
    t: float                  # simulation time
    tier: int
    kind: str  # "drop" | "merge" | "final"
    vt: float = -1.0          # VIDEO time in seconds (what the audio track needs; differs with speed / slow-mo)


@dataclass
class Popup:
    """Floating text in the world (combo multipliers)."""
    x: float
    y: float
    text: str
    born: float               # video time
    tier: int
    life: float = 0.9


@dataclass
class Banner:
    """Full-width 'NEW: Tier 6!' banner."""
    tier: int
    born: float               # video time
    life: float = 1.1


def container_points(shape: str, cx: float, cy: float, r: float, n: int = 64,
                     custom: list | None = None) -> list[tuple[float, float]]:
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
    elif shape in ("triangle", "pentagon", "diamond"):
        # triangle points down (a funnel), pentagon has a flat top, diamond is a square on its tip
        k, start = {"triangle": (3, math.pi / 2), "pentagon": (5, math.pi / 2), "diamond": (4, math.pi / 2)}[shape]
        for i in range(k):
            a = start + 2 * math.pi * i / k
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    elif shape == "rounded":
        # rounded square (superellipse)
        for i in range(n):
            a = 2 * math.pi * i / n
            ca, sa = math.cos(a), math.sin(a)
            pts.append((cx + r * 0.92 * math.copysign(abs(ca) ** 0.5, ca),
                        cy + r * 0.92 * math.copysign(abs(sa) ** 0.5, sa)))
    elif shape == "custom":
        if custom and len(custom) >= 3:
            try:
                return [(cx + float(x) * r, cy + float(y) * r) for x, y in custom]
            except (TypeError, ValueError):
                pass
        return container_points("circle", cx, cy, r, n)
    else:
        return container_points("circle", cx, cy, r, n)
    return pts


def top_inside(pts: list[tuple[float, float]], x: float) -> float | None:
    """Highest (smallest y) point where a vertical line at x crosses the outline."""
    best = None
    for i in range(len(pts)):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % len(pts)]
        if (x1 - x) * (x2 - x) <= 0 and x1 != x2:
            y = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
            best = y if best is None else min(best, y)
    return best


class MergeSim:
    def __init__(self, cfg: MergeConfig, seed: int | None = None):
        cfg.clamp()
        self.cfg = cfg
        self.rng = random.Random(cfg.seed if seed is None else seed)
        # extra effect randomness (particle colour/rotation, near-miss) has its own stream
        self.fx = random.Random((cfg.seed if seed is None else seed) * 7919 + 17)
        self.space = pymunk.Space()
        self.space.gravity = (0, cfg.gravity)
        self.space.iterations = 20
        self.t = 0.0             # simulation time (scaled by speed / slow motion)
        self.vt = 0.0            # video time (real seconds of output)
        self.balls: list[Ball] = []
        self.particles: list[Particle] = []
        self.events: list[SoundEvent] = []
        self.best_tier = 0
        self.merges = 0
        self.finished_at: float | None = None      # video time of the Final Form
        self.final_pos: tuple[float, float] | None = None
        self._next_spawn = 0.4
        self._pending: list[tuple[pymunk.Shape, pymunk.Shape]] = []
        self.cx = cfg.width / 2
        self.cy = cfg.height * cfg.container_y
        self.angle = 0.0
        # juice
        self.popups: list[Popup] = []
        self.banners: list[Banner] = []
        self.combo = 0
        self.best_combo = 0
        self._last_merge_vt = -99.0
        self.shake = 0.0
        self.tension = False          # one tier away from the Final Form
        self._slow_until = -1.0       # video time
        self._slow_len = 1.0
        self._slow_factor = 1.0
        self._near_miss_done = False
        self._build_container()
        for tier in range(cfg.tiers):
            self.space.on_collision(tier + 1, tier + 1, pre_solve=self._on_same)
        self.spout_x = self.cx
        self.fill_cap = cfg.fill_cap

    # ---------- setup ----------
    def _build_container(self) -> None:
        c = self.cfg
        self.wall_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        self.wall_body.position = (self.cx, self.cy)
        self.space.add(self.wall_body)
        pts = container_points(c.container_shape, 0, 0, c.container_radius, custom=c.container_points)
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
        ball = Ball(shape, tier, self.t, born_vt=self.vt)
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
        top = top_inside(self.outline_world(), self.spout_x)
        if top is not None:   # narrow tops (triangle, star...) : drop just under the wall
            y = max(y, top + c.container_thickness + r + 6)
        self.add_ball(tier, self.spout_x, y, (self.rng.uniform(-40, 40), c.drop_speed))
        self.events.append(SoundEvent(self.t, tier, "drop", vt=self.vt))

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
            c = self.cfg
            self._burst(mid, new_tier, 10 + new_tier * 3)
            # chain = a ball made by a merge merging again quickly (a real cascade)
            win = c.combo_window
            chain = 1 + max((x.chain if self.vt - x.born_vt <= win else 0) for x in (ba, bb))
            self._on_merge_juice(mid, new_tier, chain)
            if new_tier >= c.tiers - 1:
                nb = self.add_ball(c.tiers - 1, *mid, vel)
                self.best_tier = max(self.best_tier, c.tiers - 1)
                self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
                if self.finished_at is None:
                    self.finished_at = self.vt
                    self.final_pos = mid
                    self._burst(mid, c.tiers - 1, 120)
                    if c.slowmo_final:
                        self._slow(c.slowmo_factor, c.slowmo_seconds)
                    if c.shake_strength > 0:
                        self.shake = max(self.shake, c.shake_strength * 2.2)
            else:
                nb = self.add_ball(new_tier, *mid, vel)
                if new_tier > self.best_tier and c.tier_banners and new_tier >= c.banner_min_tier - 1:
                    self.banners = [Banner(new_tier, self.vt)]
                self.best_tier = max(self.best_tier, new_tier)
                self.events.append(SoundEvent(self.t, new_tier, "merge", vt=self.vt))
            nb.pop = 0.0
            nb.chain = chain
        self._pending.clear()

    def _on_merge_juice(self, pos, new_tier: int, chain: int) -> None:
        """Combo chain, popups and screen shake for one merge."""
        c = self.cfg
        self.combo = chain
        self._last_merge_vt = self.vt
        self.best_combo = max(self.best_combo, self.combo)
        if c.combo_popups and self.combo >= max(2, c.combo_min):
            text = c.combo_text.replace("{n}", str(self.combo))
            # only the newest combo is on screen: a busy pile never turns into a wall of text
            self.popups = []
            self.popups.append(Popup(pos[0], pos[1] - c.tier_radius(new_tier), text, self.vt, new_tier))
        if c.shake_strength > 0 and new_tier >= c.shake_min_tier - 1:
            k = 0.4 + 0.6 * new_tier / max(1, c.tiers - 1)
            self.shake = max(self.shake, c.shake_strength * k)

    def _slow(self, factor: float, seconds: float) -> None:
        self._slow_factor = factor
        self._slow_len = max(0.05, seconds)
        self._slow_until = self.vt + self._slow_len

    def time_scale(self) -> float:
        """Sim speed right now: slow motion eases back to normal over the last 40% of its window."""
        left = self._slow_until - self.vt
        if left <= 0:
            return 1.0
        k = min(1.0, left / (self._slow_len * 0.4))
        return 1.0 + (self._slow_factor - 1.0) * k

    def _check_tension(self) -> None:
        c = self.cfg
        if self.finished_at is not None:
            self.tension = False
            return
        pen = [b for b in self.balls if b.tier == c.tiers - 2]
        self.tension = bool(pen) and c.near_miss
        if not (c.near_miss and len(pen) >= 2 and not self._near_miss_done):
            return
        a, b = pen[0].shape.body.position, pen[1].shape.body.position
        r = pen[0].shape.radius
        if math.hypot(a.x - b.x, a.y - b.y) < r * 3.2:
            self._near_miss_done = True
            if self.fx.random() < c.near_miss_chance:   # randomized: not every video gets the pause
                self._slow(0.45, self.fx.uniform(0.6, 1.1))

    def _burst(self, pos, tier: int, n: int) -> None:
        c = self.cfg
        n = int(round(n * c.particle_amount))
        r = c.tier_radius(tier)
        ncol = max(1, len(c.particle_colors))
        for _ in range(n):
            # the same 4 draws per particle as v0.3 stay on the gameplay rng, so old seeds re-render identically;
            # the new extras (colour, rotation, spin) come from the effects rng
            a = self.rng.uniform(0, 2 * math.pi)
            s = self.rng.uniform(150, 600) * (1 + tier * 0.08) * c.particle_speed
            life = self.rng.uniform(0.4, 0.9) * (1.4 if c.particle_style == "confetti" else 1.0)
            size = self.rng.uniform(4, 10)
            self.particles.append(Particle(pos[0] + math.cos(a) * r * 0.5, pos[1] + math.sin(a) * r * 0.5,
                                           math.cos(a) * s, math.sin(a) * s,
                                           life, (tier, self.fx.randrange(ncol)), size,
                                           self.fx.uniform(0, 360), self.fx.uniform(-720, 720), life))

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        """Advance one video frame of dt seconds."""
        real_dt = dt
        c = self.cfg
        dt *= c.speed * self.time_scale()
        if c.spin_wobble:
            w = c.container_spin + c.spin_wobble * math.sin(2 * math.pi * self.t / max(0.2, c.spin_wobble_period))
            self.wall_body.angular_velocity = math.radians(w)
        if self.finished_at is None and self.t >= self._next_spawn and self._fill_ratio() < self.fill_cap:
            self._spawn()
            j = max(0.0, min(0.9, c.spawn_jitter))
            self._next_spawn = self.t + c.spawn_interval * self.rng.uniform(1 - j, 1 + j)
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
        drag = 0.97 if c.particle_style != "confetti" else 0.94
        for p in self.particles:
            p.x += p.vx * dt; p.y += p.vy * dt
            p.vy += c.particle_gravity * dt * (0.35 if c.particle_style == "confetti" else 1.0)
            p.vx *= drag
            p.rot += p.spin * dt
            p.life -= dt
        self.particles = [p for p in self.particles if p.life > 0]
        self.popups = [p for p in self.popups if self.vt - p.born < p.life]
        self.banners = [b for b in self.banners if self.vt - b.born < b.life]
        self.shake *= math.exp(-real_dt * 9)
        if self.shake < 0.3:
            self.shake = 0.0
        self._check_tension()
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
