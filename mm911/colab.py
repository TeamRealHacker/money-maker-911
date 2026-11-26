"""☁️ Google Colab GPU rendering (the missing Colab pieces, v0.23.0).

Money Maker 911 packs your project (code, preset, images, sounds) into a job zip, rents a Colab
GPU through the official `google-colab-cli`, runs colab/mm911_render.ipynb there, downloads every
finished video and stops the session so you keep your quota.

CLI: `python main.py colab check|quota|render ...`  (see mm911/cli.py)

On Windows the Colab CLI only runs inside WSL2, so every command is wrapped with
`wsl -e bash -lc` automatically when colab.exe is not on PATH but WSL is installed."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from .config import VERSION

REPO_NOTEBOOK = Path(__file__).resolve().parent.parent / "colab" / "mm911_render.ipynb"
SESSION_DEFAULT = "mm911"
LOG = None


def note(msg: str) -> None:
    print(msg, flush=True)


# ---------- discovery ----------
def _windows() -> bool:
    return os.name == "nt"


def _wsl_available() -> bool:
    if not _windows():
        return False
    try:
        r = subprocess.run(["wsl", "-e", "bash", "-lc", "command -v wslpath"],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _resolve(name: str) -> str | None:
    """Full path of an executable, honouring PATHEXT even when the environment lost it.
    A stripped PATHEXT (some CI runners / launchers) makes shutil.which ignore .bat and .cmd,
    which is exactly how the console-script wrappers are shipped on Windows."""
    found = shutil.which(name)
    if found or not _windows():
        return found
    exts = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    for ext in exts.split(os.pathsep if os.pathsep in exts else ";"):
        ext = ext.strip().lower()
        if ext:
            found = shutil.which(name + ext)
            if found:
                return found
    return None


def colab_cmd() -> list[str] | None:
    """The command prefix that runs `colab` on this machine (None when it is not installed).
    The resolved path is returned, not the bare name: on Windows only .exe resolves through
    PATH for a bare name, while shutil.which also finds .bat/.cmd wrappers."""
    exe = _resolve("colab")
    if exe:
        return [exe]
    if _windows() and _wsl_available():
        try:
            r = subprocess.run(["wsl", "-e", "bash", "-lc", "command -v colab"],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and r.stdout.strip():
                return ["wsl", "-e", "bash", "-lc"]
        except (OSError, subprocess.TimeoutExpired):
            pass
    return None


# Auth markers the CLI prints when the browser sign-in is needed.
AUTH_HINTS = ("unauthorized", "unauthenticated", "not authenticated", "login", "sign in", "oauth",
              "credentials", "permission denied", "401")


def check() -> dict:
    """What the app's status bar shows: ☁️ Colab ready / what is missing."""
    out = {"cli": False, "wsl": False, "notebook": False, "gpu": None, "ready": False,
           "needs_login": False, "note": "", "version": ""}
    prefix = colab_cmd()
    out["wsl"] = _wsl_available() if _windows() else True
    out["notebook"] = REPO_NOTEBOOK.exists()
    if prefix is None:
        out["note"] = ("google-colab-cli not found. One click installs it (WSL2 + Ubuntu + the CLI on "
                       "Windows); or install it yourself and press Re-check.")
        return out
    out["cli"] = True
    try:
        r = subprocess.run(_argv(prefix, ["colab", "version"]), capture_output=True, text=True,
                           timeout=90)
        lines = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
        out["version"] = lines[0][:60] if lines else ""
    except (OSError, subprocess.TimeoutExpired) as e:
        out["note"] = f"Colab CLI did not answer: {e}"
        return out
    try:
        r = subprocess.run(_argv(prefix, ["colab", "sessions"]), capture_output=True, text=True,
                           timeout=120)
        txt = ((r.stdout or "") + (r.stderr or "")).lower()
        if any(k in txt for k in AUTH_HINTS):
            out["needs_login"] = True
            out["note"] = ("Colab CLI found, but you are not signed in yet — press "
                           "\"Sign in to Google\" in the app.")
        else:
            out["ready"] = True
            out["note"] = "☁️ Colab ready"
    except (OSError, subprocess.TimeoutExpired) as e:
        out["note"] = f"Colab CLI did not answer: {e}"
    return out


GPU_CHOICES = [
    {"id": "T4", "label": "T4 · free tier", "note": "about as fast as a good laptop GPU", "free": True},
    {"id": "L4", "label": "L4 · paid", "note": "~2x faster than T4", "free": False},
    {"id": "A100", "label": "A100 · Pro only", "note": "fastest, needs Colab Pro", "free": False},
]

# The real CLI ships for Linux/macOS only, so Windows goes through WSL2. Ubuntu 24.04 blocks
# system pip installs (PEP 668), hence pipx - it also keeps the CLI off the system Python.
INSTALL_STEPS = [
    {"id": "wsl", "title": "Install WSL2 (Windows only)",
     "cmd": "wsl --install -d Ubuntu", "shell": "powershell", "note": "then reboot — skip on Linux/macOS"},
    {"id": "pipx", "title": "Install pipx inside Ubuntu",
     "cmd": "sudo apt-get update && sudo apt-get install -y pipx", "shell": "bash"},
    {"id": "cli", "title": "Install the Colab CLI",
     "cmd": "pipx install google-colab-cli", "shell": "bash"},
    {"id": "login", "title": "Sign in to Google (opens a browser)",
     "cmd": "colab logout; colab sessions", "shell": "bash", "note": "the CLI prints a URL — open it and approve"},
]

SETUP_URL = "https://github.com/googlecolab/google-colab-cli"


def manual_commands() -> dict:
    """The exact commands to paste, per platform - what the app shows when it cannot run them."""
    if _windows():
        return {"powershell": ["wsl --install -d Ubuntu",
                               "wsl -d Ubuntu -- bash -lc \"sudo apt-get update && "
                               "sudo apt-get install -y pipx && pipx install google-colab-cli\""],
                "signin": "wsl -d Ubuntu -- bash -lc \"colab sessions\"",
                "note": "Windows: the Colab CLI runs inside WSL2. Run the first command in PowerShell "
                        "as administrator, reboot when asked, then the second one (that is the whole "
                        "install). The sign-in URL appears in the app."}
    pip = "pipx" if shutil.which("pipx") else "pip3"
    return {"bash": [f"{pip} install google-colab-cli"], "signin": "colab sessions",
            "note": "Install the Colab CLI, then sign in - the URL appears in the app."}


def status() -> dict:
    """Everything the app's Colab card needs, in one call (offline)."""
    info = check()
    steps = [dict(s) for s in INSTALL_STEPS]
    if not _windows():                       # first step is Windows-only
        steps[0]["skip"] = True
    return {**info, "gpus": GPU_CHOICES, "steps": steps, "manual": manual_commands(),
            "version": VERSION, "platform": "windows" if _windows() else sys.platform,
            "wsl": info.get("wsl"), "hint": info.get("note", ""),
            "setup_url": SETUP_URL, "can_install": _runner() is not None}


# ---------- run commands for the user (one-click install / login) ----------
def _runner() -> list[str] | None:
    """The shell that can install things here: PowerShell on Windows (it can start WSL),
    the login shell elsewhere. None when there is nothing to run with."""
    if _windows():
        pw = _resolve("powershell") or _resolve("pwsh")
        return [pw] if pw else None
    sh = _resolve("bash") or _resolve("sh")
    return [sh, "-lc"] if sh else None


def install_commands() -> list[dict]:
    """The steps the one-click installer runs here, in order (each is shown before it runs)."""
    if _windows():
        return [{"title": "Install WSL2 + Ubuntu", "cmd": "wsl --install -d Ubuntu", "timeout": 1800,
                 "note": "Windows may ask to reboot. If WSL is already installed this is instant."},
                {"title": "Install pipx and the Colab CLI inside Ubuntu", "timeout": 1800,
                 "cmd": "wsl -d Ubuntu -- bash -lc \"sudo apt-get update && "
                        "sudo apt-get install -y pipx && pipx install google-colab-cli\"",
                 "note": "sudo may ask for your Ubuntu password once."}]
    pipx = shutil.which("pipx")
    cmd = "pipx install google-colab-cli" if pipx else "pip install --user google-colab-cli"
    return [{"title": "Install the Colab CLI", "cmd": cmd, "timeout": 1800,
             "note": "pipx keeps it out of your system Python." if pipx else
                     "pipx was not found, using pip --user instead."}]


def install(on_step=None, dry_run: bool = False) -> dict:
    """One click: run the install commands, reporting each one.

    `on_step(i, title, state, output)` is called as start/done/error so the app can show the
    progress live. Nothing is hidden: the command line is shown before it runs."""
    runner = _runner()
    steps = install_commands()
    if dry_run:
        return {"ok": False, "dry_run": True, "steps": steps,
                "note": "Preview only - press Install to run these."}
    if runner is None:
        return {"ok": False, "steps": steps, "error": "No shell found to run the installer with.",
                "manual": manual_commands()}
    results = []
    for i, st in enumerate(steps):
        if on_step:
            on_step(i, st["title"], "start", st["cmd"])
        try:
            r = subprocess.run(runner + [st["cmd"]], capture_output=True, text=True,
                               timeout=st.get("timeout", 1800))
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            ok = r.returncode == 0 or _looks_installed(out)
            results.append({"title": st["title"], "cmd": st["cmd"], "ok": ok,
                            "returncode": r.returncode, "output": out[-3000:]})
            if on_step:
                on_step(i, st["title"], "done" if ok else "error", out[-1200:])
            if not ok:
                detail = (out.strip().splitlines() or [""])[-1][:200]
                return {"ok": False, "steps": results,
                        "error": f"step failed: {st['title']}" + (f" — {detail}" if detail else ""),
                        "manual": manual_commands()}
        except (OSError, subprocess.TimeoutExpired) as e:
            results.append({"title": st["title"], "cmd": st["cmd"], "ok": False, "output": str(e)})
            if on_step:
                on_step(i, st["title"], "error", str(e))
            return {"ok": False, "steps": results, "error": str(e), "manual": manual_commands()}
    return {"ok": True, "steps": results, "needs_login": True,
            "note": "Colab CLI installed — now sign in."}


def _looks_installed(out: str) -> bool:
    """`pipx install` over an existing install, or WSL already being there, are not failures."""
    low = out.lower()
    return any(k in low for k in ("already installed", "already exists", "successfully installed",
                                 "installed package", "is already the newest", "upgrade"))


def login_start() -> dict:
    """Start the browser sign-in and return the URL as soon as the CLI prints one.

    `colab sessions` is the cheapest CLI call that requires auth: on a fresh machine it prints the
    Google consent URL (or opens the browser) and waits, so we read it and stop waiting on it."""
    runner = _runner()
    prefix = colab_cmd()
    if prefix is None:
        # nothing to sign in with yet: say so instead of launching a shell that will fail
        return {"error": "Install the Colab CLI first — then sign in.",
                "manual": manual_commands(), "needs_install": True}
    argv = _argv(prefix, ["colab", "sessions"])
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1)
    return {"proc": proc, "note": "Waiting for Google sign-in…"}


def find_url(text: str) -> str:
    """The first https URL in CLI output (the consent page)."""
    import re
    m = re.search(r"https?://[^\s\"'<>]+", text or "")
    return m.group(0).rstrip(".,);") if m else ""


def login_watch(proc, on_url=None, on_line=None, timeout: int = 300) -> dict:
    """Read the login process until it succeeds, prints a URL, or the user closes the browser."""
    import time
    url, lines, t0 = "", [], time.time()
    assert proc.stdout is not None
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line.rstrip())
            if on_line:
                on_line(line.rstrip())
            if not url:
                found = find_url(line)
                if found and ("accounts.google.com" in found or "oauth" in found.lower()):
                    url = found
                    if on_url:
                        on_url(found)
            if proc.poll() is not None:
                break
            if time.time() - t0 > timeout:
                break
    finally:
        rc = proc.poll()
        if rc is None:
            try:
                proc.terminate()
            except OSError:
                pass
        if proc.poll() is None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    out = "\n".join(lines)
    return {"url": url, "returncode": rc, "output": out[-2000:], "ok": rc == 0}


def _argv(prefix: list[str], cmd: list[str]) -> list[str]:
    """Build the argv for a colab command (through WSL bash on Windows).
    `cmd` starts with the program name; the direct prefix replaces it with the resolved path.
    A .bat/.cmd wrapper (pipx / pip console scripts on Windows) can only be launched by
    cmd.exe, so it is run through `cmd /c` instead of being handed to CreateProcess."""
    if prefix and prefix[0] == "wsl":
        return prefix[:-1] + ["-lc", " ".join(cmd)]
    exe = prefix[0]
    if _windows() and exe.lower().endswith((".bat", ".cmd")):
        return ["cmd", "/c", exe] + list(cmd[1:])
    return [exe] + list(cmd[1:])


def quota() -> dict:
    """`colab usage`: compute units / quota information (best effort)."""
    prefix = colab_cmd()
    if prefix is None:
        return {"error": "google-colab-cli not found"}
    try:
        r = subprocess.run(_argv(prefix, ["colab", "usage"]), capture_output=True, text=True, timeout=120)
        return {"returncode": r.returncode, "output": (r.stdout or r.stderr).strip()[-2000:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": str(e)}


def preflight(gpu: str = "T4") -> dict:
    """Everything that must be true before a cloud render, checked up front (offline).

    A Colab run costs minutes and compute units, so the app refuses to start one when a step
    would obviously fail - the user gets the fix instead of a stack trace 3 minutes later."""
    st = status()
    items = []

    def add(state, title, detail, fix=""):
        items.append({"state": state, "title": title, "detail": detail, "fix": fix})

    if st["cli"]:
        add("ok", "Colab CLI", st.get("version") or "installed")
    else:
        add("error", "Colab CLI", "not installed",
            "press Install (one click) or run the commands on the right" if st["can_install"]
            else "run the commands on the right")
    if st["cli"] and not st["ready"]:
        add("error", "Google sign-in", "the CLI is installed but not signed in",
            "press Sign in to Google")
    elif st["ready"]:
        add("ok", "Google sign-in", "signed in")
    if not st["notebook"]:
        add("error", "Render notebook", f"missing: {REPO_NOTEBOOK.name}")
    else:
        add("ok", "Render notebook", "bundled")
    gpus = {g["id"] for g in GPU_CHOICES}
    if gpu not in gpus:
        add("error", "GPU", f"unknown GPU {gpu!r}", "pick " + ", ".join(sorted(gpus)))
    else:
        add("ok", "GPU", gpu)
    if _windows() and not st["wsl"] and not st["cli"]:
        add("warn", "WSL2", "the Colab CLI runs inside WSL2 on Windows",
            "the Install button sets it up (needs a reboot)")
    errors = [i for i in items if i["state"] == "error"]
    return {"ok": not errors, "items": items, "gpu": gpu,
            "errors": len(errors), "warnings": len([i for i in items if i["state"] == "warn"]),
            "fix": " ".join(i["fix"] for i in errors if i["fix"])}


# ---------- job packing ----------
_MEDIA_KEYS = ("background_image", "background_video", "music_path",
               "drawer_picture", "sound_path", "drop_sound", "final_sound")


def _media_files(cfg) -> tuple[list[str], dict]:
    """Every media file the preset references: (files, {config_key: new value for the VM})."""
    files: list[str] = []
    fields: dict = {}

    def packed(p: str) -> str:
        name = Path(p).name
        if p not in files:
            files.append(p)
        return f"media/{name}"

    for key in _MEDIA_KEYS:
        v = getattr(cfg, key, "")
        if isinstance(v, str) and v and Path(v).exists():
            fields[key] = packed(v)
    sounds = []
    for s in (getattr(cfg, "tier_sounds", None) or []):
        if isinstance(s, str) and s and Path(s).exists():
            sounds.append(packed(s))
        else:
            sounds.append(s)
    if sounds:
        fields["tier_sounds"] = sounds
    images = []
    for img in (getattr(cfg, "tier_images", None) or []):
        if isinstance(img, str) and img and Path(img).exists():
            images.append(packed(img))
        else:
            images.append(img)
    if images:
        fields["tier_images"] = images
    folder = getattr(cfg, "tier_image_folder", "")
    if folder and Path(folder).is_dir():
        for f in sorted(Path(folder).glob("**/*")):
            if f.is_file():
                packed(str(f))
        fields["tier_image_folder"] = "media"
    return files, fields


def _repo_files(root: Path) -> list[Path]:
    """The renderer code that must reach the VM (mm911 package, main.py, presets)."""
    out: list[Path] = []
    pkg = root / "mm911"
    if pkg.is_dir():
        out += [p for p in sorted(pkg.rglob("*")) if p.is_file() and p.suffix == ".py"]
        assets = pkg / "assets"
        if assets.is_dir():
            out += [p for p in sorted(assets.rglob("*")) if p.is_file()]
    for name in ("main.py", "requirements.txt"):
        if (root / name).exists():
            out.append(root / name)
    presets = root / "presets"
    if presets.is_dir():
        out += [p for p in sorted(presets.glob("*.json"))]
    return out


def pack_job(cfg, out_zip: str, batch_count: int = 0, extra_files: list[str] | None = None) -> dict:
    """Pack code + preset + media into one zip the notebook unpacks on the VM. All media paths in
    the preset are rewritten to the flat `media/` layout the zip uses."""
    root = Path(__file__).resolve().parent.parent
    media, fields = _media_files(cfg)
    d = cfg.to_dict()
    for k, v in fields.items():
        d[k] = v
    d["seed"] = int(cfg.seed)
    count = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("job/job.json", json.dumps({"action": "batch" if batch_count > 0 else "render",
                                               "count": max(0, int(batch_count))}))
        z.writestr("job/preset.json", json.dumps(d, indent=1))
        for p in _repo_files(root):
            z.write(p, f"job/{p.relative_to(root)}")
            count += 1
        for f in media + list(extra_files or []):
            z.write(f, f"job/media/{Path(f).name}")
            count += 1
    return {"zip": out_zip, "files": count, "media": len(media)}


# ---------- the actual render run ----------
def _run(prefix: list[str] | None, cmd: list[str], timeout: int = 600, check_rc: bool = True) -> str:
    argv = _argv(prefix, cmd) if prefix else cmd
    note("  $ " + " ".join(argv))
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    if check_rc and r.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd)}` failed:\n{out.strip()[-1200:]}")
    return out


def render_on_colab(cfg, out_dir: str, gpu: str = "T4", session: str = SESSION_DEFAULT,
                    batch_count: int = 0, keep_session: bool = False,
                    timeout: int = 60 * 60 * 6) -> dict:
    """One click: pack → rent a GPU → upload → render in the notebook → download → stop."""
    prefix = colab_cmd()
    if prefix is None:
        raise SystemExit(check()["note"])
    if not REPO_NOTEBOOK.exists():
        raise SystemExit(f"missing notebook: {REPO_NOTEBOOK}")
    import tempfile
    out_dir = str(Path(out_dir))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    before = {str(p) for p in Path(out_dir).glob("*.mp4")} | {str(p) for p in Path(out_dir).glob("*.mov")}
    with tempfile.TemporaryDirectory(prefix="mm911_colab_") as tmp:
        job_zip = str(Path(tmp) / "job.zip")
        info = pack_job(cfg, job_zip, batch_count=batch_count)
        note(f"☁️ job packed: {info['files']} files ({info['media']} media) → {gpu}")
        try:
            _run(prefix, ["colab", "new", "-s", session, "--gpu", gpu], timeout=300)
        except RuntimeError as e:
            if "already exists" in str(e).lower():
                _run(prefix, ["colab", "stop", "-s", session], timeout=120, check_rc=False)
                _run(prefix, ["colab", "new", "-s", session, "--gpu", gpu], timeout=300)
            else:
                raise
        try:
            # `colab upload LOCAL REMOTE` is one file per call (no --path flag in the real CLI)
            _run(prefix, ["colab", "upload", "-s", session, job_zip, "/content/job.zip"], timeout=900)
            _run(prefix, ["colab", "upload", "-s", session, str(REPO_NOTEBOOK),
                          "/content/mm911_render.ipynb"], timeout=900)
            note("☁️ rendering on the Colab GPU (this can take a while)...")
            _run(prefix, ["colab", "exec", "-s", session, "-f", str(REPO_NOTEBOOK)], timeout=timeout)
            _run(prefix, ["colab", "download", "-s", session, "/content/output.zip",
                          str(Path(tmp) / "output.zip")], timeout=1800, check_rc=False)
            got = Path(tmp) / "output.zip"
            if got.exists():
                with zipfile.ZipFile(got) as z:
                    for name in z.namelist():
                        if name.lower().endswith((".mp4", ".mov", ".json", ".csv")):
                            z.extract(name, out_dir)
                note(f"⬇️ downloaded {got.stat().st_size / 1e6:.0f} MB from the VM")
        finally:
            if not keep_session:
                _run(prefix, ["colab", "stop", "-s", session], timeout=120, check_rc=False)
    # only what this run actually produced (the output folder holds older videos too)
    vids = sorted(str(p) for p in list(Path(out_dir).glob("*.mp4")) + list(Path(out_dir).glob("*.mov"))
                  if str(p) not in before)
    note(f"✅ {len(vids)} video(s) in {out_dir}")
    return {"videos": vids, "gpu": gpu, "session": session}
