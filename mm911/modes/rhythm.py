"""🎵 Rhythmic: a ball hops over a row of keys and lands on a new key exactly when each note of a song
plays (a MIDI file of your own, or one of the built-in melodies). Low notes are on the left, high notes
on the right. The ball evolves through your Tiers pictures as the song goes on; the last note ends the
video with SONG COMPLETE!

No physics engine: the hop between two notes is an exact parabola that lands on the next note's key at
its time, so the picture and the sound can never drift apart. Every seed wins (the song always ends).
Settings: rhythm_* (see config.py); particles / shake / sounds are shared with the other modes."""
from __future__ import annotations

import math
import random

from .. import midi
from .merge import Particle, SoundEvent


class RhythmSim:
    def __init__(self, cfg, seed: int | None = None):
        cfg.clamp()
        self.cfg = cfg
        s = cfg.seed if seed is None else seed
        self.fx = random.Random(s * 7919 + 17)
        W, H = cfg.width, cfg.height
        self.cx, self.cy = W / 2, H / 2
        self.floor = H * cfg.rhythm_floor_y
        self.ball_r = float(cfg.rhythm_ball_radius)
        self.lanes = max(2, int(cfg.rhythm_lanes))
        margin = W * 0.06
        self.lane_w = (W - 2 * margin) / self.lanes
        self.lane_x = [margin + (i + 0.5) * self.lane_w for i in range(self.lanes)]
        # ---- the song: notes -> lanes, times fitted into the video length
        notes = midi.load_song(cfg.rhythm_midi, cfg.rhythm_song)
        tempo = max(0.25, cfg.rhythm_tempo)
        budget = (180.0 if cfg.until_finished else cfg.max_seconds) - cfg.rhythm_lead - 1.5
        budget = max(2.0, budget)
        span = max(0.1, notes[-1].t / tempo)
        if span > budget:                       # too long: speed up (at most 1.8x extra), cut what still does not fit
            tempo = min(tempo * 1.8, tempo * span / budget)
        times = [cfg.rhythm_lead + n.t / tempo for n in notes]
        keep = [i for i, t in enumerate(times) if t <= cfg.rhythm_lead + budget + 1e-6]
        if len(keep) < 2:
            keep = list(range(min(2, len(notes))))
        self.notes = [notes[i] for i in keep]
        self.times = [times[i] for i in keep]
        self.pitches = [n.pitch for n in self.notes]
        lo, hi = min(self.pitches), max(self.pitches)
        self.pmin = lo
        self.note_lane = [int(round((p - lo) / (hi - lo) * (self.lanes - 1))) if hi > lo else self.lanes // 2
                          for p in self.pitches]
        self.total = len(self.notes)
        self.end_t = self.times[-1]
        # ---- state
        self.t = 0.0
        self.vt = 0.0
        self.played = 0
        self.pad_hit: dict[int, float] = {}       # lane -> video time of its last note
        self.ripples: list[tuple[float, int]] = []   # (vt, lane)
        self.particles: list[Particle] = []
        self.events: list[SoundEvent] = []
        self.banners: list = []
        self.popups: list = []
        self.trail: list[tuple[float, float]] = []
        self.finished_at: float | None = None
        self.final_pos = None
        self.shake = 0.0
        self.tension = False
        self.pos = (self.lane_x[self.note_lane[0]], self.floor - self.ball_r)
        self._update_pos(0.0)

    # ---------- the hop ----------
    def _apex(self, dt: float) -> float:
        top = self.floor - self.cfg.height * 0.3 - self.ball_r
        return max(self.ball_r * 0.7, min(top, dt * 520.0 * self.cfg.rhythm_hop))

    def _update_pos(self, t: float) -> None:
        times, lx = self.times, self.lane_x
        ground = self.floor - self.ball_r
        k = self.played                      # notes already played; the ball is flying to note k
        if t < times[0]:                     # intro: it drops onto the first key
            s = max(0.0, t / max(1e-3, times[0]))
            self.pos = (lx[self.note_lane[0]], ground - self.cfg.height * 0.28 * (1 - s * s))
            return
        if k >= self.total:                  # after the song: little happy hops in place
            e = t - times[-1]
            h = 70.0 * math.exp(-e * 1.6)
            self.pos = (lx[self.note_lane[-1]], ground - abs(math.sin(e * 7.5)) * h)
            return
        t0, t1 = times[k - 1], times[k]
        s = min(1.0, max(0.0, (t - t0) / max(1e-3, t1 - t0)))
        x0, x1 = lx[self.note_lane[k - 1]], lx[self.note_lane[k]]
        self.pos = (x0 + (x1 - x0) * s, ground - 4 * self._apex(t1 - t0) * s * (1 - s))

    @property
    def angle(self) -> float:
        """Rolling angle of the ball picture: it turns as it travels."""
        return self.pos[0] * 0.012

    # ---------- events ----------
    def _hit(self, k: int) -> None:
        c = self.cfg
        lane = self.note_lane[k]
        self.played = k + 1
        self.pad_hit[lane] = self.vt
        self.ripples = (self.ripples + [(self.vt, lane)])[-12:]
        pitch = max(-24.0, min(24.0, self.pitches[k] - self.pmin + c.rhythm_pitch_shift))
        last = k == self.total - 1
        tier = self.best_tier
        self.events.append(SoundEvent(self.t, tier, "merge", vt=self.vt, pitch=pitch))
        if c.shake_strength > 0:
            self.shake = max(self.shake, c.shake_strength * (1.2 if last else 0.25))
        n = int(round((22 if last else 7) * c.particle_amount))
        ncol = max(1, len(c.particle_colors))
        x, y = self.lane_x[lane], self.floor
        for _ in range(n):
            a = -math.pi / 2 + self.fx.uniform(-1.1, 1.1)
            sp = self.fx.uniform(160, 520 if last else 380) * c.particle_speed
            life = self.fx.uniform(0.35, 0.8)
            self.particles.append(Particle(x, y, math.cos(a) * sp, math.sin(a) * sp, life,
                                           (lane, self.fx.randrange(ncol)), self.fx.uniform(3, 7),
                                           self.fx.uniform(0, 360), self.fx.uniform(-540, 540), life))
        if last:
            self.finished_at = self.vt
            self.final_pos = self.pos
            self.events.append(SoundEvent(self.t, tier, "final", vt=self.vt))

    @property
    def best_tier(self) -> int:
        if not self.cfg.rhythm_evolve or self.total <= 1:
            return 0
        return min(self.cfg.tiers - 1, int(self.played / self.total * self.cfg.tiers))

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        c = self.cfg
        real_dt = dt
        dt *= c.speed
        self.t += dt
        self.vt += real_dt
        t = self.t
        # notes whose time has come (a long step may cross several)
        while self.played < self.total and self.times[self.played] <= t + 1e-9:
            self._hit(self.played)
        self._update_pos(t)
        self.trail.append(self.pos)
        n = max(0, int(c.rhythm_trail))
        if len(self.trail) > n:
            self.trail = self.trail[-n:] if n else []
        for pt in self.particles:
            pt.x += pt.vx * dt
            pt.y += pt.vy * dt
            pt.vy += c.particle_gravity * dt * (0.35 if c.particle_style == "confetti" else 1.0)
            pt.vx *= 0.97
            pt.rot += pt.spin * dt
            pt.life -= dt
        self.particles = [pt for pt in self.particles if pt.life > 0]
        self.shake *= math.exp(-real_dt * 9)
        if self.shake < 0.3:
            self.shake = 0.0

    def shake_offset(self) -> tuple[float, float]:
        if not self.shake:
            return 0.0, 0.0
        return self.shake * math.sin(self.vt * 93.0), self.shake * math.cos(self.vt * 71.0)

    def time_scale(self) -> float:
        return 1.0

    @property
    def done(self) -> bool:
        if self.finished_at is not None:
            return self.vt >= self.finished_at + self.cfg.end_hold_seconds + 0.6
        return self.t > self.end_t + 10

    @property
    def won(self) -> bool:
        return self.finished_at is not None

    @property
    def merges(self) -> int:
        return self.played

    @property
    def best_combo(self) -> int:
        return 0

    def stats(self) -> dict:
        return {"notes": self.played, "total": self.total, "song_seconds": round(self.end_t, 1)}
