"""Tier image prep: AI cut-outs (background removal) + "skip images with text".

Engines, best available first, all optional so the app and the .exe always start:
  * AI cut-out: the BiRefNet / ISNet / U²-Net models that rembg uses, run with onnxruntime.
    If the `rembg` package is installed its session is used, otherwise a built-in runner with the
    exact same pre/post-processing (no rembg / PIL / OpenCV needed). The BRIA model is never used
    (its licence is non-commercial, and monetised Shorts are commercial).
  * Quick cut-out ("quick"): no AI, removes a flat background connected to the image border.
  * Text check: PaddleOCR's PP-OCRv4 text *detector* (4.7 MB ONNX), only finds where text is.

Models download once into %APPDATA%/MoneyMaker911/models (existing rembg downloads are reused).
Results are cached by file path + size + mtime, so a render only pays for an image once.

Threading: pygame is not thread-safe, so every pygame call here runs inside `lock` (the desktop
app passes GFX_LOCK). The heavy ONNX inference runs outside the lock so the preview stays smooth.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
import urllib.request
from pathlib import Path
from typing import Callable

import numpy as np

from .config import IMAGE_EXTS

# name -> how rembg runs it. Order = quality order shown in the UI.
MODELS: dict[str, dict] = {
    "birefnet-general": {
        "label": "BiRefNet · best edges (973 MB, 16 GB RAM)", "min_ram_gb": 12, "file": "BiRefNet-general-epoch_244.onnx",
        "rembg_name": "birefnet-general", "md5": "7a35a0141cbbc80de11d9c9a28f52697", "mb": 973,
        "size": 1024, "mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225), "sigmoid": True},
    "isnet-general-use": {
        "label": "ISNet · great, fast (179 MB)", "file": "isnet-general-use.onnx",
        "rembg_name": "isnet-general-use", "md5": "fc16ebd8b0c10d971d3513d564d01e29", "mb": 179,
        "size": 1024, "mean": (0.5, 0.5, 0.5), "std": (1.0, 1.0, 1.0), "sigmoid": False},
    "u2net": {
        "label": "U²-Net · classic (176 MB)", "file": "u2net.onnx",
        "rembg_name": "u2net", "md5": "60024c5c889badc19c04ad937298a77b", "mb": 176,
        "size": 320, "mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225), "sigmoid": False},
}
QUICK = "quick"
DEFAULT_MODEL = "isnet-general-use"
MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/{}"
TEXT_DET = {"file": "ch_PP-OCRv4_det_infer.onnx", "mb": 5,
            "url": "https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv4/ch_PP-OCRv4_det_infer.onnx"}
MAX_SIDE = 1200          # cut-outs are stored at most this big (sprites never need more)
CUTOUT_VERSION = 1       # bump when the cut-out look changes so caches rebuild

_sessions: dict[str, object] = {}
_session_lock = threading.Lock()
_cache_lock = threading.Lock()
_cache: dict | None = None


# ---------------------------------------------------------------- paths & cache
def data_dir() -> Path:
    d = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "MoneyMaker911"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sub(name: str) -> Path:
    d = data_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file_key(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads((data_dir() / "imagecache.json").read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _save_cache() -> None:
    with _cache_lock:
        try:
            p = data_dir() / "imagecache.json"
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(_load_cache()), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass


def cutout_path(src: str, model: str) -> Path | None:
    key = _file_key(src)
    if not key:
        return None
    h = hashlib.sha1(f"{key}|{model}|{CUTOUT_VERSION}".encode()).hexdigest()[:20]
    return _sub("cutouts") / f"{h}.png"


def is_cutout(path: str) -> bool:
    try:
        return Path(path).parent.resolve() == (data_dir() / "cutouts").resolve()
    except OSError:
        return False


# ---------------------------------------------------------------- availability
def has_onnx() -> bool:
    import importlib.util
    return importlib.util.find_spec("onnxruntime") is not None


def has_rembg() -> bool:
    import importlib.util
    return importlib.util.find_spec("rembg") is not None


def _model_file(name: str) -> Path | None:
    """Already-downloaded model: ours first, then rembg's own caches."""
    m = MODELS[name]
    cands = [_sub("models") / m["file"]]
    home = Path(os.environ.get("U2NET_HOME", Path.home() / ".u2net"))
    rhome = Path(os.environ.get("REMBG_HOME", Path.home() / ".rembg"))
    cands += [home / f"{m['rembg_name']}.onnx", rhome / "models" / m["rembg_name"] / f"{m['rembg_name']}.onnx"]
    for p in cands:
        if p.exists() and p.stat().st_size > 1_000_000:
            return p
    return None


def status() -> dict:
    """What the UI shows: engines available, models present."""
    ram = total_ram_gb()
    return {"onnx": has_onnx(), "rembg": has_rembg(), "ram_gb": round(ram, 1),
            "models": [{"id": k, "label": v["label"], "ready": _model_file(k) is not None,
                        "too_big": bool(v.get("min_ram_gb") and 0 < ram < v["min_ram_gb"])} for k, v in MODELS.items()]
            + [{"id": QUICK, "label": "Quick · flat backgrounds, no AI", "ready": True, "too_big": False}],
            "text_ready": (_sub("models") / TEXT_DET["file"]).exists()}


def _download(url: str, dest: Path, md5: str | None, note: Callable[[str], None] | None, label: str) -> Path:
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "MoneyMaker911"})
    h = hashlib.md5()
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got, last = 0, -1
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            pct = int(got * 100 / total) if total else 0
            if note and pct != last and pct % 5 == 0:
                note(f"Downloading {label}… {pct}%")
                last = pct
    if md5 and h.hexdigest() != md5:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{label} download was corrupted, try again")
    os.replace(tmp, dest)
    return dest


def _ort_session(path: Path):
    import onnxruntime as ort  # optional dependency, imported only when an AI feature is used
    so = ort.SessionOptions()
    so.log_severity_level = 3
    so.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 1)
    # no arena / pattern pre-allocation: BiRefNet otherwise grabs several GB of RAM up front
    so.enable_cpu_mem_arena = False
    so.enable_mem_pattern = False
    provs = [p for p in ("DmlExecutionProvider", "CUDAExecutionProvider") if p in ort.get_available_providers()]
    try:
        return ort.InferenceSession(str(path), sess_options=so, providers=provs + ["CPUExecutionProvider"])
    except Exception:
        return ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])


def _get_session(name: str, note=None):
    with _session_lock:
        if name in _sessions:
            return _sessions[name]
        if not has_onnx():
            raise RuntimeError("AI cut-outs need onnxruntime (pip install onnxruntime)")
        if name == "textdet":
            p = _sub("models") / TEXT_DET["file"]
            if not p.exists():
                _download(TEXT_DET["url"], p, None, note, "text detector")
        else:
            p = _model_file(name)
            if p is None:
                m = MODELS[name]
                p = _download(MODEL_URL.format(m["file"]), _sub("models") / m["file"], m["md5"], note,
                              f"{name} ({m['mb']} MB, once)")
        if note:
            note("Loading AI model…")
        _sessions[name] = _ort_session(p)
        return _sessions[name]


# ---------------------------------------------------------------- pixels (pygame under lock)
def _load_rgba(path: str, lock) -> np.ndarray:
    """H x W x 4 uint8, downscaled so the long side <= MAX_SIDE."""
    import pygame
    with lock:
        src = pygame.image.load(path)
        w, h = src.get_size()
        img = pygame.Surface((w, h), pygame.SRCALPHA, 32)
        img.blit(src, (0, 0))
        k = min(1.0, MAX_SIDE / max(w, h))
        if k < 1.0:
            img = pygame.transform.smoothscale(img, (max(1, int(w * k)), max(1, int(h * k))))
        rgb = pygame.surfarray.array3d(img).transpose(1, 0, 2)
        a = pygame.surfarray.array_alpha(img).T
    return np.dstack([rgb, a]).astype(np.uint8)


def _resize(arr: np.ndarray, size: tuple[int, int], lock) -> np.ndarray:
    """Smooth-resize an HxWx3 uint8 or HxW uint8 array to (w, h)."""
    import pygame
    gray = arr.ndim == 2
    a3 = np.repeat(arr[:, :, None], 3, 2) if gray else arr[:, :, :3]
    with lock:
        s = pygame.surfarray.make_surface(np.ascontiguousarray(a3.transpose(1, 0, 2)))
        s = pygame.transform.smoothscale(s, size)
        out = pygame.surfarray.array3d(s).transpose(1, 0, 2)
    return out[:, :, 0] if gray else out


def _save_png(rgba: np.ndarray, path: Path, lock) -> None:
    import pygame
    with lock:
        h, w = rgba.shape[:2]
        s = pygame.image.frombuffer(np.ascontiguousarray(rgba).tobytes(), (w, h), "RGBA")
        tmp = path.with_name(path.stem + ".tmp.png")
        pygame.image.save(s, str(tmp))
    os.replace(tmp, path)


# ---------------------------------------------------------------- AI cut-out
def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _ai_mask(rgba: np.ndarray, name: str, lock, note=None) -> np.ndarray:
    m = MODELS[name]
    h, w = rgba.shape[:2]
    if has_rembg():
        try:  # the user's own rembg install: same models, same maths
            from PIL import Image
            from rembg import new_session
            key = "rembg:" + name
            with _session_lock:
                if key not in _sessions:
                    _sessions[key] = new_session(m["rembg_name"])
            mask = _sessions[key].predict(Image.fromarray(rgba[:, :, :3]))[0]
            return np.asarray(mask.convert("L"), dtype=np.uint8)
        except Exception:
            pass  # fall through to the built-in runner
    sess = _get_session(name, note)
    S = m["size"]
    x = _resize(rgba[:, :, :3], (S, S), lock).astype(np.float32)
    x /= max(float(x.max()), 1e-6)
    x = (x - np.array(m["mean"], np.float32)) / np.array(m["std"], np.float32)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    pred = sess.run(None, {sess.get_inputs()[0].name: x})[0][:, 0]
    if m["sigmoid"]:
        pred = _sigmoid(pred)
    pred = np.squeeze(pred)
    pred = (pred - pred.min()) / max(float(pred.max() - pred.min()), 1e-6)
    return _resize((pred.clip(0, 1) * 255).astype(np.uint8), (w, h), lock)


def _quick_mask(rgba: np.ndarray) -> np.ndarray | None:
    """No-AI cut-out: remove the flat background colour that touches the border."""
    rgb = rgba[:, :, :3].astype(np.int16)
    if rgba[:, :, 3].min() < 250:          # already transparent: keep its own alpha
        return rgba[:, :, 3].copy()
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    if (np.abs(border - bg).max(axis=1) < 38).mean() < 0.7:
        return None                         # busy / photo background: needs the AI models
    near = np.abs(rgb - bg).max(axis=2) < 38
    reach = np.zeros_like(near)
    reach[0], reach[-1], reach[:, 0], reach[:, -1] = near[0], near[-1], near[:, 0], near[:, -1]
    for _ in range(4000):                   # flood fill from the border (vectorised, converges fast)
        grow = reach.copy()
        grow[1:] |= reach[:-1]
        grow[:-1] |= reach[1:]
        grow[:, 1:] |= reach[:, :-1]
        grow[:, :-1] |= reach[:, 1:]
        grow &= near
        if (grow == reach).all():
            break
        reach = grow
    mask = np.where(reach, 0, 255).astype(np.uint8)
    # soften the edge by one pixel
    soft = mask.astype(np.float32)
    soft[1:-1, 1:-1] = (soft[1:-1, 1:-1] * 4 + soft[:-2, 1:-1] + soft[2:, 1:-1] + soft[1:-1, :-2] + soft[1:-1, 2:]) / 8
    return soft.astype(np.uint8)


def _compose(rgba: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    """Apply the mask, drop specks, crop to the subject, pad to a centred square."""
    alpha = np.minimum(rgba[:, :, 3].astype(np.uint16), mask.astype(np.uint16)).astype(np.uint8)
    alpha[alpha < 12] = 0
    solid = alpha > 40
    n = int(solid.sum())
    if n < 50 or n > alpha.size * 0.985:
        return None  # nothing found, or the "subject" is the whole picture
    # crop to the subject, ignoring stray specks (rows/cols with only a few solid pixels)
    rows = np.nonzero(solid.sum(axis=1) >= max(2, solid.shape[1] // 200))[0]
    cols = np.nonzero(solid.sum(axis=0) >= max(2, solid.shape[0] // 200))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    y0, y1, x0, x1 = rows.min(), rows.max() + 1, cols.min(), cols.max() + 1
    out = np.dstack([rgba[y0:y1, x0:x1, :3], alpha[y0:y1, x0:x1]])
    h, w = out.shape[:2]
    side = int(max(h, w) * 1.04) + 2
    sq = np.zeros((side, side, 4), np.uint8)
    oy, ox = (side - h) // 2, (side - w) // 2
    sq[oy:oy + h, ox:ox + w] = out
    return sq


def make_cutout(src: str, model: str = DEFAULT_MODEL, lock=None, note=None) -> str:
    """Cut-out PNG path for `src` (cached). Returns src unchanged when it can't be cut out."""
    lock = lock or contextlib.nullcontext()
    dst = cutout_path(src, model)
    if dst is None:
        return src
    if dst.exists():
        return str(dst)
    rgba = _load_rgba(src, lock)
    if model in MODELS and has_onnx():
        mask = _ai_mask(rgba, model, lock, note)
    else:
        mask = _quick_mask(rgba)
    sq = _compose(rgba, mask) if mask is not None else None
    if sq is None:
        return src
    _save_png(sq, dst, lock)
    return str(dst)


# ---------------------------------------------------------------- text check
def _components(binary: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """4-connected components of a small boolean map -> (area, x0, y0, x1, y1)."""
    h, w = binary.shape
    seen = np.zeros_like(binary)
    out = []
    for y0, x0 in zip(*np.nonzero(binary)):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        area, ax0, ay0, ax1, ay1 = 0, x0, y0, x0, y0
        while stack:
            y, x = stack.pop()
            area += 1
            ax0, ax1, ay0, ay1 = min(ax0, x), max(ax1, x), min(ay0, y), max(ay1, y)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and binary[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append((area, ax0, ay0, ax1, ay1))
    return out


def text_score(src: str, lock=None, note=None) -> float:
    """Share of the picture covered by confidently detected text lines (0 = none)."""
    lock = lock or contextlib.nullcontext()
    rgba = _load_rgba(src, lock)
    h, w = rgba.shape[:2]
    k = 960 / max(h, w)
    W, H = max(32, int(round(w * k / 32)) * 32), max(32, int(round(h * k / 32)) * 32)
    rgb = rgba[:, :, :3].copy()
    rgb[rgba[:, :, 3] < 128] = 255          # transparent pixels read as white paper
    x = _resize(rgb, (W, H), lock).astype(np.float32)[:, :, ::-1] / 255.0   # BGR like PaddleOCR
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    sess = _get_session("textdet", note)
    prob = sess.run(None, {sess.get_inputs()[0].name: x.transpose(2, 0, 1)[None].astype(np.float32)})[0][0, 0]
    # 4x4 pooled map keeps the component search tiny
    ph, pw = prob.shape[0] // 4, prob.shape[1] // 4
    pooled = prob[:ph * 4, :pw * 4].reshape(ph, 4, pw, 4).mean(axis=(1, 3))
    # DBNet marks text as thin, solid, horizontal bars; cartoon blobs come out round / ragged
    covered = 0
    for area, x0, y0, x1, y1 in _components(pooled > 0.3):
        bw, bh = x1 - x0 + 1, y1 - y0 + 1
        if area < 12 or bw < bh * 2 or area < 0.7 * bw * bh or bh > 0.25 * ph:
            continue
        covered += area
    return covered / float(ph * pw)


TEXT_THRESHOLD = 0.002   # >= 0.2% of the picture covered by text lines = caption / watermark


def has_text(src: str, lock=None, note=None) -> bool | None:
    """True/False, or None when it can't be checked (no onnxruntime, unreadable file). Cached."""
    key = _file_key(src)
    if not key:
        return None
    c = _load_cache()
    if key in c and "text" in c[key]:
        return c[key]["text"] >= TEXT_THRESHOLD
    if not has_onnx():
        return None
    try:
        s = text_score(src, lock, note)
    except Exception:
        return None
    with _cache_lock:
        c.setdefault(key, {})["text"] = round(s, 5)
    _save_cache()
    return s >= TEXT_THRESHOLD


def cached_has_text(src: str) -> bool | None:
    key = _file_key(src)
    v = _load_cache().get(key, {}).get("text") if key else None
    return None if v is None else v >= TEXT_THRESHOLD


# ---------------------------------------------------------------- the pipeline the app uses
def candidate_images(cfg) -> list[str]:
    """Every image the user gave (folder in natural name order, or the picked files)."""
    if cfg.tier_image_folder and Path(cfg.tier_image_folder).is_dir():
        files = [p for p in Path(cfg.tier_image_folder).iterdir() if p.suffix.lower() in IMAGE_EXTS]
        key = lambda p: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]
        return [str(p) for p in sorted(files, key=key)]
    return [p for p in cfg.tier_images if p]


def total_ram_gb() -> float:
    """Physical RAM in GB (0 when unknown). No psutil needed."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MS()
            st.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except Exception:
        return 0.0


def _model_of(cfg) -> str:
    m = getattr(cfg, "cutout_model", DEFAULT_MODEL) or DEFAULT_MODEL
    if m in MODELS and not has_onnx():
        return QUICK
    need = MODELS.get(m, {}).get("min_ram_gb", 0)
    if need and 0 < total_ram_gb() < need:
        return DEFAULT_MODEL   # BiRefNet on a small-RAM PC would freeze it; ISNet is close in quality
    return m if (m in MODELS or m == QUICK) else DEFAULT_MODEL


def tier_images(cfg, prepare: bool = False, lock=None, note: Callable[[str], None] | None = None) -> dict:
    """Final image per tier after the text check and cut-outs.
    prepare=False only reads caches (instant, safe inside the renderer);
    prepare=True runs whatever is missing (downloads / inference) — call it from a worker thread.
    Returns {"images": [...], "sources": [originals], "skipped": [names with text], "cut": n, "errors": [...]}"""
    cands = candidate_images(cfg)
    reject = bool(getattr(cfg, "reject_text", False))
    cut = bool(getattr(cfg, "ai_cutout", False))
    model = _model_of(cfg)
    imgs, skipped, errors, ncut = [], [], [], 0
    sources: list[str] = []
    for i, p in enumerate(cands):
        if len(imgs) >= cfg.tiers:
            break
        if reject:
            if prepare and note:
                note(f"Checking for text {i + 1}/{len(cands)}…")
            t = has_text(p, lock, note) if prepare else cached_has_text(p)
            if t:
                skipped.append(Path(p).name)
                continue
        imgs.append(p)
    sources = list(imgs)
    if cut:
        for i, p in enumerate(imgs):
            dst = cutout_path(p, model)
            if dst is not None and dst.exists():
                imgs[i], ncut = str(dst), ncut + 1
            elif prepare:
                if note:
                    note(f"Cutting out {i + 1}/{len(imgs)}…")
                try:
                    out = make_cutout(p, model, lock, note)
                    if out != p:
                        imgs[i], ncut = out, ncut + 1
                except Exception as e:
                    errors.append(f"{Path(p).name}: {e}")
    return {"images": imgs, "sources": sources, "skipped": skipped, "cut": ncut, "errors": errors, "model": model}


def cutout_folder(src_dir: str, out_dir: str, model: str = DEFAULT_MODEL, reject_text: bool = False,
                  note: Callable[[str], None] | None = None) -> list[dict]:
    """CLI helper: cut out every image in a folder into out_dir (keeps names, .png)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in Path(src_dir).iterdir() if p.suffix.lower() in IMAGE_EXTS)
    model = _model_of(type("C", (), {"cutout_model": model})())
    res = []
    for i, p in enumerate(files):
        row = {"file": p.name, "text": None, "out": ""}
        if note:
            note(f"{i + 1}/{len(files)} {p.name}")
        if reject_text:
            row["text"] = has_text(str(p), note=note)
            if row["text"]:
                res.append(row)
                continue
        c = make_cutout(str(p), model, note=note)
        if c != str(p):
            dst = out / (p.stem + ".png")
            dst.write_bytes(Path(c).read_bytes())
            row["out"] = str(dst)
        res.append(row)
    return res
