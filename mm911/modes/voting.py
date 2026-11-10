"""🗳️ Voting: a few pictures drift around the arena, each with a live vote counter climbing above it. At the end of every
round the picture with the fewest votes is voted out (each a higher note) until one is left: WINNER!
Built on the Chain Reaction arena (shares its renderer, sounds, particles, slow-mo and export)."""
from __future__ import annotations

from .chain import ChainSim
from .merge import SoundEvent


class VotingSim(ChainSim):
    def __init__(self, cfg, seed: int | None = None):
        super().__init__(cfg, seed)
        self.counter_text = cfg.voting_counter_text
        self.final_text = cfg.voting_final_text
        self.total = max(2, int(cfg.voting_balls))
        self.votes: dict[int, float] = {}
        self.rate: dict[int, float] = {}
        for i, b in enumerate(self.balls):
            b.index = i % max(1, cfg.tiers)
            b.vid = i
            self.votes[i] = 0.0
            self.rate[i] = self.rng.uniform(0.6, 1.4)
        self._round = 0
        self._round_start = 0.8
        self._gap = max(0.6, (cfg.voting_seconds - 0.8) / max(1, self.total - 1))
        self._next = self._round_start + self._gap

    def _radius(self) -> float:
        return self.cfg.voting_ball_radius

    def _start_balls(self) -> int:
        return self.cfg.voting_balls

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.voting_balls))

    def _add_ball(self, pos=None):
        b = super()._add_ball(pos)
        a = b.shape.body.velocity
        n = a.length or 1.0
        sp = self.cfg.voting_speed
        b.shape.body.velocity = (a.x / n * sp, a.y / n * sp)
        return b

    def count(self, ball) -> int:
        return int(self.votes.get(getattr(ball, "vid", -1), 0))

    def _chain(self) -> None:
        c = self.cfg
        if self.finished_at is not None or not self.balls:
            return
        for b in self.balls:                                   # votes keep rolling in
            v = b.vid
            self.votes[v] += self.rate[v] * self._dt_vote * (1 + 0.5 * self.rng.random())
        if self.vt < self._next or len(self.balls) <= 1:
            return
        self._next = self.vt + self._gap
        out = min(self.balls, key=lambda q: (self.votes[q.vid], q.vid))   # fewest votes goes home
        self._pop(out)
        for b in self.balls:                                   # a new round starts from zero
            self.votes[b.vid] = 0.0
            self.rate[b.vid] = self.rng.uniform(0.6, 1.4)
        if len(self.balls) == 1:
            b = self.balls[0]
            p = b.shape.body.position
            self.pops = self.total
            self.broken = self.total - 1
            self.finished_at = self.vt
            self.final_pos = (p.x, p.y)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)

    def step(self, dt: float) -> None:
        sp = self.cfg.voting_speed
        self._dt_vote = dt * 9.0                               # votes per second, scaled
        if self.finished_at is None:
            self._chain()
        for b in self.balls:
            v = b.shape.body.velocity
            n = v.length or 1.0
            b.shape.body.velocity = (v.x / n * sp, v.y / n * sp)
        super(ChainSim, self).step(dt)

    def stats(self) -> dict:
        return {"left": len(self.balls), "target": self.total}
