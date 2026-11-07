"""🔊 Myinstants sound fetch: search, download once into a local cache, measure pitch, auto-assign to tiers.

Only the standard library + numpy. Downloaded clips live in the user's cache folder
(%APPDATA%\\MoneyMaker911\\sounds on Windows, ~/.mm911/sounds elsewhere), never in the repo.

    from mm911 import sounds
    hits = sounds.search("pop")                 # [SoundResult(name, mp3_url, page_url, slug)]
    path = sounds.download(hits[0])             # cached file path
    plan = sounds.auto_plan(["pop"], tiers=9)   # tier_sounds / tier_semitones / drop / final
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import math
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

LOG = logging.getLogger("mm911")

BASE = "https://www.myinstants.com"
SEARCH_URL = BASE + "/en/search/?name={q}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MoneyMaker911/0.3 (+https://github.com/TeamRealHacker/money-maker-911)"
TIMEOUT = 12
RETRIES = 3
SEARCH_TTL = 7 * 24 * 3600          # reuse a search for a week (polite + works offline afterwards)
MAX_MP3_BYTES = 3_000_000           # Shorts sounds are tiny; skip anything huge
MAX_CLIP_SECONDS = 1.6              # "satisfying" clips: prefer short ones for auto mode

# share('Name', 'https://www.myinstants.com/en/instant/slug/', '/media/sounds/file.mp3', 'slug')
_SHARE_RE = re.compile(r"share\('((?:[^'\\]|\\.)*)',\s*'([^']*)',\s*'([^']*\.mp3)',\s*'([^']*)'\)")
# fallback: play('/media/sounds/file.mp3', 'loader-1', 'slug') ... title="Play NAME sound"
_PLAY_RE = re.compile(r"play\('([^']*\.mp3)',\s*'[^']*',\s*'([^']*)'\)\"\s*title=\"Play (.*?) sound\"")
_OG_AUDIO_RE = re.compile(r'<meta property="og:audio" content="([^"]+\.mp3)"')
_MP3_RE = re.compile(r"(/media/sounds/[^\"' )]+\.mp3)")


@dataclass
class SoundResult:
    name: str
    mp3_url: str
    page_url: str = ""
    slug: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------- cache ----------------
def cache_dir() -> Path:
    env = os.environ.get("MM911_SOUND_CACHE")
    if env:
        d = Path(env)
    elif os.environ.get("APPDATA"):
        d = Path(os.environ["APPDATA"]) / "MoneyMaker911" / "sounds"
    else:
        d = Path.home() / ".mm911" / "sounds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return cache_dir() / "index.json"


def _load_index() -> dict:
    try:
        return json.loads(_index_path().read_text(encoding="utf-8"))
    except Exception:
        return {"files": {}, "analysis": {}}


def _save_index(idx: dict) -> None:
    tmp = _index_path().with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(idx, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _index_path())
    except OSError as e:
        LOG.warning("sound cache index not saved: %s", e)


# ---------------- http ----------------
def _get(url: str, binary: bool = False, limit: int | None = None) -> bytes | str:
    """GET with a polite User-Agent, timeout and simple exponential back-off retries."""
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = r.read(limit + 1 if limit else -1)
            if limit and len(data) > limit:
                raise ValueError(f"file larger than {limit} bytes")
            return data if binary else data.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 404, 410):
                break                       # no point retrying
        except Exception as e:  # URLError, timeout, reset...
            last = e
        time.sleep(0.6 * (2 ** attempt))
    raise ConnectionError(f"{url}: {last}")


def _js_unescape(s: str) -> str:
    """Names sit inside JS string literals: undo \\' and \\uXXXX escapes, then HTML entities."""
    s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)
    return html.unescape(s.replace("\\'", "'").replace("\\\\", "\\")).strip()


def parse_search(page: str) -> list[SoundResult]:
    """Pull (name, mp3) pairs out of a Myinstants search / list page."""
    out: list[SoundResult] = []
    seen = set()
    for name, page_url, mp3, slug in _SHARE_RE.findall(page):
        url = urllib.parse.urljoin(BASE, mp3)
        if url in seen:
            continue
        seen.add(url)
        out.append(SoundResult(_js_unescape(name), url, page_url, slug))
    if not out:  # markup changed: fall back to the play buttons
        for mp3, slug, name in _PLAY_RE.findall(page):
            url = urllib.parse.urljoin(BASE, mp3)
            if url not in seen:
                seen.add(url)
                out.append(SoundResult(html.unescape(name).strip(), url, f"{BASE}/en/instant/{slug}/", slug))
    return out


def search(query: str, pages: int = 1, use_cache: bool = True) -> list[SoundResult]:
    """Search Myinstants. Results are cached for a week; when offline the last cached search is used."""
    query = (query or "").strip()
    if not query:
        return []
    key = hashlib.sha1(f"{query.lower()}|{pages}".encode()).hexdigest()[:16]
    cfile = cache_dir() / "searches" / f"{key}.json"
    cached = None
    if cfile.exists():
        try:
            cached = json.loads(cfile.read_text(encoding="utf-8"))
        except Exception:
            cached = None
    if use_cache and cached and time.time() - cached.get("time", 0) < SEARCH_TTL:
        return [SoundResult(**r) for r in cached["results"]]
    results: list[SoundResult] = []
    try:
        for p in range(1, max(1, pages) + 1):
            url = SEARCH_URL.format(q=urllib.parse.quote_plus(query)) + (f"&page={p}" if p > 1 else "")
            got = parse_search(_get(url))  # type: ignore[arg-type]
            new = [r for r in got if r.mp3_url not in {x.mp3_url for x in results}]
            if not new:
                break
            results += new
    except ConnectionError as e:
        LOG.warning("myinstants search failed (%s), using cache if any", e)
        if cached:
            return [SoundResult(**r) for r in cached["results"]]
        raise
    try:
        cfile.parent.mkdir(parents=True, exist_ok=True)
        cfile.write_text(json.dumps({"query": query, "time": time.time(),
                                     "results": [r.to_dict() for r in results]}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return results


def resolve(url_or_page: str) -> str:
    """Turn a Myinstants instant page URL (or a direct mp3 URL) into the mp3 URL."""
    u = url_or_page.strip()
    if u.lower().split("?")[0].endswith(".mp3"):
        return urllib.parse.urljoin(BASE, u)
    page = _get(u)
    m = _OG_AUDIO_RE.search(page) or _MP3_RE.search(page)  # type: ignore[arg-type]
    if not m:
        raise ValueError("no mp3 on that page")
    return urllib.parse.urljoin(BASE, m.group(1))


def _safe_name(url: str) -> str:
    name = Path(urllib.parse.urlparse(url).path).name or "sound.mp3"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:80]
    if not name.lower().endswith(".mp3"):
        name += ".mp3"
    return f"{hashlib.sha1(url.encode()).hexdigest()[:8]}_{name}"


def download(item: SoundResult | str) -> str:
    """Download once into the cache and return the local path (cached file is reused forever)."""
    url = item.mp3_url if isinstance(item, SoundResult) else resolve(item)
    idx = _load_index()
    known = idx["files"].get(url)
    if known and Path(cache_dir() / known["file"]).exists():
        return str(cache_dir() / known["file"])
    data = _get(url, binary=True, limit=MAX_MP3_BYTES)
    if len(data) < 200:  # type: ignore[arg-type]
        raise ValueError("empty sound file")
    fname = _safe_name(url)
    path = cache_dir() / fname
    path.write_bytes(data)  # type: ignore[arg-type]
    idx["files"][url] = {"file": fname, "name": item.name if isinstance(item, SoundResult) else fname,
                         "time": int(time.time())}
    _save_index(idx)
    return str(path)


def cached_sounds() -> list[dict]:
    """Every sound already in the cache (for the app's 'Downloaded' list)."""
    idx = _load_index()
    out = []
    for url, v in idx["files"].items():
        p = cache_dir() / v["file"]
        if p.exists():
            out.append({"name": v.get("name", v["file"]), "mp3_url": url, "path": str(p)})
    return out


# ---------------- pitch analysis ----------------
def analyze(path: str) -> dict:
    """Measure a clip: duration, spectral centroid (brightness, Hz), fundamental (Hz, if tonal), loudness.

    Sorting uses the spectral centroid: it works for noisy pops as well as tonal dings, and a resample
    pitch shift of r semitones multiplies it by exactly 2**(r/12), so tier targets can be hit precisely.
    """
    p = str(path)
    idx = _load_index()
    try:
        st = os.stat(p)
        key = f"{Path(p).name}|{st.st_size}"
    except OSError:
        key = p
    if key in idx.get("analysis", {}):
        return idx["analysis"][key]
    from .audio import decode, SR
    x = decode(p, 6.0)
    res = {"duration": 0.0, "centroid": 0.0, "f0": 0.0, "tonal": False, "rms": 0.0, "pitch_hz": 0.0}
    if x.size:
        on = np.flatnonzero(np.abs(x) > 0.02 * (np.max(np.abs(x)) or 1))
        if on.size:
            x = x[on[0]: on[-1] + 1]
        res["duration"] = round(len(x) / SR, 3)
        res["rms"] = float(np.sqrt(np.mean(x ** 2)))
        # analyse the loudest 120 ms (the "body" of the hit)
        win = int(SR * 0.12)
        if len(x) > win:
            energy = np.convolve(x ** 2, np.ones(win // 4), "valid")
            c = int(np.argmax(energy))
            s = max(0, min(len(x) - win, c - win // 4))
            seg = x[s: s + win]
        else:
            seg = np.pad(x, (0, max(0, win - len(x))))
        seg = seg * np.hanning(len(seg))
        spec = np.abs(np.fft.rfft(seg, n=8192))
        freqs = np.fft.rfftfreq(8192, 1 / SR)
        band = (freqs > 40) & (freqs < 12000)
        if spec[band].sum() > 0:
            res["centroid"] = float((freqs[band] * spec[band]).sum() / spec[band].sum())
        # fundamental via autocorrelation (60 Hz .. 2 kHz)
        ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
        if ac[0] > 0:
            lo, hi = int(SR / 2000), int(SR / 60)
            lag = lo + int(np.argmax(ac[lo:hi]))
            clarity = float(ac[lag] / ac[0])
            res["f0"] = round(SR / lag, 1)
            res["tonal"] = clarity > 0.55
        res["pitch_hz"] = round(res["centroid"], 1)
    idx.setdefault("analysis", {})[key] = res
    _save_index(idx)
    return res


def semitones(hz: float) -> float:
    return 12 * math.log2(max(hz, 1.0) / 440.0)


def tier_pitches(measured_hz: list[float], tiers: int, step: float = 1.6, clamp: float = 12.0) -> list[float]:
    """Semitone shift per tier so tier 1 is lowest and the final tier highest.

    measured_hz[t] is the (brightness) pitch of the sound used by tier t, already sorted low -> high.
    Targets rise evenly from the lowest sound by at least `step` semitones per tier.
    """
    if not measured_hz:
        return []
    m = [semitones(h) for h in measured_hz]
    span = max(step * (tiers - 1), m[-1] - m[0])
    out = []
    for t in range(tiers):
        target = m[0] + span * t / max(1, tiers - 1)
        out.append(round(max(-clamp, min(clamp, target - m[t])), 2))
    # clamping can break the order: nudge so the final pitch never falls tier to tier
    for t in range(1, tiers):
        if m[t] + out[t] < m[t - 1] + out[t - 1]:
            out[t] = round(min(24.0, m[t - 1] + out[t - 1] - m[t] + 0.5), 2)
    return out


# ---------------- auto mode ----------------
def _keywords(keywords) -> list[str]:
    from .config import SATISFYING_KEYWORDS
    if isinstance(keywords, str):
        keywords = [k for k in re.split(r"[,;|]", keywords)]
    kws = [k.strip() for k in (keywords or []) if k and k.strip()]
    return kws or list(SATISFYING_KEYWORDS)


def _candidates(kws: list[str], rng: random.Random, want: int, max_tries: int) -> list[dict]:
    """Search, shuffle (seeded), download and measure until `want` short clips are found."""
    pool: list[SoundResult] = []
    for kw in kws:
        try:
            pool += search(kw)
        except ConnectionError as e:
            LOG.warning("search %r failed: %s", kw, e)
        if len(pool) >= want * 4:
            break
    # keep search order roughly (relevance) but shuffle within the top results so videos differ
    top = pool[: max(want * 4, 12)]
    rng.shuffle(top)
    out, tries, longs = [], 0, []
    for r in top:
        if len(out) >= want or tries >= max_tries:
            break
        tries += 1
        try:
            path = download(r)
            a = analyze(path)
        except Exception as e:
            LOG.info("skip %s: %s", r.mp3_url, e)
            continue
        if a["duration"] <= 0.02 or a["centroid"] <= 0:
            continue
        item = {"name": r.name, "url": r.mp3_url, "path": path, **a}
        (out if a["duration"] <= MAX_CLIP_SECONDS else longs).append(item)
    if len(out) < want:  # not enough short clips: allow longer ones (load_sound caps them anyway)
        out += sorted(longs, key=lambda d: d["duration"])[: want - len(out)]
    return out


def auto_plan(keywords=None, tiers: int = 9, strategy: str = "sorted", count: int = 4,
              separate: bool = True, drop_keyword: str = "", final_keyword: str = "",
              step: float = 1.6, seed: int = 1) -> dict:
    """Pick Myinstants sounds and map them to tiers, low pitch -> high pitch.

    Returns {"tier_sounds", "tier_semitones", "sound_path", "drop_sound", "final_sound", "sounds", "keywords"}.
    Empty lists / strings mean "use the built-in pop" (offline or nothing found)."""
    rng = random.Random(seed)
    kws = _keywords(keywords)
    plan = {"tier_sounds": [], "tier_semitones": [], "sound_path": "", "drop_sound": "", "final_sound": "",
            "sounds": [], "keywords": kws}
    want = 1 if strategy == "pitch_up" else max(1, min(count, tiers))
    extra = 1 if (separate and not drop_keyword) else 0
    found = _candidates(kws, rng, want + extra, max_tries=(want + extra) * 3 + 2)
    if not found:
        return plan
    drop = None
    if separate and not drop_keyword and len(found) > want:
        drop = min(found, key=lambda d: d["duration"])        # shortest clip = the lightest "tick"
        found = [f for f in found if f is not drop]
    found = found[:want]
    if strategy == "pitch_up" or len(found) == 1:
        base = found[0]
        plan["sound_path"] = base["path"]
        plan["tier_semitones"] = [round(t * step, 2) for t in range(tiers)]
    else:
        found.sort(key=lambda d: d["pitch_hz"])
        n = len(found)
        per_tier = [found[min(n - 1, t * n // tiers)] for t in range(tiers)]
        plan["tier_sounds"] = [d["path"] for d in per_tier]
        plan["tier_semitones"] = tier_pitches([d["pitch_hz"] for d in per_tier], tiers, step)
        plan["sound_path"] = found[0]["path"]
    plan["sounds"] = [{k: d[k] for k in ("name", "url", "path", "pitch_hz", "f0", "duration")} for d in found]
    if separate:
        for kw, key in ((drop_keyword, "drop_sound"), (final_keyword, "final_sound")):
            if kw:
                got = _candidates([kw], rng, 1, 4)
                if got:
                    plan[key] = got[0]["path"]
        if not plan["drop_sound"] and drop is not None:
            plan["drop_sound"] = drop["path"]
    return plan


def apply_plan(cfg, plan: dict) -> None:
    """Write an auto_plan result into a MergeConfig (in place)."""
    cfg.tier_sounds = list(plan.get("tier_sounds") or [])
    cfg.tier_semitones = list(plan.get("tier_semitones") or [])
    cfg.sound_path = plan.get("sound_path") or ""
    cfg.drop_sound = plan.get("drop_sound") or ""
    cfg.final_sound = plan.get("final_sound") or ""


def resolve_auto(cfg) -> dict | None:
    """If cfg.auto_sounds is on, fetch + assign sounds (in place). Never raises: offline = built-in pop."""
    if not getattr(cfg, "auto_sounds", False):
        return None
    try:
        plan = auto_plan(cfg.auto_sound_keywords, cfg.tiers, cfg.auto_sound_strategy, cfg.auto_sound_count,
                         cfg.auto_sound_separate, cfg.auto_drop_keyword, cfg.auto_final_keyword,
                         cfg.pitch_step, cfg.seed)
    except Exception as e:  # pragma: no cover - network edge cases
        LOG.warning("auto sounds failed, using built-in pop: %s", e)
        return None
    if not (plan["sound_path"] or plan["tier_sounds"]):
        LOG.warning("auto sounds: nothing found for %s, using built-in pop", plan["keywords"])
        return plan
    apply_plan(cfg, plan)
    return plan
