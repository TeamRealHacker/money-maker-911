"""⚔️ Flag Battle: every picture (flag, face, meme...) is a fighter bouncing around the arena. When two touch,
the weaker hitter loses health; at zero health a fighter pops out with a note higher than the last. The last one
standing grows into the middle and wins.

Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export). Fighter i wears the
i-th Tiers picture / emoji, so any photos work; the number of fighters is `battle_fighters` (0 = one per form)."""
from __future__ import annotations

import math

import pymunk

from .breaker import BreakerSim, BBall, pitch_ladder
from .merge import SoundEvent, Particle


class BattleSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self._made = 0
        self._by_ball: dict = {}
        self._kills: list = []
        self.eliminated = 0
        self.winner: BBall | None = None
        self._last_fight_vt = 0.0
        super().__init__(cfg, seed)
        self.counter_text = cfg.battle_counter_text
        self.final_text = cfg.battle_final_text
        self.space.on_collision(1, 1, begin=self._on_fight)
        self._last_break_vt = self.vt

    # ---------- setup ----------
    def _radius(self) -> float:
        return self.cfg.battle_radius

    def _start_balls(self) -> int:
        return self.cfg.battle_fighters or self.cfg.tiers

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(1, (self.cfg.battle_fighters or self.cfg.tiers) - 1)   # eliminations needed

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        r = self._radius()
        if pos is None:
            for _ in range(60):
                p = (self.rng.uniform(x0 + 2 * r, x1 - 2 * r), self.rng.uniform(y0 + 2 * r, y1 - 2 * r))
                if all((p[0] - b.shape.body.position.x) ** 2 + (p[1] - b.shape.body.position.y) ** 2 > (2.6 * r) ** 2
                       for b in self.balls):
                    break
            pos = p
        ball = super()._add_ball(pos)
        ball.index = self._made
        self._made += 1
        a = self.rng.uniform(0, 2 * math.pi)
        ball.shape.body.velocity = (math.cos(a) * c.breaker_speed, math.sin(a) * c.breaker_speed)
        ball.shape.elasticity = 1.0
        ball.hp = float(c.battle_hp)
        ball.max_hp = float(c.battle_hp)
        ball.power = self.rng.uniform(0.8, 1.25)
        ball.hit_vt = -9.0
        ball.scale_k = 1.0
        self._by_ball[id(ball.shape)] = ball
        return ball

    def rage(self) -> float:
        """Sudden death: damage ramps up after half of the video so a fight can't drag on."""
        return 1.0 + max(0.0, self.vt - 0.5 * self.cfg.max_seconds) / 12.0

    # ---------- fights ----------
    def _on_fight(self, arbiter, space, data) -> None:
        a = self._by_ball.get(id(arbiter.shapes[0]))
        b = self._by_ball.get(id(arbiter.shapes[1]))
        if a is None or b is None or self.finished_at is not None or a in self._kills or b in self._kills:
            return
        c = self.cfg
        self.hits += 1
        self._last_fight_vt = self.vt
        d = c.battle_damage * self.rage()
        a.hp -= d * b.power * self.fx.uniform(0.85, 1.15)
        b.hp -= d * a.power * self.fx.uniform(0.85, 1.15)
        a.hit_vt = b.hit_vt = self.vt
        if a.hp <= 0 and b.hp <= 0:                  # never two at once: the healthier one hangs on
            (a if a.hp >= b.hp else b).hp = 1.0
        for ball in (a, b):
            if ball.hp <= 0:
                self._kills.append(ball)
        mid = arbiter.contact_point_set.points[0].point_a if arbiter.contact_point_set.points else a.shape.body.position
        self._sparks(mid.x, mid.y, 5, a.index)
        self.events.append(SoundEvent(self.t, min(c.tiers - 1, a.index), "drop", vt=self.vt,
                                      pitch=pitch_ladder(c, self.eliminated, self.total) - 2 + self.fx.uniform(-1.5, 1.5)))
        if c.shake_strength > 0:
            self.shake = max(self.shake, c.shake_strength * 0.35)

    def _sparks(self, x: float, y: float, n: int, tier: int) -> None:
        c = self.cfg
        for _ in range(int(round(n * c.particle_amount))):
            a = self.fx.uniform(0, 2 * math.pi)
            s = self.fx.uniform(120, 420) * c.particle_speed
            life = self.fx.uniform(0.25, 0.55)
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s, life, (tier, self.fx.randrange(max(1, len(c.particle_colors)))),
                                           self.fx.uniform(3, 6), self.fx.uniform(0, 360), self.fx.uniform(-540, 540), life))

    def _eliminate(self, ball: BBall) -> None:
        c = self.cfg
        if ball not in self.balls:
            return
        p = ball.shape.body.position
        self.space.remove(ball.shape, ball.shape.body)
        self.balls.remove(ball)
        self._by_ball.pop(id(ball.shape), None)
        i = self.eliminated
        self.eliminated += 1
        self.broken = self.eliminated
        self._last_break_vt = self.vt
        self._sparks(p.x, p.y, 26, ball.index)
        if len(self.balls) <= 1:
            self._win()
        else:
            self.events.append(SoundEvent(self.t, min(c.tiers - 1, ball.index), "merge", vt=self.vt,
                                          pitch=pitch_ladder(c, i, self.total)))
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 0.9)

    def _win(self) -> None:
        c = self.cfg
        self.winner = self.balls[0]
        self.finished_at = self.vt
        self.constant_speed = False
        w = self.winner
        name = c.tier_value("tier_names", w.index % max(1, c.tiers))
        text = c.battle_final_text
        self.final_text = text.replace("{winner}", name) if name else ("WINNER!" if "{winner}" in text else text)
        p = w.shape.body.position
        self.final_pos = (p.x, p.y)
        self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
        if c.slowmo_final:
            self._slow(c.slowmo_factor, c.slowmo_seconds)
        if c.shake_strength > 0:
            self.shake = max(self.shake, c.shake_strength * 2.0)
        self._sparks(p.x, p.y, 50, w.index)

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        super().step(dt)
        for ball in list(self._kills):
            self._eliminate(ball)
        self._kills.clear()
        if self.winner is not None:
            w = self.winner
            age = self.vt - self.finished_at
            e = min(1.0, age / 0.8)
            w.scale_k = 1.0 + 0.9 * (1 - (1 - e) ** 3)
            tx, ty = self.cx, self.cy
            p = w.shape.body.position
            w.shape.body.velocity = ((tx - p.x) * 5.0, (ty - p.y) * 5.0)
            return
        # nobody has touched for a while: everyone bends toward their nearest opponent
        quiet = self.vt - self._last_fight_vt
        if len(self.balls) >= 2 and (quiet > 1.2 or len(self.balls) <= 3):
            k = min(1.0, (1.4 if quiet <= 1.2 else 2.6) * dt)
            for ball in self.balls:
                body = ball.shape.body
                p = body.position
                other = min((o for o in self.balls if o is not ball),
                            key=lambda o: (o.shape.body.position.x - p.x) ** 2 + (o.shape.body.position.y - p.y) ** 2)
                q = other.shape.body.position
                dx, dy = q.x - p.x, q.y - p.y
                dl = math.hypot(dx, dy) or 1.0
                v = body.velocity
                sp = v.length or 1.0
                vx, vy = v.x / sp + (dx / dl - v.x / sp) * k, v.y / sp + (dy / dl - v.y / sp) * k
                n = math.hypot(vx, vy) or 1.0
                body.velocity = (vx / n * sp, vy / n * sp)

    @property
    def best_tier(self) -> int:
        return (self.winner.index if self.winner else 0) % max(1, self.cfg.tiers)

    def stats(self) -> dict:
        return {"fighters": self.total + 1, "alive": len(self.balls)}
