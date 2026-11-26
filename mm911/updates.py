"""🔄 Update center: is there a newer Money Maker 911, and how do I get it?

The app is a portable .exe published as a GitHub release (the `nightly` pre-release on every push
to main, plus versioned `v*` tags). This module answers, offline-first and without extra
dependencies:

  current_version()      - the version this build reports
  parse_version("0.24.1")- comparable tuple ("1.2.3-rc1" sorts below "1.2.3")
  check(latest=...)      - is a newer release out? (network is optional; pass `latest` in tests)
  download(asset, dest)  - fetch the new .exe into the app folder
  install(asset, ...)    - swap the running .exe on Windows (old one is renamed, never deleted)
  changelog(text)        - the release notes, trimmed to the bullets a human wants to read

Only the standard library is used (urllib), so the update center works in the portable build
without shipping requests. Every network call fails soft: the caller gets
`{"error": ...}` / False and the app keeps working.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .config import VERSION

REPO = "TeamRealHacker/money-maker-911"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
API_TAGS = f"https://api.github.com/repos/{REPO}/releases"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
TIMEOUT = 12
_ASSET_HINTS = (".exe", ".zip")


# ---------- versions ----------
def parse_version(text: str) -> tuple:
    """'v0.24.1' -> (0, 24, 1). Pre-releases sort before the release: 1.0.0-rc1 < 1.0.0."""
    s = str(text or "").strip().lstrip("vV")
    m = re.match(r"(\d+(?:\.\d+)*)(?:[-+.]?(.*))?$", s)
    if not m:
        return ()
    nums = tuple(int(p) for p in m.group(1).split(".") if p.isdigit())
    tail = (m.group(2) or "").lower()
    # a bare release outranks its pre-releases
    return nums + ((1, "") if not tail else (0, tail))


def is_newer(candidate: str, current: str = "") -> bool:
    """True when `candidate` is a later version than `current` (defaults to this build)."""
    a, b = parse_version(candidate), parse_version(current or VERSION)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def current_version() -> str:
    return VERSION


# ---------- checking ----------
def _get_json(url: str, timeout: int = TIMEOUT) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"MoneyMaker911/{VERSION}",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _release_info(payload: dict) -> dict:
    """Normalise a GitHub release payload into what the update card shows."""
    assets = []
    for a in payload.get("assets") or []:
        name = str(a.get("name") or "")
        if name.lower().endswith(_ASSET_HINTS):
            assets.append({"name": name, "url": a.get("browser_download_url", ""),
                           "size": int(a.get("size") or 0)})
    return {
        "version": str(payload.get("tag_name") or payload.get("name") or "").lstrip("vV"),
        "name": payload.get("name") or payload.get("tag_name") or "",
        "notes": payload.get("body") or "",
        "url": payload.get("html_url") or RELEASES_PAGE,
        "published": payload.get("published_at") or "",
        "prerelease": bool(payload.get("prerelease")),
        "assets": assets,
    }


def check(latest: dict | str | None = None, current: str = "",
          include_prerelease: bool = True, timeout: int = TIMEOUT) -> dict:
    """Compare this build with the newest release.

    `latest` lets callers (and tests) skip the network: pass a GitHub release payload or a
    version string. Without it the newest release is fetched from GitHub, and any network
    problem is reported in `error` instead of raised.
    """
    cur = current or VERSION
    out = {"current": cur, "latest": "", "newer": False, "notes": "", "url": RELEASES_PAGE,
           "published": "", "prerelease": False, "assets": [], "error": "", "checked": False}
    info: dict = {}
    try:
        if isinstance(latest, dict):
            info = _release_info(latest)
        elif isinstance(latest, str) and latest:
            info = {"version": latest.lstrip("vV")}
        else:
            payload = None
            if include_prerelease:
                # `latest` skips pre-releases, but the portable build ships as the nightly one
                for rel in _get_json(API_TAGS + "?per_page=10", timeout) or []:
                    if not rel.get("draft"):
                        payload = rel
                        break
            payload = payload or _get_json(API_LATEST)
            info = _release_info(payload)
        out["checked"] = True
    except urllib.error.HTTPError as e:
        out["error"] = f"GitHub answered {e.code} - no release found yet"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        out["error"] = f"could not reach GitHub ({e})"
    for k in ("version", "notes", "url", "published", "prerelease", "assets"):
        if k in info:
            out["latest" if k == "version" else k] = info[k]
    out["newer"] = bool(out["latest"]) and is_newer(out["latest"], cur)
    return out


def changelog(text: str, limit: int = 14) -> list[str]:
    """Release notes -> the lines worth showing (first `limit`, bullets cleaned up)."""
    lines = []
    for raw in str(text or "").splitlines():
        s = raw.strip()
        if not s or s.startswith(("#", "<!--", "|", "```")):
            continue
        s = re.sub(r"^[-*+]\s+", "", s)
        s = re.sub(r"\s+", " ", s)
        if s:
            lines.append(s)
        if len(lines) >= limit:
            break
    return lines


# ---------- downloading / installing ----------
def download(url: str, dest: str, timeout: int = 180) -> dict:
    """Stream a release asset to `dest` (atomic: temp file, then rename)."""
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": f"MoneyMaker911/{VERSION}"})
    tmp = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, tempfile.NamedTemporaryFile(
                delete=False, dir=str(dest_path.parent), suffix=".part") as f:
            tmp = f.name
            shutil.copyfileobj(r, f, length=1024 * 256)
        Path(tmp).replace(dest_path)
        return {"file": str(dest_path), "size": dest_path.stat().st_size}
    except (urllib.error.URLError, OSError, ValueError) as e:
        if tmp and Path(tmp).exists():
            try:
                Path(tmp).unlink()
            except OSError:
                pass
        return {"error": f"download failed ({e})"}


def is_frozen() -> bool:
    """True in the portable .exe (PyInstaller) - the only build that can self-update."""
    return bool(getattr(sys, "frozen", False))


def exe_path() -> Path:
    return Path(sys.executable if is_frozen() else sys.argv[0]).resolve()


def install(new_file: str, target: str | None = None, restart: bool = True) -> dict:
    """Replace the running .exe with `new_file`.

    Windows cannot overwrite a running image, so the current .exe is renamed to `.old` (kept, so
    a bad update can be undone by hand) and the new one moved into place; a tiny detached
    launcher starts it again after this process exits.
    """
    if not is_frozen():
        return {"error": "self-update only works in the portable .exe - "
                         "use the release page for a source install", "url": RELEASES_PAGE}
    src = Path(new_file)
    if not src.exists():
        return {"error": "downloaded file is missing"}
    dest = Path(target) if target else exe_path()
    old = dest.with_suffix(dest.suffix + ".old")
    try:
        if old.exists():
            old.unlink()
        if dest.exists():
            dest.replace(old)
        shutil.copy2(src, dest)
    except OSError as e:
        # put the old one back if we can, so the user is never left without an app
        try:
            if old.exists() and not dest.exists():
                old.replace(dest)
        except OSError:
            pass
        return {"error": f"could not replace the app ({e}) - close other copies and retry"}
    started = False
    if restart:
        try:
            import subprocess
            creation = 0x00000008 if os.name == "nt" else 0     # DETACHED_PROCESS
            subprocess.Popen([str(dest)], close_fds=True, creationflags=creation)
            started = True
        except OSError:
            started = False
    return {"ok": True, "file": str(dest), "old": str(old) if old.exists() else "", "restarted": started}


def status(current: str = "") -> dict:
    """Small summary for the app's sidebar badge (no network)."""
    return {"current": current or VERSION, "repo": REPO, "releases": RELEASES_PAGE,
            "frozen": is_frozen()}
