# Progress log

## ✅ Done
- **2026-11-07** · Core engine: pymunk physics, pygame offscreen renderer (supersampled, anti-aliased), FFmpeg export with auto hardware encoder (NVENC / QSV / AMF → x264 fallback)
- **2026-11-07** · 🍉 Merge Evolution v1: 6 palettes, 6 container shapes (circle, hexagon, octagon, square, heart, star), container spin, tier strip, pop-in + particle bursts, FINAL FORM ending, "So close…" ending
- **2026-11-07** · Sound: drop any file (Myinstants mp3 etc.), auto pitch per tier/merge/drop, built-in synthesized pop, optional music slot, soft limiter
- **2026-11-07** · Batch factory: N videos, anti-repeat rotation (palette, shape, hook, spin, speed), "only Final Form wins" seed search, `titles.csv` with title / description / hashtags
- **2026-11-07** · CLI: `MoneyMaker911.exe render|batch`
- **2026-11-07** · Desktop app: splash screen, onboarding (made by TeamRealHackers), Apple-style UI, live preview, inspector, render + batch with progress
- **2026-11-07** · Logo + Windows icon
- **2026-11-07** · GitHub Actions: smoke test + portable `MoneyMaker911.exe` → Nightly release
- **2026-11-07** · 🎨 Merge polish: tier image folder (natural name order) + circle-crop previews in a per-tier editor (name, emoji, hex colour), 5 offline emoji sets (Twemoji SVG, any other emoji auto-downloads once), auto `.jpg` thumbnail per video + `thumb` command + "Save thumbnail" button, 30/45/60s length presets (`--length`), `presets/emoji_fruit.json`
- **2026-11-08** · 🛠️ Stability fix: onboarding crash + freezing. pygame calls from the preview, render and UI threads are now serialized (was a native crash); preview thread snapshots the config and can't die on a bad setting; live preview is pulled by the page (requestAnimationFrame) instead of pushed with evaluate_js 30×/s, and pauses during onboarding / when minimized; JS API state made private (pywebview was walking the native Window object on load); sliders debounced; settings saved atomically; onboarding can't double-submit or get stuck; main window shows when loaded instead of after a fixed sleep; errors go to %APPDATA%\MoneyMaker911\app.log
- **2026-11-08** · ✂️ AI cut-outs + "Skip images with text" (v0.3.0): background removal with the rembg models BiRefNet-general (PCs with 12 GB+ RAM) / ISNet-general-use (default) / U²-Net, run offline with onnxruntime (uses your `rembg` install if you have one, otherwise a built-in runner with identical maths; the non-commercial BRIA model is never used). Models download once to `%APPDATA%\MoneyMaker911\models` (existing rembg downloads are reused). Cut-outs become stickers: tier-colour disc, white outline (toggle), soft shadow, auto-crop to the subject. "Quick" no-AI cut-out for flat backgrounds. Text check uses the 5 MB PP-OCRv4 text detector and skips captioned memes / watermarked images (extra images in the folder fill the gap). Everything is cached per file, runs off the UI thread with a live status line, and is optional: without onnxruntime the app still starts and offers Quick mode. CLI: `--cutout [model]`, `--reject-text`, and `main.py cutout --in folder --out folder`. The .exe now ships with onnxruntime.
- **2026-11-08** · 🚑 v0.3.1 hotfix: onboarding could never close (CSS `display:flex` beat the `hidden` attribute, so the welcome card stayed on screen with dead buttons; same bug kept the progress bar always visible). New onboarding step **How many forms?** (3 to 15) + **Use my pictures / Picture folder** (photos of you, memes, anything; the number of pictures sets the forms). Click any tier circle to set its own picture, right-click to remove. Final Form auto-fits the container for any form count; bigger drops with many forms so the Final Form stays reachable (default 9 forms now actually wins). Broken/missing images no longer crash; big photos are shrunk and cached. Regression tests in `tests/` (incl. headless-Chromium onboarding test).

## 🔜 TODO (in order)
1. Duplicate checker for batches
2. 🌀 Escape
3. 🧱 Breaker
4. 🥛 Glass Rush
5. 👻 Ghost Escape
6. 🎵 Rhythmic (MIDI)
7. ➕ Accumulate
8. ✏️ Drawer
9. 🏢 Glass Tower
10. 🚩 Flag Battle
11. ⚔️ Weapon Ball Battle
12. New 2D: Race, Plinko, Gravity Flip, Snake Grow, Chain Reaction, Countdown Survival, Color Sort, Voting
13. ☁️ Colab rendering (google-colab-cli via WSL2)
14. 3D modes: Wave, Marble Run, Ball Crush, Jelly, Cut Count, Magnet, then Hydraulic Press, Liquid Pour, Shatter, Coin Pusher
15. YouTube upload queue
