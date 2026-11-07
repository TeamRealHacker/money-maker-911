"""Find FFmpeg: bundled next to the .exe, imageio-ffmpeg, or system PATH."""
from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates += [base / exe, Path(sys.executable).parent / exe]
    candidates.append(Path(__file__).resolve().parent.parent / "bin" / exe)
    for c in candidates:
        if c.exists():
            return str(c)
    try:
        import imageio_ffmpeg  # type: ignore
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise RuntimeError("FFmpeg not found. Install it (winget install Gyan.FFmpeg) or keep ffmpeg.exe next to the app.")


@lru_cache(maxsize=1)
def best_encoder() -> list[str]:
    """Pick hardware H.264 if available (NVENC / QSV / AMF), else libx264."""
    import subprocess
    try:
        out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except Exception:
        out = ""
    for enc, args in (("h264_nvenc", ["-preset", "p5", "-cq", "21"]),
                      ("h264_qsv", ["-global_quality", "22"]),
                      ("h264_amf", ["-quality", "quality"])):
        if enc in out and _encoder_works(enc):
            return ["-c:v", enc, *args]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


def _encoder_works(enc: str) -> bool:
    import subprocess
    try:
        r = subprocess.run([ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
                            "-c:v", enc, "-f", "null", "-"], capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


_HW = {  # (codec, vendor) -> encoder name
    ("h264", "nvidia"): "h264_nvenc", ("h264", "intel"): "h264_qsv", ("h264", "amd"): "h264_amf",
    ("h265", "nvidia"): "hevc_nvenc", ("h265", "intel"): "hevc_qsv", ("h265", "amd"): "hevc_amf",
}


@lru_cache(maxsize=None)
def _available(enc: str) -> bool:
    import subprocess
    try:
        out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-encoders"], capture_output=True, text=True,
                             timeout=20).stdout
    except Exception:
        return False
    return enc in out and _encoder_works(enc)


def encoder_args(codec: str = "h264", quality: int = 18, which: str = "auto") -> tuple[list[str], str]:
    """Video encoder arguments for the export settings. Hardware (NVIDIA/Intel/AMD) when asked for or
    when 'auto' finds one that really works; otherwise CPU (libx264 / libx265). Returns (args, name)."""
    codec = "h265" if codec == "h265" else "h264"
    q = int(quality)
    vendors = ["nvidia", "intel", "amd"] if which == "auto" else ([which] if which in ("nvidia", "intel", "amd") else [])
    for v in vendors:
        enc = _HW[(codec, v)]
        if _available(enc):
            if v == "nvidia":
                args = ["-c:v", enc, "-preset", "p5", "-rc", "vbr", "-cq", str(q + 2), "-b:v", "0"]
            elif v == "intel":
                args = ["-c:v", enc, "-global_quality", str(q + 3)]
            else:
                args = ["-c:v", enc, "-quality", "quality", "-rc", "cqp", "-qp_i", str(q + 2), "-qp_p", str(q + 4)]
            if codec == "h265":
                args += ["-tag:v", "hvc1"]
            return args, enc
    if codec == "h265" and _available("libx265"):
        return ["-c:v", "libx265", "-preset", "fast", "-crf", str(q + 4), "-tag:v", "hvc1",
                "-x265-params", "log-level=error"], "libx265"
    return ["-c:v", "libx264", "-preset", "fast" if q <= 15 else "veryfast", "-crf", str(q)], "libx264"
