"""🧱 Breaker: balls bounce around an arena and smash a wall of bricks. Every brick broken plays a note
a little higher than the last; every few bricks a new ball joins in; clear the wall for the ending.

Shares MergeConfig (settings prefixed breaker_*), sounds, particles, shake, slow-mo and export."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pymunk

from .merge import Particle, SoundEvent, Banner


@dataclass
class Brick:
    row: int
    col: int
    x: float          # centre
    y: float
    w: float
    h: float
    hp: int
    max_hp: int
    shape: pymunk.Poly | None = None
    broken_vt: float | None = None
    hit_vt: float = -9.0


@dataclass
class BBall:
    shape: pymunk.Circle
    index: int        # which picture it wears
    born_vt: float
    trail: list


def pattern_cells(pattern: str, rows: int, cols: int) -> list[tuple[int, int]]:
    cells = []
    for r in range(rows):
        for c in range(cols):
            u = (c + 0.5) / cols * 2 - 1           # -1..1 across
            v = (r + 0.5) / rows * 2 - 1           # -1..1 down
            keep = True
            if pattern == "pyramid":
                keep = abs(u) <= (r + 1) / rows + 1e-6
            elif pattern == "diamond":
                keep = abs(u) + abs(v) <= 1.05
            elif pattern == "heart":
                x, y = u * 1.25, -v * 1.25 + 0.25
                keep = (x * x + y * y - 1) ** 3 - x * x * y ** 3 <= 0
            elif pattern == "checker":
                keep = (r + c) % 2 == 0
            elif pattern == "stripes":
                keep = r % 2 == 0
            if keep:
                cells.append((r, c))
    return cells or [(r, c) for r in range(rows) for c in range(cols)]


def pitch_ladder(cfg, i: int, total: int) -> float:
    k = i / (total - 1) if total > 1 else 1.0
    return cfg.breaker_pitch_low + (cfg.breaker_pitch_high - cfg.breaker_pitch_low) * k


class BreakerSim:
    def __init__(self, cfg, seed: int | None = None):
        cfg.clamp()
        self.cfg = cfg
        s = cfg.seed if seed is None else seed
        self.rng = random.Random(s)
        self.fx = random.Random(s * 7919 + 17)
        self.space = pymunk.Space()
        self.space.gravity = (0, cfg.breaker_gravity)
        self.space.iterations = 12
        self.t = 0.0
        self.vt = 0.0
        self.particles: list[Particle] = []
        self.events: list[SoundEvent] = []
        self.banners: list[Banner] = []
        self.popups: list = []
        self.balls: list[BBall] = []
        self.bricks: list[Brick] = []
        self.broken = 0
        self.hits = 0
        self.finished_at: float | None = None
        self.final_pos = None
        self.shake = 0.0
        self.tension = False
        self._slow_until = -1.0
        self._slow_len = 1.0
        self._slow_factor = 1.0
        self._last_break_vt = 0.0
        self.constant_speed = True      # Breaker keeps the speed fixed; gravity modes turn this off
        self._to_remove: list[Brick] = []
        self._by_shape: dict = {}
        W, H = cfg.width, cfg.height
        m = cfg.breaker_arena_margin
        self.arena = (m, H * cfg.breaker_arena_top, W - m, H * cfg.breaker_arena_bottom)
        self.cx, self.cy = W / 2, (self.arena[1] + self.arena[3]) / 2
        self._build_walls()
        self._build_bricks()
        for i in range(self._start_balls()):
            self._add_ball()
        self.space.on_collision(1, 3, begin=self._on_brick)
        self.space.on_collision(1, 2, begin=self._on_wall)

    # ---------- setup ----------
    def _radius(self) -> float:
        return self.cfg.breaker_ball_radius

    def _start_balls(self) -> int:
        return self.cfg.breaker_balls

    def _build_walls(self) -> None:
        x0, y0, x1, y1 = self.arena
        body = self.space.static_body
        th = 20
        segs = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
        self.walls = []
        for a, b in segs:
            # push the wall line outwards by its radius so the ball bounces off the drawn edge
            s = pymunk.Segment(body, a, b, 0.5)
            s.elasticity, s.friction, s.collision_type = 1.0, 0.0, 2
            self.walls.append(s)
        self.space.add(*self.walls)
        self.wall_th = th

    def _build_bricks(self) -> None:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        gap = c.breaker_brick_gap
        cols, rows = c.breaker_cols, c.breaker_rows
        bw = (x1 - x0 - gap * (cols + 1)) / cols
        bh = c.breaker_brick_height
        top = y0 + (y1 - y0) * c.breaker_wall_rows_y
        for r, col in pattern_cells(c.breaker_pattern, rows, cols):
            # top rows are the toughest
            hp = max(1, c.breaker_hp - int(r * c.breaker_hp / max(1, rows)))
            x = x0 + gap + bw / 2 + col * (bw + gap)
            y = top + gap + bh / 2 + r * (bh + gap)
            b = Brick(r, col, x, y, bw, bh, hp, hp)
            verts = [(x - bw / 2, y - bh / 2), (x + bw / 2, y - bh / 2), (x + bw / 2, y + bh / 2), (x - bw / 2, y + bh / 2)]
            shape = pymunk.Poly(self.space.static_body, verts, radius=1.0)
            shape.elasticity, shape.friction, shape.collision_type = 1.0, 0.0, 3
            self.space.add(shape)
            b.shape = shape
            self._by_shape[id(shape)] = b
            self.bricks.append(b)
        self.total = len(self.bricks)

    def _add_ball(self, pos=None) -> BBall:
        c = self.cfg
        r = self._radius()
        x0, y0, x1, y1 = self.arena
        body = pymunk.Body(1.0, pymunk.moment_for_circle(1.0, 0, r))
        if pos is None:
            pos = (self.rng.uniform(x0 + 3 * r, x1 - 3 * r), y1 - 4 * r)
        body.position = pos
        a = self.rng.uniform(math.radians(-150), math.radians(-30))    # upwards
        body.velocity = (math.cos(a) * c.breaker_speed, math.sin(a) * c.breaker_speed)
        shape = pymunk.Circle(body, r)
        shape.elasticity, shape.friction, shape.collision_type = 1.0, 0.0, 1
        self.space.add(body, shape)
        ball = BBall(shape, len(self.balls), self.vt, [])
        self.balls.append(ball)
        return ball

    # ---------- events ----------
    def _on_wall(self, arbiter, space, data) -> None:
        self.hits += 1

    def _on_brick(self, arbiter, space, data) -> None:
        brick = self._by_shape.get(id(arbiter.shapes[1]))
        if brick is None or brick.broken_vt is not None or brick in self._to_remove:
            return
        brick.hp -= 1
        brick.hit_vt = self.vt
        self.hits += 1
        if brick.hp <= 0:
            self._to_remove.append(brick)
        else:   # a crack: quieter note at the current pitch
            self.events.append(SoundEvent(self.t, min(brick.row, self.cfg.tiers - 1), "drop", vt=self.vt,
                                          pitch=pitch_ladder(self.cfg, self.broken, self.total) + 4))
            self._burst(brick, 4)

    def _break(self, brick: Brick) -> None:
        c = self.cfg
        self.space.remove(brick.shape)
        brick.broken_vt = self.vt
        i = self.broken
        self.broken += 1
        self._last_break_vt = self.vt
        self._burst(brick, 14)
        last = self.broken >= self.total
        if last:
            self.finished_at = self.vt
            self.final_pos = (brick.x, brick.y)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.2)
            self._burst(brick, 60)
        else:
            self.events.append(SoundEvent(self.t, min(brick.row, c.tiers - 1), "merge", vt=self.vt,
                                          pitch=pitch_ladder(c, i, self.total)))
            if c.shake_strength > 0 and brick.max_hp > 1:
                self.shake = max(self.shake, c.shake_strength * 0.6)
            self._after_break(brick)

    def _after_break(self, brick: Brick) -> None:
        """Extra ball every N bricks (Breaker); other modes override."""
        c = self.cfg
        if c.breaker_split_every and self.broken % c.breaker_split_every == 0 \
                and len(self.balls) < c.breaker_max_balls:
            src = self.balls[self.rng.randrange(len(self.balls))].shape.body.position
            nb = self._add_ball((src.x, src.y))
            if c.tier_banners and nb.index < c.tiers and nb.index >= 1:
                self.banners = [Banner(min(nb.index, c.tiers - 1), self.vt)]

    def _burst(self, brick: Brick, n: int) -> None:
        c = self.cfg
        n = int(round(n * c.particle_amount))
        ncol = max(1, len(c.particle_colors))
        for _ in range(n):
            a = self.fx.uniform(0, 2 * math.pi)
            s = self.fx.uniform(120, 520) * c.particle_speed
            life = self.fx.uniform(0.35, 0.8) * (1.4 if c.particle_style == "confetti" else 1.0)
            x = brick.x + self.fx.uniform(-brick.w / 2, brick.w / 2)
            y = brick.y + self.fx.uniform(-brick.h / 2, brick.h / 2)
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s, life,
                                           (brick.row, self.fx.randrange(ncol)), self.fx.uniform(3, 8),
                                           self.fx.uniform(0, 360), self.fx.uniform(-720, 720), life))

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

    def alive_bricks(self) -> list[Brick]:
        return [b for b in self.bricks if b.broken_vt is None]

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        real_dt = dt
        c = self.cfg
        dt *= c.speed * self.time_scale()
        sub = 4
        for _ in range(sub):
            self.space.step(dt / sub)
            for b in self._to_remove:
                if b.broken_vt is None:
                    self._break(b)
            self._to_remove.clear()
        alive = self.alive_bricks() if self.finished_at is None else []
        steer = self.finished_at is None and self.vt - self._last_break_vt > 1.5 and alive
        x0, y0, x1, y1 = self.arena
        for ball in self.balls:
            body = ball.shape.body
            v = body.velocity
            sp = v.length or 1.0
            vx, vy = v.x / sp, v.y / sp
            if self.constant_speed:
                if steer:
                    # nobody hit anything for a while: bend gently toward the nearest brick
                    p = body.position
                    tgt = min(alive, key=lambda b: (b.x - p.x) ** 2 + (b.y - p.y) ** 2)
                    dx, dy = tgt.x - p.x, tgt.y - p.y
                    dl = math.hypot(dx, dy) or 1.0
                    k = min(1.0, 1.6 * dt)
                    vx, vy = vx + (dx / dl - vx) * k, vy + (dy / dl - vy) * k
                # never too flat (endless side-to-side) or too steep (endless up-down)
                if abs(vy) < 0.18:
                    vy = math.copysign(0.18, vy or -1)
                if abs(vx) < 0.08:
                    vx = math.copysign(0.08, vx or (1 if self.rng.random() < 0.5 else -1))
                n = math.hypot(vx, vy) or 1.0
                body.velocity = (vx / n * c.breaker_speed, vy / n * c.breaker_speed)
            # safety net: a ball squeezed out of the arena comes back in
            r = ball.shape.radius
            px_, py_ = body.position
            if not (x0 - r < px_ < x1 + r and y0 - r < py_ < y1 + r):
                body.position = (min(max(px_, x0 + r + 2), x1 - r - 2), min(max(py_, y0 + r + 2), y1 - r - 2))
            ball.trail.append((body.position.x, body.position.y))
            if len(ball.trail) > max(0, int(c.breaker_trail)):
                ball.trail = ball.trail[-max(0, int(c.breaker_trail)):] if c.breaker_trail > 0 else []
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
        left = self.total - self.broken
        self.tension = c.near_miss and self.finished_at is None and 0 < left <= max(1, self.total // 20)
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
    def best_tier(self) -> int:
        return min(len(self.balls) - 1, self.cfg.tiers - 1)

    @property
    def merges(self) -> int:
        return self.broken

    @property
    def best_combo(self) -> int:
        return 0

    def stats(self) -> dict:
        return {"bricks": self.total, "broken": self.broken, "balls": len(self.balls)}
