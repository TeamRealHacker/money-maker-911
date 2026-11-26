"""Money Maker 911 desktop app (pywebview: tiny, uses Windows' built-in Edge WebView2)."""
from __future__ import annotations

import base64
import copy
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import fields
from pathlib import Path

import webview

from ..config import (MergeConfig, PALETTES, SHAPES, HOOKS, APP_NAME, CREDIT, VERSION, LENGTH_PRESETS,
                      EMOJI_SETS, BG_MODES, SIZE_CURVES, PARTICLE_STYLES, SOUND_STRATEGIES,
                      SATISFYING_KEYWORDS, RANDOM_KNOBS, hex_to_rgb, MIN_TIERS, MAX_TIERS, FPS_CHOICES,
                      RESOLUTIONS, QUALITIES, CODECS, ENCODERS, FORMATS, AUDIO_BITRATES)
from .. import audio as _audio
from .. import sounds as myinstants
from ..modes.merge import MergeSim
from ..render import (Renderer, render_video, render_preview_frame, make_thumbnail, prepare_images, make_sim,
                      make_renderer)
from .. import imageprep
from ..batch import run_batch, make_title

# pygame (fonts, surfaces, image codecs) is NOT thread-safe. Every pygame call made from the
# preview thread, the render threads and the JS API threads goes through this one lock.
# Without it the app crashes natively (no Python traceback) as soon as two threads draw at once,
# which is exactly what happened during onboarding: live preview + tier previews + sound pick.
GFX_LOCK = threading.RLock()


def app_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "MoneyMaker911"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _setup_log() -> logging.Logger:
    log = logging.getLogger("mm911")
    if not log.handlers:
        try:
            h = logging.FileHandler(app_dir() / "app.log", encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            log.addHandler(h)
        except OSError:
            pass
        log.setLevel(logging.INFO)
    return log


LOG = _setup_log()


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    p = base / "mm911" / "gui" / "web"
    return p if p.exists() else Path(__file__).resolve().parent / "web"


class Api:
    """Everything public here is callable from JS. Keep all state in _private attributes:
    pywebview recursively inspects every public attribute of the js_api object, and walking into
    the native Window object (or the config) froze / crashed the app on startup on Windows."""

    def __init__(self):
        self._window: webview.Window | None = None
        self._settings_path = app_dir() / "settings.json"
        self._save_lock = threading.Lock()
        self._settings = self._load_settings()
        self._cfg = MergeConfig.from_dict(self._settings.get("config", {}))
        self._preview_on = False
        self._signin = {"running": False, "url": "", "error": "", "done": False}
        self._uploading = False
        self._plan_edits = {}
        self._preview_dirty = True
        self._busy = False
        self._stop = False
        self._frame: tuple[str, int, float] | None = None   # latest preview frame (b64, tier, t)
        self._frame_id = 0
        self._sounds = deque(maxlen=48)   # preview sound events for the page to play
        self._pthread: threading.Thread | None = None
        self._prep_lock = threading.Lock()     # one image-prep run at a time
        self._prep_note = ""
        self._prep_busy = False

    # ---------- settings ----------
    def _load_settings(self) -> dict:
        defaults = {"onboarded": False, "output_dir": str(Path.home() / "Videos" / "MoneyMaker911")}
        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**defaults, **data}
        except FileNotFoundError:
            pass
        except Exception as e:
            LOG.warning("settings.json unreadable, starting fresh: %s", e)
        return defaults

    def _save(self):
        """Atomic, thread-safe save (several JS calls can save at the same moment)."""
        with self._save_lock:
            try:
                self._settings["config"] = self._cfg.to_dict()
                tmp = self._settings_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._settings, indent=2), encoding="utf-8")
                os.replace(tmp, self._settings_path)
            except Exception as e:
                LOG.error("could not save settings: %s", e)

    def bootstrap(self) -> dict:
        return {"app": APP_NAME, "credit": CREDIT, "version": VERSION, "config": self._cfg.to_dict(),
                "palettes": {k: v for k, v in PALETTES.items()}, "shapes": SHAPES, "hooks": HOOKS,
                "lengths": LENGTH_PRESETS, "emoji_sets": EMOJI_SETS, "cutout": imageprep.status(),
                "bg_modes": BG_MODES, "size_curves": SIZE_CURVES, "particle_styles": PARTICLE_STYLES,
                "sound_strategies": SOUND_STRATEGIES, "keywords": SATISFYING_KEYWORDS, "random_knobs": RANDOM_KNOBS,
                "themes": self.list_themes(),
                "onboarded": self._settings.get("onboarded", False),
                "min_tiers": MIN_TIERS, "max_tiers": MAX_TIERS,
                "export": {"fps": FPS_CHOICES, "resolutions": list(RESOLUTIONS), "qualities": list(QUALITIES),
                           "codecs": CODECS, "encoders": ENCODERS, "formats": FORMATS,
                           "audio_bitrates": AUDIO_BITRATES},
                "output_dir": self._settings.get("output_dir")}

    def finish_onboarding(self, choices: dict) -> bool:
        choices = choices or {}
        self._settings["onboarded"] = True
        if choices.get("palette") in PALETTES:
            self._cfg.palette = choices["palette"]
        if choices.get("tiers"):
            try:
                self._cfg.tiers = max(MIN_TIERS, min(MAX_TIERS, int(choices["tiers"])))
            except (TypeError, ValueError):
                pass
        if str(choices.get("theme_name") or "").strip():
            self._cfg.theme_name = str(choices["theme_name"]).strip()[:40]
        self._preview_dirty = True
        self._save()
        return True

    def set_config(self, patch: dict) -> dict:
        names = {f.name: f.type for f in fields(MergeConfig)}
        for k, v in (patch or {}).items():
            if k in names:
                cur = getattr(self._cfg, k)
                try:
                    if isinstance(cur, bool):
                        v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
                    elif isinstance(cur, int):
                        v = int(round(float(v)))
                    elif isinstance(cur, float):
                        v = float(v)
                    elif isinstance(cur, str):
                        v = "" if v is None else str(v)
                    elif isinstance(cur, list) and not isinstance(v, list):
                        continue
                except (TypeError, ValueError):
                    continue  # ignore bad values instead of storing garbage that crashes the renderer
                if k == "tiers":
                    v = max(MIN_TIERS, min(MAX_TIERS, v))
                setattr(self._cfg, k, v)
        self._cfg.sanitize_export()
        try:
            self._cfg.clamp()
        except (TypeError, ValueError):
            pass
        self._preview_dirty = True
        self._save()
        return self._cfg.to_dict()

    def reset_config(self) -> dict:
        self._cfg = MergeConfig()
        self._preview_dirty = True
        self._save()
        return self._cfg.to_dict()

    # ---------- files ----------
    def pick_file(self, kind: str) -> str:
        types = {"sound": ("Audio (*.mp3;*.wav;*.ogg;*.m4a;*.aac;*.flac;*.opus;*.mp4)",),
                 "image": ("Images (*.png;*.jpg;*.jpeg;*.webp)",),
                 "video": ("Videos (*.mp4;*.mov;*.webm;*.mkv;*.gif)",),
                 "font": ("Fonts (*.ttf;*.otf)",),
                 "midi": ("MIDI (*.mid;*.midi)",),
                 "theme": ("Theme / preset (*.json)",)}.get(kind, ("All files (*.*)",))
        try:
            res = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=types)
        except Exception as e:
            LOG.error("file dialog failed: %s", e)
            return ""
        return res[0] if res else ""

    def pick_images(self) -> list[str]:
        res = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                             file_types=("Images (*.png;*.jpg;*.jpeg;*.webp)",))
        files = sorted(res or [])
        if not files:
            return self._cfg.tier_images
        if len(files) >= MIN_TIERS:  # your pictures decide how many forms there are
            self._cfg.tiers = min(MAX_TIERS, len(files))
        self._cfg.tier_images = files[:40]   # extras fill in when "skip images with text" drops some
        self._cfg.tier_image_folder = ""
        self._preview_dirty = True
        self._save()
        return self._cfg.tier_images

    def pick_tier_image(self, i: int) -> list[dict]:
        """Choose (or replace) the picture for ONE form. Works with photos of yourself, memes, anything."""
        i = int(i)
        try:
            res = self._window.create_file_dialog(webview.FileDialog.OPEN,
                                                  file_types=("Images (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif)",))
        except Exception as e:
            LOG.error("file dialog failed: %s", e)
            res = None
        if res:
            imgs = list(self._cfg.resolved_tier_images())   # folder mode -> explicit list so one can be swapped
            while len(imgs) <= i:
                imgs.append("")
            imgs[i] = res[0]
            self._cfg.tier_images = imgs[: self._cfg.tiers]
            self._cfg.tier_image_folder = ""
            self._preview_dirty = True
            self._save()
        return self.tier_previews()

    def clear_tier_image(self, i: int) -> list[dict]:
        i = int(i)
        imgs = list(self._cfg.resolved_tier_images())
        if i < len(imgs):
            imgs[i] = ""
            while imgs and not imgs[-1]:
                imgs.pop()
            self._cfg.tier_images, self._cfg.tier_image_folder = imgs, ""
            self._preview_dirty = True
            self._save()
        return self.tier_previews()

    def pick_image_folder(self) -> list[dict]:
        res = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if res:
            self._cfg.tier_image_folder = res[0]
            n = len(MergeConfig(tier_image_folder=res[0], tiers=MAX_TIERS).resolved_tier_images())
            if n >= MIN_TIERS:
                self._cfg.tiers = min(MAX_TIERS, n)
            self._preview_dirty = True
            self._save()
        return self.tier_previews()

    # ---------- per-tier editor ----------
    def tier_previews(self) -> list[dict]:
        """One row per tier: circle-cropped preview (exactly how it renders), name, colour, emoji, image."""
        import io
        import pygame
        cfg = copy.deepcopy(self._cfg)
        with GFX_LOCK:
            return self._tier_rows(cfg, io, pygame)

    def _tier_rows(self, cfg, io, pygame) -> list[dict]:
        try:
            rend = Renderer(cfg, scale=0.25)
        except Exception as e:
            LOG.exception("tier preview failed: %s", e)
            return []
        prep = imageprep.tier_images(cfg)   # cached results only, never blocks on AI
        imgs, cut = prep["sources"], prep["images"]
        rows = []
        for t in range(cfg.tiers):
            spr = rend.icon(t, 96)   # built at the shown size (crisp on HiDPI), not shrunk from a sprite
            buf = io.BytesIO()
            pygame.image.save(spr, buf, "p.png")
            col = rend._tier_color(t)
            rows.append({"i": t, "png": base64.b64encode(buf.getvalue()).decode(),
                         "name": cfg.tier_value("tier_names", t),
                         "color": "#%02X%02X%02X" % col, "custom_color": bool(cfg.tier_value("tier_colors", t)),
                         "emoji": cfg.tier_value("tier_emojis", t),
                         "image": Path(imgs[t]).name if t < len(imgs) else "",
                         "cut": t < len(cut) and imageprep.is_cutout(cut[t])})
        return rows

    # ---------- AI cut-outs + text check ----------
    def prepare_images(self) -> dict:
        """Runs the text check and cut-outs for the current tier images (downloads the model once).
        Called by the page after image settings change; pywebview runs it on its own thread, and the
        page polls prep_status() for the progress line. Inference runs outside GFX_LOCK."""
        with self._prep_lock:
            self._prep_busy = True
            cfg = copy.deepcopy(self._cfg)
            try:
                res = prepare_images(cfg, lock=GFX_LOCK, note=self._set_note)
            except Exception as e:
                LOG.exception("image prep failed")
                res = {"images": [], "skipped": [], "cut": 0, "errors": [str(e)]}
            finally:
                self._prep_busy, self._prep_note = False, ""
            self._preview_dirty = True
            return {"images": len(res.get("images", [])), "skipped": res.get("skipped", []),
                    "cut": res.get("cut", 0), "errors": res.get("errors", [])[:3],
                    "status": imageprep.status()}

    def _set_note(self, msg: str) -> None:
        self._prep_note = msg

    def prep_status(self) -> dict:
        return {"busy": self._prep_busy, "note": self._prep_note}

    def set_tier(self, i: int, key: str, value: str) -> list[dict]:
        attr = {"name": "tier_names", "color": "tier_colors", "emoji": "tier_emojis"}.get(key)
        if attr is None:
            return self.tier_previews()
        lst = list(getattr(self._cfg, attr))
        while len(lst) <= int(i):
            lst.append("")
        value = (value or "").strip()
        if key == "color" and value:
            try:
                hex_to_rgb(value)
            except ValueError:
                value = ""
        lst[int(i)] = value
        while lst and not lst[-1]:
            lst.pop()
        setattr(self._cfg, attr, lst)
        self._preview_dirty = True
        self._save()
        return self.tier_previews()

    def apply_emoji_set(self, name: str) -> list[dict]:
        self._cfg.tier_emojis = list(EMOJI_SETS.get(name, []))[: self._cfg.tiers] if name else []
        if name:
            self._cfg.theme_name = name
        self._preview_dirty = True
        self._save()
        return self.tier_previews()

    def clear_tiers(self) -> list[dict]:
        self._cfg.tier_names, self._cfg.tier_colors, self._cfg.tier_emojis = [], [], []
        self._cfg.tier_images, self._cfg.tier_image_folder = [], ""
        self._preview_dirty = True
        self._save()
        return self.tier_previews()

    def save_thumbnail(self) -> str:
        out = Path(self._settings["output_dir"]) / f"thumb_{int(time.time())}.jpg"
        try:
            with GFX_LOCK:
                make_thumbnail(copy.deepcopy(self._cfg), str(out))
        except Exception as e:
            LOG.exception("thumbnail failed")
            return "error: " + str(e)
        return str(out)

    def pick_folder(self) -> str:
        res = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if res:
            self._settings["output_dir"] = res[0]
            self._save()
            return res[0]
        return self._settings.get("output_dir", "")

    def open_output(self) -> None:
        self._open_path(Path(self._settings.get("output_dir")))

    def _open_path(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            LOG.error("open folder failed: %s", e)

    # ---------- preflight (would this render fail?) ----------
    def preflight(self) -> dict:
        """Offline check of the current settings; the app shows it above the Render button."""
        from .. import preflight as _pf
        from ..ffmpeg import ffmpeg_exe
        try:
            ff_ok = bool(ffmpeg_exe())
        except Exception:
            ff_ok = False
        try:
            res = _pf.check(self._cfg, self._settings.get("output_dir", ""), ffmpeg_ok=ff_ok)
        except Exception as e:                       # never let a check block rendering
            LOG.error("preflight failed: %s", e)
            return {"items": [], "errors": 0, "warnings": 0, "ready": True, "summary": ""}
        res["summary"] = _pf.summary(res)
        return res

    # ---------- update center ----------
    def update_check(self) -> dict:
        """Is a newer build out? Runs on its own thread from JS (never blocks the UI)."""
        from .. import updates
        try:
            res = updates.check()
        except Exception as e:
            LOG.error("update check failed: %s", e)
            res = {"current": VERSION, "latest": "", "newer": False, "error": str(e)}
        res["notes"] = updates.changelog(res.get("notes", ""))
        return res

    def update_download(self) -> dict:
        """Fetch the newest .exe into the app folder (returns the path for update_install)."""
        from .. import updates
        info = updates.check()
        if info.get("error") or not info.get("newer"):
            return {"error": info.get("error") or "already up to date"}
        asset = next((a for a in info.get("assets") or [] if a["name"].lower().endswith(".exe")), None)
        if not asset:
            if info.get("url"):
                self._open_url(info["url"])
            return {"error": "this release has no .exe - opening the release page"}
        dest = app_dir() / "updates" / asset["name"]
        got = updates.download(asset["url"], str(dest))
        if got.get("error"):
            return got
        return {"file": got["file"], "size": got["size"], "version": info.get("latest", "")}

    def update_install(self, file: str = "") -> dict:
        """Swap the running .exe for the downloaded one and restart the app."""
        from .. import updates
        res = updates.install(file) if file else {"error": "download the update first"}
        if res.get("ok"):
            if self._window is not None:
                try:
                    self._window.destroy()
                except Exception:
                    pass
        return res

    def open_url(self, url: str) -> None:
        self._open_url(str(url or ""))

    def _open_url(self, url: str) -> None:
        """Open a link in the user's browser (only http/https, never a local path)."""
        if not re.match(r"^https?://", url or "", re.I):
            return
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            LOG.error("open url failed: %s", e)

    # ---------- sounds (Myinstants) ----------
    def sound_search(self, query: str) -> dict:
        """Search Myinstants. Returns {"results": [{name, mp3_url, page_url}], "error": ""}."""
        try:
            res = myinstants.search(str(query or ""))
            return {"results": [r.to_dict() for r in res[:60]], "error": ""}
        except Exception as e:
            LOG.warning("sound search failed: %s", e)
            return {"results": [], "error": "Myinstants not reachable (offline?). The built-in pop still works."}

    def sound_use(self, mp3_url: str, target: str = "all") -> dict:
        """Download (once) and use a sound. target: all | drop | final | tier:N"""
        try:
            path = myinstants.download(myinstants.SoundResult("", mp3_url) if mp3_url.endswith(".mp3")
                                       else mp3_url)
        except Exception as e:
            LOG.warning("sound download failed: %s", e)
            return {"error": "Download failed: " + str(e), "rows": self.sound_rows()}
        self._assign_sound(path, target)
        return {"error": "", "rows": self.sound_rows(), "config": self._cfg.to_dict()}

    def _assign_sound(self, path: str, target: str) -> None:
        c = self._cfg
        if target == "drop":
            c.drop_sound = path
        elif target == "final":
            c.final_sound = path
        elif str(target).startswith("tier:"):
            i = int(str(target).split(":")[1])
            lst = list(c.tier_sounds)
            while len(lst) <= i:
                lst.append("")
            lst[i] = path
            c.tier_sounds = lst
        else:  # one sound for every tier, auto pitched up
            c.sound_path, c.tier_sounds, c.tier_semitones = path, [], []
        c.auto_sounds = False
        self._preview_dirty = True
        self._save()

    def pick_sound_for(self, target: str) -> dict:
        f = self.pick_file("sound")
        if f:
            self._assign_sound(f, target)
        return {"rows": self.sound_rows(), "config": self._cfg.to_dict()}

    def sound_auto_fill(self, keywords: str = "", strategy: str = "", count: int = 0) -> dict:
        """Pick sounds automatically and lay them out low -> high pitch across the tiers."""
        c = self._cfg
        if strategy in SOUND_STRATEGIES:
            c.auto_sound_strategy = strategy
        if count:
            c.auto_sound_count = max(1, min(12, int(count)))
        try:
            plan = myinstants.auto_plan(keywords or c.auto_sound_keywords, c.tiers, c.auto_sound_strategy,
                                        c.auto_sound_count, c.auto_sound_separate, c.auto_drop_keyword,
                                        c.auto_final_keyword, c.pitch_step, c.seed)
        except Exception as e:
            LOG.warning("auto fill failed: %s", e)
            return {"error": "Auto fill failed: " + str(e), "rows": self.sound_rows(), "config": c.to_dict()}
        if not (plan["sound_path"] or plan["tier_sounds"]):
            return {"error": "Nothing found (offline?). Keeping the current sounds.", "rows": self.sound_rows(),
                    "config": c.to_dict()}
        myinstants.apply_plan(c, plan)
        c.auto_sounds = False   # fixed sounds now; tick "new sounds every render" to fetch per video
        self._save()
        return {"error": "", "rows": self.sound_rows(), "config": c.to_dict(),
                "picked": [s["name"] for s in plan["sounds"]]}

    def sound_rows(self) -> list[dict]:
        """One row per tier + drop + final: which sound, which pitch (auto or manual)."""
        c = self._cfg
        names = {v["path"]: v["name"] for v in myinstants.cached_sounds()}
        label = lambda p: (names.get(p) or Path(p).stem) if p else "Built-in pop"
        rows = []
        for t in range(c.tiers):
            p = c.tier_value("tier_sounds", t) or c.sound_path
            manual = t < len(c.tier_semitones) and c.tier_semitones[t] not in (None, "")
            rows.append({"key": f"tier:{t}", "label": f"{t + 1}", "sound": label(p),
                         "own": bool(c.tier_value("tier_sounds", t)),
                         "pitch": round(c.tier_pitch(t), 2), "manual": manual})
        rows.append({"key": "drop", "label": "Drop", "sound": label(c.drop_sound) if c.drop_sound else "same as tier",
                     "own": bool(c.drop_sound), "pitch": c.drop_pitch, "manual": True})
        rows.append({"key": "final", "label": "Final", "sound": label(c.final_sound) if c.final_sound else "top tier",
                     "own": bool(c.final_sound), "pitch": c.final_pitch, "manual": True})
        return rows

    def set_sound_pitch(self, key: str, value) -> list[dict]:
        """Manual pitch (semitones). Empty value = back to auto for tiers."""
        c = self._cfg
        try:
            v = None if value in (None, "") else max(-24.0, min(24.0, float(value)))
        except (TypeError, ValueError):
            v = None
        if key == "drop":
            c.drop_pitch = -4.0 if v is None else v
        elif key == "final":
            c.final_pitch = 7.0 if v is None else v
        elif key.startswith("tier:"):
            i = int(key.split(":")[1])
            lst = list(c.tier_semitones)
            while len(lst) <= i:
                lst.append(None)
            lst[i] = v
            while lst and lst[-1] in (None, ""):
                lst.pop()
            c.tier_semitones = lst
        self._save()
        return self.sound_rows()

    def clear_sound(self, key: str) -> dict:
        c = self._cfg
        if key == "drop":
            c.drop_sound = ""
        elif key == "final":
            c.final_sound = ""
        elif key.startswith("tier:"):
            i = int(key.split(":")[1])
            if i < len(c.tier_sounds):
                lst = list(c.tier_sounds)
                lst[i] = ""
                while lst and not lst[-1]:
                    lst.pop()
                c.tier_sounds = lst
        else:  # everything back to the built-in pop
            c.sound_path, c.tier_sounds, c.tier_semitones, c.drop_sound, c.final_sound = "", [], [], "", ""
            c.auto_sounds = False
        self._save()
        return {"rows": self.sound_rows(), "config": c.to_dict()}

    def preview_sound(self, key: str) -> str:
        """Exactly what that tier / drop / final will sound like (pitched), as a data: URL."""
        from ..audio import SoundBank, to_wav_bytes, pitch
        try:
            bank = SoundBank(copy.deepcopy(self._cfg))
            if key == "drop":
                smp, semis, _ = bank.event("drop", 0)
            elif key == "final":
                smp, semis, _ = bank.event("final", self._cfg.tiers - 1)
            else:
                smp, semis, _ = bank.event("merge", int(str(key).split(":")[1]))
            return "data:audio/wav;base64," + base64.b64encode(to_wav_bytes(pitch(smp, semis))).decode()
        except Exception as e:
            LOG.warning("sound preview failed: %s", e)
            return ""

    # ---------- 📤 publish studio (YouTube) ----------
    def _publish_settings(self) -> dict:
        from .. import autoupload
        return autoupload.settings(self._settings.get("publish"))

    def _set_publish_settings(self, patch: dict) -> dict:
        from .. import autoupload
        cur = dict(self._settings.get("publish") or {})
        cur.update(patch or {})
        self._settings["publish"] = autoupload.settings(cur)
        self._save()
        return self._settings["publish"]

    def publish_status(self) -> dict:
        """Everything the studio card needs: deps, client secret, sign-in, auto-upload."""
        from .. import publish as pb
        deps = pb.has_google_deps()
        secret = pb.find_client_secret()
        token = pb.token_file()
        st = self._publish_settings()
        out = {"deps": deps, "client_secret": secret, "signed_in": token.exists(),
               "channel": "", "thumb": "", "error": "",
               "settings": st, "pip": "pip install google-api-python-client google-auth-oauthlib",
               "console_url": "https://console.cloud.google.com/apis/credentials",
               "folder": self._settings.get("output_dir", "")}
        if deps and out["signed_in"]:
            acc = pb.account_info(token_path=str(token))
            out.update(channel=acc.get("channel", ""), thumb=acc.get("thumb", ""),
                       error=acc.get("error", ""), signed_in=acc.get("signed_in", out["signed_in"]))
        return out

    def publish_add_secret(self) -> dict:
        """Copy the user's client_secret*.json into the app folder (never the repo)."""
        from .. import publish as pb
        res = self._window.create_file_dialog(webview.FileDialog.OPEN,
                                              file_types=("JSON (*.json)", "All files (*.*)"))
        if not res:
            return {"cancelled": True}
        src = Path(res[0] if isinstance(res, (list, tuple)) else res)
        try:
            if src.suffix.lower() != ".json" or src.stat().st_size > 512 * 1024:
                return {"error": "pick the client_secret .json Google gave you"}
            dest = pb._app_dir() / "client_secret.json"
            shutil.copyfile(src, dest)
            return {"file": str(dest)}
        except OSError as e:
            return {"error": f"could not read that file ({e})"}

    def publish_sign_in(self) -> dict:
        """Start Google sign-in on a worker thread; JS polls publish_signin_progress()."""
        from .. import publish as pb
        if self._signin["running"]:
            return {"running": True}
        if not pb.has_google_deps():
            return {"error": "install the Google libraries first",
                    "pip": pb.check_api().get("pip", "")}
        if not pb.find_client_secret():
            return {"error": "add your client_secret.json first"}
        self._signin.update(running=True, url="", error="", done=False)

        def work():
            try:
                pb.sign_in(on_url=lambda u: self._signin.update(url=u))
                self._signin["done"] = True
            except BaseException as e:       # SystemExit from the Google libs included
                self._signin["error"] = str(e)[:400]
            finally:
                self._signin["running"] = False
        threading.Thread(target=work, daemon=True).start()
        return {"running": True}

    def publish_signin_progress(self) -> dict:
        return dict(self._signin)

    def publish_sign_out(self) -> dict:
        from .. import publish as pb
        return pb.sign_out()

    def publish_plan(self) -> dict:
        """What would be uploaded from the output folder right now (never uploads)."""
        from .. import publish as pb
        from .. import autoupload
        folder = self._settings.get("output_dir", "")
        rows = autoupload.rows_from_folder(folder)
        if not rows:
            return {"plan": [], "summary": "Nothing rendered yet", "todo": 0, "skipped": []}
        st = self._publish_settings()
        csv_path = Path(folder) / "titles.csv"
        if csv_path.exists():
            plan = pb.queue_plan(str(csv_path), folder=folder, spread_days=int(st["spread_days"]),
                                 times=str(st["times"]), privacy=str(st["privacy"]))
        else:
            plan = autoupload.after_render(folder, {**st, "enabled": True})["plan"]
        for item in plan:                     # never offer an already-uploaded video again
            item["uploaded"] = autoupload.already_uploaded(folder, item.get("video", ""))
        todo = [p for p in plan if not p["uploaded"]]
        q = pb.quota(autoupload.uploaded_today(folder))
        summary = f"{len(todo)} ready to upload"
        if len(todo) > q["left"]:
            summary += f" · only {q['left']} fit in today's YouTube quota"
        return {"plan": plan, "summary": summary, "folder": folder,
                "skipped": [], "todo": len(todo), "quota": q}

    def publish_update_plan(self, index: int, patch: dict) -> dict:
        """Edit one row of the plan (title / description / privacy / publish time)."""
        edits = getattr(self, "_plan_edits", None) or {}
        row = edits.setdefault(int(index), {})
        for k in ("title", "description", "privacy", "publish_at", "tags"):
            if k in (patch or {}):
                v = patch[k]
                row[k] = [t.strip() for t in str(v).split(",") if t.strip()] if k == "tags" else str(v)
        self._plan_edits = edits
        return {"ok": True}

    def publish_upload(self, plan: list | None = None) -> bool:
        """Upload the plan on a worker thread; progress goes to the normal progress bar."""
        from .. import publish as pb
        from .. import autoupload
        if self._uploading:
            return False
        if not pb.has_google_deps():
            self._emit({"pubdone": True, "error": "install the Google libraries first"})
            return False
        if not pb.token_file().exists():
            self._emit({"pubdone": True, "error": "sign in to YouTube first"})
            return False
        items = plan if plan else self.publish_plan()["plan"]
        edits = getattr(self, "_plan_edits", None) or {}
        queue = []
        for i, item in enumerate(items):
            if item.get("uploaded"):
                continue
            merged = dict(item)
            merged.update(edits.get(i, {}))
            if merged.get("publish_at"):
                merged["privacy"] = "private"      # scheduled uploads must start private
            queue.append(merged)
        if not queue:
            self._emit({"pubdone": True, "results": [], "note": "nothing to upload"})
            return False
        self._uploading = True
        folder = self._settings.get("output_dir", "")

        def work():
            n, results = len(queue), []
            try:
                for i, item in enumerate(queue):
                    self._emit({"pub": True, "i": i, "n": n, "p": 0, "title": item.get("title", "")})
                    try:
                        res = pb.upload_video(item["video"], item.get("title", ""),
                                              item.get("description", ""), item.get("tags"),
                                              item.get("privacy", "private"),
                                              item.get("publish_at", ""),
                                              client_secret=pb.find_client_secret() or "client_secret.json",
                                              token_path=str(pb.token_file()))
                        autoupload.save_receipt(folder, item["video"], res)
                        results.append({**res, "video": item["video"], "title": item.get("title", "")})
                        self._emit({"pub": True, "i": i, "n": n, "p": 1})
                    except BaseException as e:      # one bad video must not stop the queue
                        LOG.exception("upload failed")
                        results.append({"video": item.get("video", ""), "error": str(e)[:300]})
                self._emit({"pubdone": True, "results": results,
                            "note": f"{len([r for r in results if not r.get('error')])} uploaded"})
            finally:
                self._uploading = False
        threading.Thread(target=work, daemon=True).start()
        return True

    def publish_open_url(self, url: str) -> None:
        self._open_url(url)

    def _auto_upload_after_batch(self) -> None:
        """Called when a batch finishes: queue the new videos if the user asked for that."""
        from .. import autoupload
        st = self._publish_settings()
        if not st.get("enabled") or not st.get("after_batch"):
            return
        folder = self._settings.get("output_dir", "")
        plan = autoupload.after_render(folder, st)
        self._emit({"autoupload": {"queued": len(plan["plan"]),
                                   "note": autoupload.summary(plan)}})
        if plan["plan"]:
            self.publish_upload(plan["plan"])

    # ---------- themes: save / load / import / export ----------
    def _themes_dir(self) -> Path:
        d = app_dir() / "themes"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_themes(self) -> list[str]:
        return sorted(p.stem for p in self._themes_dir().glob("*.json"))

    def save_theme(self, name: str) -> list[str]:
        safe = "".join(ch for ch in str(name or "").strip() if ch.isalnum() or ch in " -_")[:40].strip()
        if safe:
            self._cfg.save(self._themes_dir() / f"{safe}.json")
        return self.list_themes()

    def load_theme(self, name: str) -> dict:
        p = self._themes_dir() / f"{name}.json"
        if p.exists():
            try:
                self._cfg = MergeConfig.load(p).clamp()
                self._preview_dirty = True
                self._save()
            except Exception as e:
                LOG.error("theme load failed: %s", e)
        return self._cfg.to_dict()

    def delete_theme(self, name: str) -> list[str]:
        p = self._themes_dir() / f"{name}.json"
        try:
            p.unlink()
        except OSError:
            pass
        return self.list_themes()

    def export_theme(self) -> str:
        try:
            res = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=f"{self._cfg.theme_name}_theme.json",
                                                 file_types=("Theme (*.json)",))
        except Exception as e:
            LOG.error("save dialog failed: %s", e)
            return ""
        path = res if isinstance(res, str) else (res[0] if res else "")
        if path:
            self._cfg.save(path)
        return path or ""

    def import_theme(self) -> dict:
        f = self.pick_file("theme")
        if f:
            try:
                self._cfg = MergeConfig.load(f).clamp()
                self._preview_dirty = True
                self._save()
            except Exception as e:
                LOG.error("theme import failed: %s", e)
                return {"error": str(e), "config": self._cfg.to_dict()}
        return {"error": "", "config": self._cfg.to_dict()}

    # ---------- live preview ----------
    # The old version pushed every frame into the page with evaluate_js() 30x a second. evaluate_js
    # blocks on the UI thread, so the window (and the onboarding buttons) stuttered and froze.
    # Now the preview thread only renders into a buffer and the page pulls the newest frame when
    # it is ready for one (requestAnimationFrame), so the UI can never be flooded.
    def preview(self, on: bool) -> None:
        self._preview_on = bool(on)
        if self._preview_on and (self._pthread is None or not self._pthread.is_alive()):
            self._pthread = threading.Thread(target=self._preview_loop, daemon=True, name="preview")
            self._pthread.start()

    def preview_size(self, px_height: int) -> None:
        """The page reports the preview's real pixel height (HiDPI aware); frames render at that size."""
        try:
            px = int(px_height)
        except (TypeError, ValueError):
            return
        if px > 0 and abs(px - getattr(self, "_preview_px", 0)) > 8:
            self._preview_px = px
            self._preview_dirty = True

    def _preview_scale(self) -> float:
        px = getattr(self, "_preview_px", 0) or 690
        return max(0.3, min(0.75, px / self._cfg.height))

    def restart_preview(self) -> None:
        self._cfg.seed += 1
        self._preview_dirty = True

    def get_frame(self, last_id: int = 0):
        """Newest preview frame, or None when nothing new since last_id."""
        f = self._frame
        if f is None or self._frame_id == last_id:
            return None
        snd = []
        while self._sounds:
            try:
                snd.append(self._sounds.popleft())
            except IndexError:
                break
        return {"id": self._frame_id, "jpg": f[0], "tier": f[1], "t": f[2], "snd": snd}

    # ---------- listen to your sound ----------
    def sound_sample(self, kind: str = "sound") -> str:
        """Audio for the page as a data URL. kind: 'sound' (the raw pop, used for live preview sound),
        'demo' (how it will sound in a video: drops, rising merges, final), 'music' (first 30 s)."""
        try:
            c = self._cfg
            if kind == "music":
                data = _audio.load_music(c.music_path, 30) * float(c.music_volume or 0.25) * 2
                if data.size == 0:
                    return ""
            elif kind == "demo":
                data = _audio.demo_track(_audio.load_sound(c.sound_path), min(1.0, float(c.sound_volume)))
            else:
                data = _audio.load_sound(c.sound_path)
            return "data:audio/wav;base64," + base64.b64encode(_audio.wav_bytes(data)).decode()
        except Exception:
            LOG.exception("sound preview failed")
            return ""

    def _preview_loop(self):
        sim = rend = cfg = None
        fps = 30
        while True:
            if not self._preview_on or self._busy:
                time.sleep(0.1)
                continue
            t0 = time.time()
            try:
                if self._preview_dirty or sim is None or sim.done:
                    if sim is not None and sim.done and not self._preview_dirty:
                        time.sleep(0.8)  # let the ending breathe before the next run
                        self._cfg.seed += 1
                    self._preview_dirty = False
                    # snapshot: the UI can change the live config at any time; the sim/renderer must
                    # never see half-applied changes (e.g. tiers going 9 -> 11 crashed the old loop).
                    cfg = copy.deepcopy(self._cfg)
                    with GFX_LOCK:
                        sim, rend = make_sim(cfg), make_renderer(cfg, scale=self._preview_scale())
                    ev_seen, last_drop = 0, -1.0
                    self._sounds.clear()
                sim.step(1 / fps)
                # hand new sound events to the page (it plays them pitched, like the export)
                for ev in sim.events[ev_seen:]:
                    if ev.kind == "drop" and (not cfg.drop_sounds or ev.t - last_drop < 0.12):
                        continue
                    if ev.kind == "drop":
                        last_drop = ev.t
                    self._sounds.append([ev.kind, ev.tier])
                ev_seen = len(sim.events)
                with GFX_LOCK:
                    jpg = render_preview_frame(cfg, sim, rend)
                self._frame = (base64.b64encode(jpg).decode(), sim.best_tier + 1, round(sim.t, 1))
                self._frame_id += 1
            except Exception:
                # never let the preview thread die (that was the "stuck preview" bug)
                LOG.exception("preview frame failed, rebuilding")
                sim = None
                time.sleep(0.5)
                continue
            time.sleep(max(0.0, 1 / fps - (time.time() - t0)))

    # ---------- rendering ----------
    def _emit(self, payload: dict):
        now = time.time()
        if not (payload.get("done") or payload.get("error")) and now - getattr(self, "_last_emit", 0) < 0.25:
            return  # max 4 progress updates/s, evaluate_js is expensive
        self._last_emit = now
        try:
            self._window.evaluate_js(f"window.mm.progress({json.dumps(payload)})")
        except Exception:
            pass

    def render_one(self) -> bool:
        if self._busy:
            return False
        self._busy, self._stop = True, False

        def work():
            try:
                out = Path(self._settings["output_dir"]) / f"{self._cfg.mode}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
                cfg = copy.deepcopy(self._cfg)
                meta = render_video(cfg, str(out), progress=lambda p: self._emit({"i": 0, "n": 1, "p": p}),
                                    lock=GFX_LOCK)
                meta["title"] = make_title(cfg)
                self._emit({"done": True, "results": [meta]})
                if cfg.open_folder_after:
                    self.open_output()
            except Exception as e:  # pragma: no cover
                LOG.exception("render failed")
                self._emit({"error": str(e)})
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()
        return True

    def render_batch(self, count: int, randomize: bool, only_wins: bool) -> bool:
        if self._busy:
            return False
        self._busy, self._stop = True, False

        def work():
            try:
                res = run_batch(copy.deepcopy(self._cfg), max(1, min(500, int(count))), self._settings["output_dir"],
                                randomize, only_wins,
                                progress=lambda i, n, p: self._emit({"i": i, "n": n, "p": p}),
                                stop=lambda: self._stop, lock=GFX_LOCK)
                self._emit({"done": True, "results": res})
                if self._cfg.open_folder_after:
                    self.open_output()
                self._auto_upload_after_batch()
            except Exception as e:  # pragma: no cover
                LOG.exception("render failed")
                self._emit({"error": str(e)})
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()
        return True

    def stop(self) -> None:
        self._stop = True


def main() -> None:
    api = Api()
    web = web_dir()
    splash = webview.create_window("Money Maker 911", url=str(web / "splash.html"), width=520, height=360,
                                   frameless=True, easy_drag=False, resizable=False, on_top=True,
                                   background_color="#0E0E12")
    main_win = webview.create_window(APP_NAME, url=str(web / "index.html"), js_api=api, width=1360,
                                     height=860, min_size=(1100, 720), background_color="#F5F5F7",
                                     hidden=True)
    api._window = main_win

    def boot():
        # show the main window once its page has loaded (not after a fixed sleep), then drop the splash
        main_win.events.loaded.wait(15)
        time.sleep(0.4)
        try:
            main_win.show()
        finally:
            try:
                splash.destroy()
            except Exception:
                pass

    def on_closed():
        api._preview_on = False
        api._stop = True

    main_win.events.closed += on_closed
    webview.start(boot, http_server=True, debug=bool(os.environ.get("MM911_DEBUG")))


if __name__ == "__main__":
    main()
