"""AI cut-outs (rembg) + optional 'reject images with text'. Everything is lazy/optional:
if rembg is not installed the original image is used, nothing crashes.
Models: birefnet-general (best), isnet-general-use, u2net. Never the BRIA default."""
from __future__ import annotations
import hashlib, os
from pathlib import Path

MODELS = ("birefnet-general", "isnet-general-use", "u2net")
_sessions: dict = {}


def cache_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / ".cache") / "MoneyMaker911" / "cutouts"
    base.mkdir(parents=True, exist_ok=True)
    return base


def available() -> bool:
    try:
        import rembg  # noqa: F401
        return True
    except Exception:
        return False


def has_text(path: str) -> bool:
    """True if OCR finds readable text. Needs optional rapidocr-onnxruntime; else False."""
    try:
        from rapidocr_onnxruntime import RapidOCR
        res, _ = RapidOCR()(path)
        return bool(res) and any(float(r[2]) > 0.6 and len(r[1].strip()) >= 3 for r in res)
    except Exception:
        return False


def cut_out(path: str, model: str = "birefnet-general") -> str:
    """Return path to a transparent PNG cut-out (cached). Falls back to the original path."""
    if model not in MODELS:
        model = MODELS[0]
    p = Path(path)
    key = hashlib.sha1(f"{p.resolve()}|{p.stat().st_mtime_ns}|{model}".encode()).hexdigest()[:16]
    out = cache_dir() / f"{p.stem}_{key}.png"
    if out.exists():
        return str(out)
    try:
        from rembg import new_session, remove
        from PIL import Image
        if model not in _sessions:
            _sessions[model] = new_session(model)
        with Image.open(p) as im:
            remove(im.convert("RGBA"), session=_sessions[model]).save(out)
        return str(out)
    except Exception:
        return str(path)


def prepare(paths: list[str], model: str, reject_text: bool) -> list[str]:
    res = []
    for x in paths:
        if reject_text and has_text(x):
            continue
        res.append(cut_out(x, model))
    return res
