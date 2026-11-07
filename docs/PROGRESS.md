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

## 🔜 TODO (in order)
1. AI cut-outs (rembg + birefnet-general / isnet-general-use / u2net, never the BRIA default) + "reject images with text"
2. Duplicate checker for batches
3. 🌀 Escape
4. 🧱 Breaker
5. 🥛 Glass Rush
6. 👻 Ghost Escape
7. 🎵 Rhythmic (MIDI)
8. ➕ Accumulate
9. ✏️ Drawer
10. 🏢 Glass Tower
11. 🚩 Flag Battle
12. ⚔️ Weapon Ball Battle
13. New 2D: Race, Plinko, Gravity Flip, Snake Grow, Chain Reaction, Countdown Survival, Color Sort, Voting
14. ☁️ Colab rendering (google-colab-cli via WSL2)
15. 3D modes: Wave, Marble Run, Ball Crush, Jelly, Cut Count, Magnet, then Hydraulic Press, Liquid Pour, Shatter, Coin Pusher
16. YouTube upload queue
