"""♾️ Infinite Zoom Physics Loop (the "Satisfying Meme Physics Simulation"):

a raw PNG meme cutout bounces down glowing neon stairs in a pitch-black star space while the
camera zooms in forever. Every step the object lands on is a little bigger, so the loop feels
endless, and every bounce plays a sound that is slower and deeper in pitch than the last.

How the endless-zoom illusion works: each "step" is the same choreography (two hops along the
platform, then a long fall onto the next platform). The camera zooms by cfg.zoom_growth during
every step and the next platform is drawn 1/zoom_growth smaller, so the frame at the end of a
step is identical to the frame at its start — the zoom never has to stop. Motion is kinematic
(scripted arcs) rather than dynamic physics: the landing point is fixed by the loop math, so the
seam between steps is pixel-perfect and masked by the impact (shake + spark burst + deep sound).

Built on the shared config / export / sound pipeline (settings prefixed zoom_*)."""
from __future__ import annotations

import math
import random

from .merge import SoundEvent


class ZoomSim:
    def __init__(self, cfg, seed: int | None = None):
        cfg.clamp()
        self.cfg = cfg
        s = cfg.seed if seed is None else seed
        self.rng = random.Random(s)
        self.fx = random.Random(s * 6151 + 11)
        self.t = 0.0            # simulation time (scaled by speed)
        self.vt = 0.0           # video time (real seconds, what the audio track uses)
        self.events: list[SoundEvent] = []
        self.banners: list = []
        self.popups: list = []
        self.particles: list = []
        self.finished_at: float | None = None
        self.final_pos = None
        self.shake = 0.0
        self.tension = False
        self._slow_until = -1.0
        self._slow_len = 1.0
        self._slow_factor = 1.0
        self.counter_text = cfg.zoom_counter_text
        self.final_text = cfg.zoom_final_text
        # loop geometry: platform width in "phase world" units; the next platform is a scaled copy
        self.W = cfg.width * cfg.zoom_platform_w
        self.r = self.W * cfg.zoom_ball_size
        self.g = cfg.zoom_growth
        self.C1 = (0.26 * self.W, 0.52 * self.W)   # next platform centre, in the current frame
        self.A = (-0.30 * self.W, -self.r)          # loop start: ball on the current platform
        self.total = int(cfg.zoom_target)
        self.broken = 0                             # steps completed
        self.idx = 0                                # current step index
        self.T = self._step_time(0)
        self.phase_t = 0.0
        self.pos = (self.A[0], self.A[1])
        self.angle = 0.0
        self._jitter = self._new_jitter()
        self._fired: set[int] = set()               # which bounces of this step already sounded
        self.sparks: list[list] = []                # screen-space dust: x, y, vx, vy, life, max, col
        self._last_land_vt = -9.0

    # ---------- loop geometry ----------
    def _step_time(self, k: int) -> float:
        return self.cfg.zoom_step_time * (self.cfg.zoom_slow ** k)

    def _new_jitter(self) -> tuple[float, float, float]:
        return (self.fx.uniform(0.85, 1.15), self.fx.uniform(0.85, 1.15), self.fx.uniform(0.85, 1.15))

    def _landing(self) -> tuple[float, float]:
        """Where the ball lands, in the current frame: the loop start expressed on the next platform."""
        return (self.C1[0] + self.A[0] / self.g, self.C1[1] + self.A[1] / self.g)

    def _pos_at(self, u: float) -> tuple[float, float]:
        """Ball position inside the current step (u = 0..1). Two hops, then the long fall."""
        W, T = self.W, self.T
        j1, j2, j3 = self._jitter
        r = self.r
        A, B1, B2, L = self.A, (-0.02 * W, -r), (0.22 * W, -r), self._landing()
        t1, t2 = 0.24, 0.44                                  # hop boundaries (fraction of T)
        if u < t1:                                           # hop 1
            return self._arc(A, B1, u / t1, 0.10 * W * j1)
        if u < t2:                                           # hop 2
            return self._arc(B1, B2, (u - t1) / (t2 - t1), 0.11 * W * j2)
        return self._arc(B2, L, (u - t2) / (1 - t2), 0.14 * W * j3)

    @staticmethod
    def _arc(p0: tuple[float, float], p1: tuple[float, float], u: float, h: float) -> tuple[float, float]:
        u = max(0.0, min(1.0, u))
        x = p0[0] + (p1[0] - p0[0]) * u
        y = p0[1] + (p1[1] - p0[1]) * u - 4.0 * h * u * (1 - u)
        return (x, y)

    # ---------- camera (the renderer uses the same math) ----------
    def phase_progress(self) -> float:
        return max(0.0, min(1.0, self.phase_t / max(1e-6, self.T)))

    def camera(self) -> tuple[float, float, float]:
        """(focus_x, focus_y, zoom) for the current moment. zoom = growth^progress (exponential, so
        the picture grows at a constant rate); the focus glides smoothly to the next platform."""
        e = self.phase_progress()
        z = self.g ** e
        f = e * e * (3 - 2 * e)                             # smoothstep
        C1 = self.C1
        return (C1[0] * f, C1[1] * f, z)

    def pitch_now(self) -> float:
        return self.cfg.zoom_pitch_start - self.idx * self.cfg.zoom_pitch_drop

    def tier_now(self) -> int:
        return min(self.cfg.tiers - 1, self.broken * self.cfg.tiers // max(1, self.total))

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        real_dt = dt
        c = self.cfg
        dt *= c.speed * self.time_scale()
        if self.finished_at is None:
            self.phase_t += dt
            self.pos = self._pos_at(self.phase_progress())
            # collision-synced sounds: two hops, then the landing on the next step (the final
            # landing plays only the big "final" sound, so it never doubles up)
            last = self.broken + 1 >= self.total
            marks = [(0.24, "drop"), (0.44, "drop")] if last else [(0.24, "drop"), (0.44, "drop"), (1.0, "merge")]
            for i, (at, kind) in enumerate(marks):
                if i not in self._fired and self.phase_t >= self.T * at:
                    self._fired.add(i)
                    tier = self.tier_now()
                    if kind == "merge":
                        self.events.append(SoundEvent(self.t, tier, "merge", vt=self.vt,
                                                      pitch=self.pitch_now()))
                    else:
                        self.events.append(SoundEvent(self.t, tier, "drop", vt=self.vt,
                                                      pitch=self.pitch_now() + c.zoom_bounce_pitch))
            # the landing itself
            if self.phase_t >= self.T:
                self._land()
        # tumble
        self.angle += c.zoom_ball_spin * 360.0 * dt
        # spark dust (screen space, spawned by _land)
        for sp in self.sparks:
            sp[0] += sp[2] * real_dt
            sp[1] += sp[3] * real_dt
            sp[3] += 260.0 * real_dt
            sp[2] *= 0.90
            sp[4] -= real_dt
        self.sparks = [sp for sp in self.sparks if sp[4] > 0]
        self.shake *= math.exp(-real_dt * 9)
        if self.shake < 0.3:
            self.shake = 0.0
        self.tension = (self.finished_at is None and self.total - self.broken <= 2
                        and c.near_miss)
        self.t += dt
        self.vt += real_dt

    def _land(self) -> None:
        c = self.cfg
        self.broken += 1
        self._last_land_vt = self.vt
        if self.broken >= self.total:
            self.finished_at = self.vt
            self.final_pos = self._landing()
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.0 * c.zoom_shake)
            self._burst(28)
            return
        leftover = max(0.0, self.phase_t - self.T)     # frame overshoot carries into the next step
        self.idx += 1
        self.T = self._step_time(self.idx)
        self.phase_t = max(0.0, min(leftover, self.T * 0.5))
        self._jitter = self._new_jitter()
        self._fired.clear()
        self.pos = self._pos_at(self.phase_progress())
        if c.shake_strength > 0:
            self.shake = max(self.shake, c.shake_strength * 0.9 * c.zoom_shake)
        self._burst(10)

    def _burst(self, n: int) -> None:
        """Dust burst where the ball just landed, in screen space (Cx, Cy + A) — the seam point."""
        c = self.cfg
        n = int(round(n * c.particle_amount))
        if n <= 0:
            return
        Cx, Cy = self.cfg.width / 2, self.cfg.height * 0.42
        x = Cx + self.A[0]
        y = Cy + self.A[1]
        ncol = max(1, len(c.particle_colors))
        col = (self.tier_now(), self.fx.randrange(ncol))
        for _ in range(n):
            a = self.fx.uniform(-math.pi, 0.0)
            sp = self.fx.uniform(120, 520) * c.particle_speed
            life = self.fx.uniform(0.3, 0.7)
            self.sparks.append([x, y, math.cos(a) * sp, math.sin(a) * sp, life, life, col,
                                self.fx.uniform(2, 6)])

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
        return self.tier_now()

    @property
    def merges(self) -> int:
        return self.broken

    @property
    def best_combo(self) -> int:
        return 0

    def stats(self) -> dict:
        return {"steps": self.broken, "target": self.total}

    def thumb_ready(self):
        return self.finished_at is not None and self.vt >= self.finished_at + 0.45
