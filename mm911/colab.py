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


def check() -> dict:
    """What the app's status bar shows: ☁️ Colab ready / what is missing."""
    out = {"cli": False, "wsl": False, "notebook": False, "gpu": None, "ready": False, "note": ""}
    prefix = colab_cmd()
    out["wsl"] = _wsl_available() if _windows() else True
    out["notebook"] = REPO_NOTEBOOK.exists()
    if prefix is None:
        out["note"] = ("google-colab-cli not found. On Windows: install WSL2 (wsl --install -d Ubuntu), "
                       "then inside Ubuntu: pipx install google-colab-cli, and sign in with "
                       "`gcloud auth application-default login`.")
        return out
    out["cli"] = True
    argv = _argv(prefix, ["colab", "config", "list"])
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=90)
        txt = (r.stdout + r.stderr).lower()
        if "not authenticated" in txt or "login" in txt and "required" in txt:
            out["note"] = "Colab CLI found, but not signed in. Run: gcloud auth application-default login"
        else:
            out["ready"] = True
            out["note"] = "☁️ Colab ready"
    except (OSError, subprocess.TimeoutExpired) as e:
        out["note"] = f"Colab CLI did not answer: {e}"
    return out


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
            # upload: the CLI moves a folder or file into the session's working dir
            up = Path(tmp) / "upload"
            up.mkdir()
            shutil.copy(job_zip, up / "job.zip")
            shutil.copy(REPO_NOTEBOOK, up / "mm911_render.ipynb")
            _run(prefix, ["colab", "upload", "-s", session, "--path", str(up)], timeout=900)
            note("☁️ rendering on the Colab GPU (this can take a while)...")
            _run(prefix, ["colab", "exec", "-s", session, "-f", "mm911_render.ipynb"], timeout=timeout)
            _run(prefix, ["colab", "download", "-s", session, "--path", "output", "--dest", out_dir],
                 timeout=1800, check_rc=False)
        finally:
            if not keep_session:
                _run(prefix, ["colab", "stop", "-s", session], timeout=120, check_rc=False)
    vids = sorted(str(p) for p in Path(out_dir).glob("**/*.mp4")) + \
        sorted(str(p) for p in Path(out_dir).glob("**/*.mov"))
    note(f"✅ {len(vids)} video(s) in {out_dir}")
    return {"videos": vids, "gpu": gpu, "session": session}
