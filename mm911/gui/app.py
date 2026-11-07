"""Money Maker 911 desktop app (pywebview: tiny, uses Windows' built-in Edge WebView2)."""
from __future__ import annotations

import base64
import copy
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import fields
from pathlib import Path

import webview

from ..config import (MergeConfig, PALETTES, SHAPES, HOOKS, APP_NAME, CREDIT, VERSION, LENGTH_PRESETS,
                      EMOJI_SETS, hex_to_rgb, MIN_TIERS, MAX_TIERS)
from ..modes.merge import MergeSim
from ..render import Renderer, render_video, render_preview_frame, make_thumbnail, prepare_images
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
        self._preview_dirty = True
        self._busy = False
        self._stop = False
        self._frame: tuple[str, int, float] | None = None   # latest preview frame (b64, tier, t)
        self._frame_id = 0
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
                "onboarded": self._settings.get("onboarded", False),
                "min_tiers": MIN_TIERS, "max_tiers": MAX_TIERS,
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
        types = {"sound": ("Audio (*.mp3;*.wav;*.ogg;*.m4a)",),
                 "image": ("Images (*.png;*.jpg;*.jpeg;*.webp)",),
                 "font": ("Fonts (*.ttf;*.otf)",)}.get(kind, ("All files (*.*)",))
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
            rend = Renderer(cfg, scale=0.5)
        except Exception as e:
            LOG.exception("tier preview failed: %s", e)
            return []
        prep = imageprep.tier_images(cfg)   # cached results only, never blocks on AI
        imgs, cut = prep["sources"], prep["images"]
        rows = []
        for t in range(cfg.tiers):
            spr = pygame.transform.smoothscale(rend.sprites[t], (56, 56))
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
        out = Path(self._settings.get("output_dir"))
        try:
            out.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(out))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(out)])
        except Exception as e:
            LOG.error("open folder failed: %s", e)

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

    def restart_preview(self) -> None:
        self._cfg.seed += 1
        self._preview_dirty = True

    def get_frame(self, last_id: int = 0):
        """Newest preview frame, or None when nothing new since last_id."""
        f = self._frame
        if f is None or self._frame_id == last_id:
            return None
        return {"id": self._frame_id, "jpg": f[0], "tier": f[1], "t": f[2]}

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
                        sim, rend = MergeSim(cfg), Renderer(cfg, scale=0.36)
                sim.step(1 / fps)
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
                out = Path(self._settings["output_dir"]) / f"merge_{int(time.time())}.mp4"
                cfg = copy.deepcopy(self._cfg)
                meta = render_video(cfg, str(out), progress=lambda p: self._emit({"i": 0, "n": 1, "p": p}),
                                    lock=GFX_LOCK)
                meta["title"] = make_title(cfg)
                self._emit({"done": True, "results": [meta]})
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
