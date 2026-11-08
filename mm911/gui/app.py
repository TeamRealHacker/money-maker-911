"""Money Maker 911 desktop app (pywebview: tiny, uses Windows' built-in Edge WebView2)."""
from __future__ import annotations

import base64
import json
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
                      EMOJI_SETS, hex_to_rgb)
from ..modes.merge import MergeSim
from ..render import Renderer, render_video, render_preview_frame, make_thumbnail
from ..batch import run_batch, make_title


def app_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "MoneyMaker911"
    base.mkdir(parents=True, exist_ok=True)
    return base


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    p = base / "mm911" / "gui" / "web"
    return p if p.exists() else Path(__file__).resolve().parent / "web"


class Api:
    def __init__(self):
        self.window: webview.Window | None = None
        self.settings_path = app_dir() / "settings.json"
        self.settings = self._load_settings()
        self.cfg = MergeConfig.from_dict(self.settings.get("config", {}))
        self._preview_on = False
        self._preview_dirty = True
        self._busy = False
        self._stop = False

    # ---------- settings ----------
    def _load_settings(self) -> dict:
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return {"onboarded": False, "output_dir": str(Path.home() / "Videos" / "MoneyMaker911")}

    def _save(self):
        self.settings["config"] = self.cfg.to_dict()
        self.settings_path.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")

    def bootstrap(self) -> dict:
        return {"app": APP_NAME, "credit": CREDIT, "version": VERSION, "config": self.cfg.to_dict(),
                "palettes": {k: v for k, v in PALETTES.items()}, "shapes": SHAPES, "hooks": HOOKS,
                "lengths": LENGTH_PRESETS, "emoji_sets": EMOJI_SETS,
                "onboarded": self.settings.get("onboarded", False),
                "output_dir": self.settings.get("output_dir")}

    def finish_onboarding(self, choices: dict) -> bool:
        self.settings["onboarded"] = True
        if choices.get("palette"):
            self.cfg.palette = choices["palette"]
        if choices.get("theme_name"):
            self.cfg.theme_name = choices["theme_name"]
        self._preview_dirty = True
        self._save()
        return True

    def set_config(self, patch: dict) -> dict:
        names = {f.name: f.type for f in fields(MergeConfig)}
        for k, v in patch.items():
            if k in names:
                cur = getattr(self.cfg, k)
                try:
                    v = type(cur)(v) if not isinstance(cur, list) else v
                except Exception:
                    pass
                setattr(self.cfg, k, v)
        self._preview_dirty = True
        self._save()
        return self.cfg.to_dict()

    def reset_config(self) -> dict:
        self.cfg = MergeConfig()
        self._preview_dirty = True
        self._save()
        return self.cfg.to_dict()

    # ---------- files ----------
    def pick_file(self, kind: str) -> str:
        types = {"sound": ("Audio (*.mp3;*.wav;*.ogg;*.m4a)",),
                 "image": ("Images (*.png;*.jpg;*.jpeg;*.webp)",),
                 "font": ("Fonts (*.ttf;*.otf)",)}.get(kind, ("All files (*.*)",))
        res = self.window.create_file_dialog(webview.OPEN_DIALOG, file_types=types)
        return res[0] if res else ""

    def pick_images(self) -> list[str]:
        res = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True,
                                             file_types=("Images (*.png;*.jpg;*.jpeg;*.webp)",))
        files = sorted(res or [])
        self.cfg.tier_images = files[: self.cfg.tiers]
        self.cfg.tier_image_folder = ""
        self._preview_dirty = True
        self._save()
        return self.cfg.tier_images

    def pick_image_folder(self) -> list[dict]:
        res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if res:
            self.cfg.tier_image_folder = res[0]
            self._preview_dirty = True
            self._save()
        return self.tier_previews()

    # ---------- per-tier editor ----------
    def tier_previews(self) -> list[dict]:
        """One row per tier: circle-cropped preview (exactly how it renders), name, colour, emoji, image."""
        import io
        import pygame
        rend = Renderer(self.cfg, scale=0.5)
        imgs = self.cfg.resolved_tier_images()
        rows = []
        for t in range(self.cfg.tiers):
            spr = pygame.transform.smoothscale(rend.sprites[t], (56, 56))
            buf = io.BytesIO()
            pygame.image.save(spr, buf, "p.png")
            col = rend._tier_color(t)
            rows.append({"i": t, "png": base64.b64encode(buf.getvalue()).decode(),
                         "name": self.cfg.tier_value("tier_names", t),
                         "color": "#%02X%02X%02X" % col, "custom_color": bool(self.cfg.tier_value("tier_colors", t)),
                         "emoji": self.cfg.tier_value("tier_emojis", t),
                         "image": Path(imgs[t]).name if t < len(imgs) else ""})
        return rows

    def set_tier(self, i: int, key: str, value: str) -> list[dict]:
        attr = {"name": "tier_names", "color": "tier_colors", "emoji": "tier_emojis"}.get(key)
        if attr is None:
            return self.tier_previews()
        lst = list(getattr(self.cfg, attr))
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
        setattr(self.cfg, attr, lst)
        self._preview_dirty = True
        self._save()
        return self.tier_previews()

    def apply_emoji_set(self, name: str) -> list[dict]:
        self.cfg.tier_emojis = list(EMOJI_SETS.get(name, []))[: self.cfg.tiers] if name else []
        if name:
            self.cfg.theme_name = name
        self._preview_dirty = True
        self._save()
        return self.tier_previews()

    def clear_tiers(self) -> list[dict]:
        self.cfg.tier_names, self.cfg.tier_colors, self.cfg.tier_emojis = [], [], []
        self.cfg.tier_images, self.cfg.tier_image_folder = [], ""
        self._preview_dirty = True
        self._save()
        return self.tier_previews()

    def save_thumbnail(self) -> str:
        out = Path(self.settings["output_dir"]) / f"thumb_{int(time.time())}.jpg"
        make_thumbnail(self.cfg, str(out))
        return str(out)

    def pick_folder(self) -> str:
        res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if res:
            self.settings["output_dir"] = res[0]
            self._save()
            return res[0]
        return self.settings.get("output_dir", "")

    def open_output(self) -> None:
        out = Path(self.settings.get("output_dir"))
        out.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(out))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(out)])

    # ---------- live preview ----------
    def preview(self, on: bool) -> None:
        self._preview_on = on
        if on and not getattr(self, "_pthread", None):
            self._pthread = threading.Thread(target=self._preview_loop, daemon=True)
            self._pthread.start()

    def restart_preview(self) -> None:
        self.cfg.seed += 1
        self._preview_dirty = True

    def _preview_loop(self):
        sim = rend = None
        while True:
            if not self._preview_on or self._busy:
                time.sleep(0.1)
                continue
            if self._preview_dirty or sim is None or sim.done:
                if sim is not None and sim.done and not self._preview_dirty:
                    self.cfg.seed += 1
                self._preview_dirty = False
                sim, rend = MergeSim(self.cfg), Renderer(self.cfg, scale=0.36)
            t0 = time.time()
            sim.step(1 / 30)
            jpg = render_preview_frame(self.cfg, sim, rend)
            b64 = base64.b64encode(jpg).decode()
            try:
                self.window.evaluate_js(f"window.mm.frame('{b64}',{sim.best_tier + 1},{sim.t:.1f})")
            except Exception:
                pass
            time.sleep(max(0.0, 1 / 30 - (time.time() - t0)))

    # ---------- rendering ----------
    def _emit(self, payload: dict):
        try:
            self.window.evaluate_js(f"window.mm.progress({json.dumps(payload)})")
        except Exception:
            pass

    def render_one(self) -> bool:
        if self._busy:
            return False
        self._busy, self._stop = True, False

        def work():
            try:
                out = Path(self.settings["output_dir"]) / f"merge_{int(time.time())}.mp4"
                meta = render_video(self.cfg, str(out), progress=lambda p: self._emit({"i": 0, "n": 1, "p": p}))
                meta["title"] = make_title(self.cfg)
                self._emit({"done": True, "results": [meta]})
            except Exception as e:  # pragma: no cover
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
                res = run_batch(self.cfg, int(count), self.settings["output_dir"], randomize, only_wins,
                                progress=lambda i, n, p: self._emit({"i": i, "n": n, "p": p}),
                                stop=lambda: self._stop)
                self._emit({"done": True, "results": res})
            except Exception as e:  # pragma: no cover
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

    def boot():
        time.sleep(2.2)
        main_win = webview.create_window(APP_NAME, url=str(web / "index.html"), js_api=api, width=1360,
                                         height=860, min_size=(1100, 720), background_color="#F5F5F7")
        api.window = main_win
        time.sleep(0.6)
        splash.destroy()

    webview.start(boot, http_server=True, debug=False)


if __name__ == "__main__":
    main()
