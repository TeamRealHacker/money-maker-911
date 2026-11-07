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

## 🔜 TODO (in order)
1. Merge polish: tier images from a folder with auto circle-crop preview, per-tier names editor, custom hex colors, emoji tiers, thumbnail export, 30/45/60s length presets
2. AI cut-outs (rembg + birefnet-general / isnet-general-use / u2net, never the BRIA default) + "reject images with text"
3. Duplicate checker for batches
4. 🌀 Escape
5. 🧱 Breaker
6. 🥛 Glass Rush
7. 👻 Ghost Escape
8. 🎵 Rhythmic (MIDI)
9. ➕ Accumulate
10. ✏️ Drawer
11. 🏢 Glass Tower
12. 🚩 Flag Battle
13. ⚔️ Weapon Ball Battle
14. New 2D: Race, Plinko, Gravity Flip, Snake Grow, Chain Reaction, Countdown Survival, Color Sort, Voting
15. ☁️ Colab rendering (google-colab-cli via WSL2)
16. 3D modes: Wave, Marble Run, Ball Crush, Jelly, Cut Count, Magnet, then Hydraulic Press, Liquid Pour, Shatter, Coin Pusher
17. YouTube upload queue
