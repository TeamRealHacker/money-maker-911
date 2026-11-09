"""⚔️ Weapon Ball Battle: Flag Battle where every fighter swings a weapon (sword, spear or mace) around itself.
Only the weapon hurts: touching bodies just bounce. The last fighter standing wins.

Built on Flag Battle (same fighters, health bars, sounds, ending)."""
from __future__ import annotations

import math

from .battle import BattleSim
from .merge import SoundEvent
from .breaker import pitch_ladder

# length (x radius), spin (rad/s), damage factor, width (x radius)
WEAPONS = {"sword": (2.3, 4.6, 1.0, 0.30), "spear": (3.0, 3.0, 0.9, 0.16), "mace": (1.9, 6.5, 1.3, 0.22)}


def seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy or 1.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class WeaponSim(BattleSim):
    def _add_ball(self, pos=None, from_vel=None):
        ball = super()._add_ball(pos)
        c = self.cfg
        kind = c.weapon_type
        if kind == "mixed":
            kind = ("sword", "spear", "mace")[ball.index % 3]
        ball.weapon = kind
        ball.angle = self.rng.uniform(0, 2 * math.pi)
        ball.spin = self.rng.choice((-1, 1)) * WEAPONS[kind][1] * c.weapon_spin * self.rng.uniform(0.85, 1.15)
        return ball

    def weapon_len(self, ball) -> float:
        return WEAPONS[ball.weapon][0] * self.cfg.weapon_length * self._radius()

    def _on_fight(self, arbiter, space, data) -> None:
        """Bodies only bounce; the weapons do the damage."""
        self.hits += 1

    def step(self, dt: float) -> None:
        super().step(dt)
        if self.winner is not None and self.finished_at is not None:
            for b in self.balls:
                b.angle += b.spin * dt * 0.4
            return
        c = self.cfg
        gdt = dt * c.speed * self.time_scale()
        r = self._radius()
        for a in self.balls:
            a.angle += a.spin * gdt
        for a in self.balls:
            if a in self._kills:
                continue
            L, _, dmg, wid = WEAPONS[a.weapon]
            L *= c.weapon_length * r
            pa = a.shape.body.position
            tx, ty = pa.x + math.cos(a.angle) * L, pa.y + math.sin(a.angle) * L
            hx, hy = pa.x + math.cos(a.angle) * r * 0.7, pa.y + math.sin(a.angle) * r * 0.7
            for b in self.balls:
                if b is a or b in self._kills:
                    continue
                pb = b.shape.body.position
                if seg_dist(pb.x, pb.y, hx, hy, tx, ty) > r + wid * r * 0.5:
                    continue
                key = (id(a), id(b))
                if self.vt - self._cool.get(key, -9.0) < 0.45:
                    continue
                self._cool[key] = self.vt
                b.hp -= c.battle_damage * self.rage() * dmg * a.power * self.fx.uniform(0.85, 1.15)
                b.hit_vt = self.vt
                self._last_fight_vt = self.vt
                self.hits += 1
                self._sparks(pb.x, pb.y, 6, b.index)
                self.events.append(SoundEvent(self.t, min(c.tiers - 1, a.index), "drop", vt=self.vt,
                                              pitch=pitch_ladder(c, self.eliminated, self.total) - 2 + self.fx.uniform(-1.5, 1.5)))
                if c.shake_strength > 0:
                    self.shake = max(self.shake, c.shake_strength * 0.4)
                if b.hp <= 0 and b not in self._kills:
                    self._kills.append(b)

    def __init__(self, cfg, seed: int | None = None):
        self._cool: dict = {}
        super().__init__(cfg, seed)
