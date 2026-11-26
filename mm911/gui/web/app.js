const MODES = [
  ["🍉 Merge Evolution", "merge"], ["🌀 Escape", "escape"], ["🧱 Breaker", "breaker"], ["🥛 Glass Rush", "glass"], ["👻 Ghost Escape", "ghost"], ["🎵 Rhythmic", "rhythmic"], ["➕ Accumulate", "accumulate"], ["✏️ Drawer", "drawer"], ["🏢 Glass Tower", "tower"], ["🚩 Flag Battle", "battle"],
  ["⚔️ Weapon Battle", "weapon"],
  ["🎳 Bowling Strike", "bowling"], ["🏗️ Tower Stack", "stacker"], ["🫧 Bubble Pop", "bubble"], ["🕳️ Hole Eater", "hole"], ["♾️ Infinite Zoom", "zoom"],
  ["🏁 Race", "race"], ["🔄 Gravity Flip", "flip"], ["🐍 Snake Grow", "snake"], ["💥 Chain Reaction", "chain"], ["⏳ Countdown Survival", "countdown"], ["🎨 Color Sort", "colorsort"], ["🗳️ Voting", "voting"], ["🎯 Plinko", "plinko"], ["🌊 Wave 3D"], ["🎢 Marble Run 3D"], ["🧲 Magnet 3D"],
];
const MODE_HOOKS = { merge: "Will it reach the Final Form?", escape: "Can it escape all 8 rings?",
  breaker: "Can it break every brick?", glass: "Will the glass hold?", ghost: "Can the ghost escape the dark?", rhythmic: "Can the ball play the whole song?", accumulate: "Can it reach 100 balls?", drawer: "Can it paint the whole picture?", tower: "How many floors will break?", battle: "Who wins the battle?", weapon: "Who survives?", plinko: "Can it reach the jackpot?", race: "Who wins the race?", flip: "Can gravity survive?", snake: "How long can it get?", chain: "Can one pop clear them all?", countdown: "Who survives the countdown?", colorsort: "Can it sort every colour?", voting: "Who gets your vote?",
  bowling: "Can it bowl a STRIKE?", stacker: "How high can the tower go?", bubble: "Can it pop every bubble?", hole: "Can the hole eat them all?", zoom: "How deep do the stairs go?" };
const $ = (s) => document.querySelector(s);
let state = {};
let booted = false;

// Every call into Python goes through here: a failing call shows a toast instead of
// leaving a button dead or the onboarding overlay stuck on screen.
async function call(name, ...args) {
  try { return await pywebview.api[name](...args); }
  catch (e) { console.error(name, e); toast("Something went wrong (" + name + "). Try again."); throw e; }
}

// ---- live preview: pull the newest frame when the browser is ready to paint one ----
let lastFrame = 0, previewOn = false, pulling = false;
async function pullFrame() {
  if (!previewOn) return;
  if (!pulling && !document.hidden) {
    pulling = true;
    try {
      const f = await pywebview.api.get_frame(lastFrame);
      if (f) { lastFrame = f.id; mm.frame(f.jpg, f.tier, f.t); if (f.snd && f.snd.length) sfx.play(f.snd); }
    } catch (e) { /* app closing */ }
    pulling = false;
  }
  setTimeout(() => requestAnimationFrame(pullFrame), 33);
}
// Tell Python how many real screen pixels the preview has (HiDPI aware), so it renders the
// preview at that size instead of a small frame the browser has to stretch (that looked blurry).
let lastPx = 0;
function previewSize() {
  const ph = document.querySelector(".phone");
  if (!ph || !window.pywebview) return;
  const px = Math.round(ph.clientHeight * (window.devicePixelRatio || 1));
  if (px > 0 && Math.abs(px - lastPx) > 8) { lastPx = px; try { pywebview.api.preview_size(px); } catch (e) { /* closing */ } }
}
window.addEventListener("resize", () => { clearTimeout(window.__pvT); window.__pvT = setTimeout(previewSize, 250); });
function setPreview(on) {
  if (on === previewOn) return;
  previewOn = on;
  if (on) previewSize();
  pywebview.api.preview(on);
  if (on) requestAnimationFrame(pullFrame);
}
document.addEventListener("visibilitychange", () => { if (state.onboarded) setPreview(!document.hidden); });

const PREP_KEYS = ["ai_cutout", "cutout_model", "reject_text", "tiers", "tier_images", "tier_image_folder"];
let prepRunning = false, prepAgain = false;

// Sliders fire dozens of events a second: send only the last value every 120 ms.
let pending = {}, pendTimer = null;
function queueSet(patch) {
  Object.assign(pending, patch);
  clearTimeout(pendTimer);
  pendTimer = setTimeout(() => { const p = pending; pending = {}; mm.set(p); }, 120);
}

// ---- sound: listen to your sound, and hear the live preview (same pitch rules as the export) ----
const sfx = {
  ctx: null, buf: null, bufKey: "", on: localStorage.getItem("mm_pvsound") !== "0", player: null,
  ensure() {
    if (!this.ctx) { const C = window.AudioContext || window.webkitAudioContext; if (C) this.ctx = new C(); }
    if (this.ctx && this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  },
  async load() {
    const key = (state.config.sound_path || "") + "|";
    if (this.buf && this.bufKey === key) return;
    this.bufKey = key; this.buf = null;
    let url = "";
    try { url = await pywebview.api.sound_sample("sound"); } catch (e) { return; }
    if (typeof url !== "string" || !url.startsWith("data:") || !this.ensure()) return;
    const bytes = Uint8Array.from(atob(url.split(",")[1]), (c) => c.charCodeAt(0));
    try { this.buf = await this.ctx.decodeAudioData(bytes.buffer); } catch (e) { this.buf = null; }
  },
  play(events) {
    if (!this.on || !this.buf || !this.ctx || this.ctx.state !== "running") return;
    const vol = Math.min(1.2, +state.config.sound_volume || 0);
    events.slice(-6).forEach(([kind, tier]) => {
      const c = state.config, ov = (c.tier_semitones || [])[tier];
      const base = ov !== undefined && ov !== null && ov !== "" ? +ov : tier * (c.pitch_step ?? 1.6);
      const semis = base + (kind === "drop" ? (c.drop_pitch ?? -4) : kind === "final" ? (c.final_pitch ?? 7) : 0);
      const src = this.ctx.createBufferSource(), g = this.ctx.createGain();
      src.buffer = this.buf; src.playbackRate.value = Math.pow(2, semis / 12);
      g.gain.value = vol * (kind === "drop" ? 0.35 : kind === "final" ? 1.2 : 0.9) * 0.6;
      src.connect(g).connect(this.ctx.destination); src.start();
    });
  },
};
// browsers only allow sound after a click: unlock on the first one
document.addEventListener("pointerdown", () => { sfx.ensure(); sfx.load(); }, { once: true });

const mm = {
  async listen(kind) {
    if (sfx.player) { sfx.player.pause(); sfx.player = null; }
    const url = await call("sound_sample", kind);
    if (typeof url !== "string" || !url.startsWith("data:")) { toast(kind === "music" ? "Add a music file first." : "Couldn't read that sound file. Try an mp3 or wav."); return; }
    sfx.player = new Audio(url);
    sfx.player.play().catch(() => toast("Sound is blocked. Click anywhere in the app, then try again."));
  },
  frame(b64, tier, t) {
    $("#frame").src = "data:image/jpeg;base64," + b64;
    $("#tier").textContent = "Tier " + tier;
    $("#time").textContent = t.toFixed(1) + "s";
  },
  progress(m) {
    if (m.colab) return mm.colabProgress(m.colab);
    if (m.pub) { mm.uploadProgress(m); return mm.pubProgress(m); }
    if (m.pubdone) { mm.uploadDone(m); return mm.pubDone(m); }
    if (m.autoupload) { toast("Auto-upload: " + m.autoupload.note); if (m.autoupload.queued) mm.refreshPlan(); return; }
    const p = $("#prog");
    p.hidden = false;
    if (m.error) { $("#ptext").textContent = "Error: " + m.error; return; }
    if (m.done) {
      $("#bar").style.width = "100%";
      const wins = m.results.filter((r) => r.won).length;
      $("#ptext").textContent = `Done ✓ ${m.results.length} video(s), ${wins} Final Form`;
      $("#status").textContent = "Live preview";
      return;
    }
    const overall = (m.i + m.p) / m.n;
    $("#bar").style.width = (overall * 100).toFixed(1) + "%";
    $("#ptext").textContent = `Video ${m.i + 1} of ${m.n} · ${(m.p * 100).toFixed(0)}%`;
    $("#status").textContent = "Rendering…";
  },
  // switching mode also swaps the hook, unless the user wrote their own
  async setMode(key) {
    const h = (state.config && state.config.hook) || "";
    const patch = { mode: key };
    if (!h || Object.values(MODE_HOOKS).includes(h) || (state.hooks || []).includes(h)) patch.hook = MODE_HOOKS[key] || h;
    return mm.set(patch);
  },
  async set(patch) {
    state.config = await call("set_config", patch); fill(); paintPreflight(); mm.refreshHistory();
    if (PREP_KEYS.some((k) => k in patch)) mm.prep();
    else if (["tiers", "palette", "tier_images", "show_tier_labels", "cutout_outline", "ball_scale", "base_radius", "growth",
              "size_curve", "tier_sizes", "ball_outline", "ball_outline_color", "auto_fit", "ball_highlight", "ball_inner_shadow",
              "ball_rim", "image_fit", "image_zoom", "cutout_style", "mode"].some((k) => k in patch)) tiers();
    if (["tiers", "pitch_step", "sound_path", "auto_sounds"].some((k) => k in patch)) soundRows();
  },
  // AI cut-outs / text check run in Python on their own thread; we poll a status line meanwhile.
  async prep() {
    const c = state.config;
    const hasImgs = c.tier_image_folder || (c.tier_images || []).length;
    if (!hasImgs || !(c.ai_cutout || c.reject_text)) { aiHint(); return tiers(); }
    if (prepRunning) { prepAgain = true; return; }
    prepRunning = true;
    const el = $("#aistatus");
    el.classList.add("busy"); el.textContent = "Preparing images…";
    const poll = setInterval(async () => {
      try { const s = await pywebview.api.prep_status(); if (s.note) el.textContent = s.note; } catch (e) { /* closing */ }
    }, 400);
    let r = null;
    try { r = await call("prepare_images"); } catch (e) { /* toast shown */ }
    clearInterval(poll);
    el.classList.remove("busy");
    prepRunning = false;
    if (r) { state.cutout = r.status; aiModels(); aiHint(r); }
    await tiers();
    if (prepAgain) { prepAgain = false; mm.prep(); }
  },
  async pick(key, kind, extra) {
    const f = await pywebview.api.pick_file(kind);
    if (f) await mm.set({ [key]: f, ...(extra || {}) });
  },
  async pickImages() {
    await call("pick_images"); state.config = (await call("bootstrap")).config; fill(); await tiers(); mm.prep();
    if (state.config.tier_images.length) toast(`${state.config.tier_images.length} picture(s) loaded · ${state.config.tiers} forms`);
  },
  async pickImageFolder() {
    tiers(await call("pick_image_folder")); state.config = (await call("bootstrap")).config; fill(); mm.prep();
    if (state.config.tier_image_folder) toast(`Folder loaded · ${state.config.tiers} forms`);
  },
  async setTier(i, key, v) { tiers(await call("set_tier", i, key, v)); },
  async tierImage(i) { tiers(await call("pick_tier_image", i)); state.config = (await call("bootstrap")).config; fill(); mm.prep(); },
  async clearTierImage(i) { tiers(await call("clear_tier_image", i)); state.config = (await call("bootstrap")).config; fill(); },
  // ---- themes ----
  async saveTheme() {
    const n = $("#themename").value.trim();
    if (!n) return toast("Give the theme a name first");
    themes(await call("save_theme", n)); toast("Theme saved ✓");
  },
  async loadTheme() {
    const n = $("#themes").value; if (!n) return;
    state.config = await call("load_theme", n); fill(); tiers(); soundRows(); toast("Loaded " + n);
  },
  async deleteTheme() { const n = $("#themes").value; if (n) themes(await call("delete_theme", n)); },
  async exportTheme() { const f = await call("export_theme"); if (f) toast("Exported ✓ " + f.split(/[\\/]/).pop()); },
  async importTheme() {
    const r = await call("import_theme");
    if (r.error) return toast("Import failed: " + r.error);
    state.config = r.config; fill(); tiers(); soundRows();
  },
  setPoints() {
    try {
      const pts = JSON.parse($("#ptsbox").value);
      if (!Array.isArray(pts) || pts.length < 3) throw new Error("need 3+ points");
      mm.set({ container_points: pts, container_shape: "custom" });
    } catch (e) { toast("Points must look like [[-1,-0.5],[0,1],[1,-0.5]]"); }
  },
  bgThird() {
    const c = [...(state.config.bg_colors || [])];
    if (c.length >= 3) c.length = 2; else { while (c.length < 2) c.push(c.length ? "#E2ECE9" : "#FDE2E4"); c.push("#FFFFFF"); }
    mm.set({ bg_colors: c, bg_mode: c.length === 1 ? "solid" : "gradient" });
  },
  // ---- sounds ----
  async soundSearch(q) {
    q = (q || $("#sq").value || "").trim(); if (!q) return;
    $("#sq").value = q; $("#smsg").textContent = "Searching Myinstants…";
    const r = await call("sound_search", q);
    $("#smsg").textContent = r.error || (r.results.length ? `${r.results.length} sounds · ▶ preview · use for all tiers, drop or final` : "Nothing found");
    $("#sresults").innerHTML = r.results.map((x, i) => `
      <div class="sres"><button class="play" onclick="mm.play('${esc(x.mp3_url)}')">▶</button>
        <span title="${esc(x.name)}">${esc(x.name)}</span>
        <button class="ghost xs" onclick="mm.useSound(${i},'all')" title="One sound, auto pitched per tier">Use for tiers</button>
        <button class="link xs" onclick="mm.useSound(${i},'drop')">drop</button><button class="link xs" onclick="mm.useSound(${i},'final')">final</button></div>`).join("");
    state.sresults = r.results;
  },
  play(src) { const a = $("#player"); a.src = src; a.currentTime = 0; a.play().catch(() => toast("Can't play that preview")); },
  async useSound(i, target) {
    const x = state.sresults[i]; toast("Downloading " + x.name + "…");
    const r = await call("sound_use", x.mp3_url, target);
    if (r.error) return toast(r.error);
    state.config = r.config; fill(); soundRows(r.rows); toast("Using " + x.name + " ✓");
  },
  async autoFill(kw) {
    kw = kw || $("#sq").value.trim() || state.config.auto_sound_keywords || "";
    toast("Picking sounds" + (kw ? " for “" + kw + "”" : "") + "…");
    const r = await call("sound_auto_fill", kw, "", 0);
    if (r.error) return toast(r.error);
    state.config = r.config; fill(); soundRows(r.rows);
    toast("✓ " + r.picked.join(", ") + " (low → high)");
  },
  async previewTier(key) { const u = await call("preview_sound", key); if (u) mm.play(u); },
  async setPitch(key, v) { soundRows(await call("set_sound_pitch", key, v)); },
  async pickSound(key) { const r = await call("pick_sound_for", key); state.config = r.config; fill(); soundRows(r.rows); },
  async clearSound(key) { const r = await call("clear_sound", key); state.config = r.config; fill(); soundRows(r.rows); },
  async emojiSet(name) { tiers(await pywebview.api.apply_emoji_set(name)); state.config = (await pywebview.api.bootstrap()).config; fill(); },
  async clearTiers() { tiers(await pywebview.api.clear_tiers()); state.config = (await pywebview.api.bootstrap()).config; fill(); aiHint(); },
  async thumb() {
    toast("Making thumbnail…");
    const f = await call("save_thumbnail");
    toast(f.startsWith("error:") ? "Thumbnail failed: " + f.slice(6) : "Thumbnail saved ✓ " + f.split(/[\\/]/).pop());
  },
  async folder() { state.output_dir = await pywebview.api.pick_folder(); fill(); },
  restart() { pywebview.api.restart_preview(); },
  async reset() { state.config = await pywebview.api.reset_config(); fill(); paintPreflight(); },
  // ---- 📤 one-click upload (library page + sidebar) ----
  async refreshUploadState() {
    let st = null;
    try { st = await call("auto_upload_state"); } catch (e) { return; }
    state.upload = st;
    const box = $("#libauto"), hint = $("#libautohint"), btn = $("#libuploadbtn"), cnt = $("#libuploadcount");
    if (box) { box.checked = !!st.enabled; box.closest(".libauto").classList.toggle("on", !!st.enabled); }
    if (hint) {
      hint.textContent = st.enabled
        ? (st.signed_in ? "On — new videos upload themselves" : "On, but not signed in to YouTube yet")
        : "Off — upload when you say so";
      hint.className = "hint" + (st.enabled && !st.signed_in ? " bad" : "");
    }
    const n = st.todo || 0;
    if (cnt) { cnt.textContent = String(n); cnt.hidden = !n; }
    if (btn) {
      btn.disabled = n === 0;
      btn.title = n ? `${n} video(s) not on YouTube yet` : "Every video is already uploaded";
    }
    // sidebar: a green dot means auto-upload is armed
    const dot = document.createElement("i");
    let sd = $("#pubnav .dot");
    if (st.enabled && !sd) { dot.className = "dot"; $("#pubnav").appendChild(dot); }
    if (!st.enabled && sd) sd.remove();
  },
  async autoUploadToggle() {
    const st = state.upload || {};
    return mm.autoUploadFromLibrary(!st.enabled);
  },
  async autoUploadFromLibrary(on) {
    let r = null;
    try { r = await call("auto_upload_set", !!on); } catch (e) { return; }
    toast(on ? "Auto-upload on — new videos go up by themselves" : "Auto-upload off");
    if (on && r && !r.signed_in) toast("Tip: sign in to YouTube in the Publish studio");
    await mm.refreshUploadState();
  },
  // literally one click: everything not on YouTube yet
  async uploadNew() {
    const n = (state.upload || {}).todo || 0;
    if (!n) return toast("Nothing new to upload");
    const ok = await call("publish_upload", null);
    if (!ok) return toast("Upload not started — check the Publish studio setup");
    const prog = $("#libprog"); if (prog) prog.hidden = false;
    mm.refreshPlan();
  },
  uploadProgress(m) {
    const prog = $("#libprog"), bar = $("#libbar"), text = $("#libptext");
    if (!prog) return;
    prog.hidden = false;
    if (bar) bar.style.width = (m.n ? ((m.i + (m.p || 0)) / m.n) * 100 : 0).toFixed(1) + "%";
    if (text) text.textContent = `Uploading ${m.i + 1} of ${m.n}${m.title ? " · " + m.title : ""}`;
  },
  uploadDone(m) {
    const prog = $("#libprog"); if (prog) prog.hidden = true;
    toast(m.error || m.note || "Upload finished");
    mm.refreshUploadState();
    if (state.lib) mm.refreshLibrary();
  },

  // ---- ⌘K command palette ----
  async openPalette(q) {
    const el = $("#palette");
    if (!el) return;
    el.hidden = false;
    const input = $("#palq");
    if (input) { input.value = q || ""; setTimeout(() => input.focus(), 30); }
    mm.palQuery = q || "";
    if (!state.palIndex) {
      try { state.palIndex = await call("palette"); } catch (e) { state.palIndex = null; }
    }
    await mm.paletteSearch();
  },
  closePalette() {
    const el = $("#palette");
    if (el) el.hidden = true;
    mm.palResults = [];
    mm.palSel = 0;
  },
  async paletteSearch() {
    const q = (($("#palq") || {}).value || "").trim();
    let rows = [];
    if (state.palIndex) {
      // local ranking for instant feedback; Python is only used for the index
      rows = mm.rankPalette(state.palIndex, q);
    } else {
      try { rows = await call("palette_search", q); } catch (e) { rows = []; }
    }
    mm.palResults = rows;
    mm.palSel = 0;
    mm.paintPalette();
  },
  // mirror of mm911/palette.py:score - curated first, then by match strength
  rankPalette(idx, q) {
    const norm = (t) => String(t || "").toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
    const bonus = { action: 12, page: 9, setting: 0, video: 3 };
    const order = { action: 0, page: 1, setting: 2, video: 3 };
    const score = (label, kw) => {
      const n = norm(q), lab = norm(label), k = norm(kw);
      if (!n) return 0;
      if (lab === n) return 100;
      if (lab.startsWith(n)) return 90;
      if (lab.split(" ").some((w) => w.startsWith(n))) return 80;
      if (lab.includes(n)) return 65;
      if (k === n) return 85;
      if (k.split(" ").some((w) => w.startsWith(n))) return 55;
      if (k.includes(n)) return 35;
      const parts = n.split(" ");
      if (parts.length > 1 && parts.every((x) => (lab + " " + k).includes(x))) return 25;
      return 0;
    };
    const out = [];
    for (const kind of ["action", "page", "setting", "video"]) {
      const key = { action: "actions", page: "pages", setting: "settings", video: "videos" }[kind];
      for (const it of (idx[key] || [])) {
        const s = score(it.label, it.keywords);
        if (s) out.push({ ...it, score: s + bonus[kind] });
      }
    }
    if (!q) {
      const first = (idx.actions || []).filter((a) => ["render", "batch", "publish", "library", "colab", "upload", "undo", "update"].includes(a.id));
      return first.slice(0, 12);
    }
    out.sort((a, b) => (order[a.kind] - order[b.kind]) || (b.score - a.score) || a.label.localeCompare(b.label));
    return out.slice(0, 12);
  },
  paintPalette() {
    const box = $("#pallist");
    if (!box) return;
    const rows = mm.palResults || [];
    const icons = { action: "⚡", page: "→", setting: "⚙", video: "🎬" };
    box.innerHTML = rows.length ? rows.map((r, i) => `
      <div class="palrow ${i === mm.palSel ? "on" : ""}" data-i="${i}" onclick="mm.palRun(${i})"
           onmousemove="mm.palHover(${i})">
        <span class="ico">${icons[r.kind] || "•"}</span>
        <span class="lab">${esc(r.label)}${r.meta ? `<small>${esc(r.meta)}</small>` : ""}</span>
        ${r.kind === "setting" ? `<span class="grp">setting</span>` : ""}
        ${r.shortcut ? `<kbd>${esc(r.shortcut)}</kbd>` : ""}
      </div>`).join("")
      : `<div class="palempty">Nothing matches “${esc(($("#palq") || {}).value || "")}”. Try “render”, “upload”, “gravity” or a video title.</div>`;
    const on = box.querySelector(".palrow.on");
    if (on && on.scrollIntoView) { try { on.scrollIntoView({ block: "nearest" }); } catch (e) {} }
  },
  paletteKey(e) {
    const n = (mm.palResults || []).length;
    if (e.key === "ArrowDown") { e.preventDefault(); mm.palSel = n ? (mm.palSel + 1) % n : 0; mm.paintPalette(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); mm.palSel = n ? (mm.palSel - 1 + n) % n : 0; mm.paintPalette(); }
    else if (e.key === "Enter") { e.preventDefault(); mm.palRun(mm.palSel); }
    else if (e.key === "Escape") { e.preventDefault(); mm.closePalette(); }
  },
  palHover(i) { if (mm.palSel !== i) { mm.palSel = i; mm.paintPalette(); } },
  async palRun(i) {
    const r = (mm.palResults || [])[i];
    if (!r) return;
    mm.closePalette();
    // settings and videos are handled here (they need the page); actions ask Python
    if (r.kind === "setting") { mm.reveal(r.id); return; }
    if (r.kind === "page") { mm.goPage(r.id); return; }
    if (r.kind === "video") { mm.libPlay(r.id); return; }
    let res = null;
    try { res = await call("palette_run", r.kind, r.id); } catch (e) { return; }
    if (!res || res.error) return toast((res && res.error) || "That did not work");
    if (res.reveal) return mm.reveal(res.reveal);
    if (res.page) return mm.goPage(res.page);
    if (res.focus === "settings") { const el = $("#setsearch"); if (el) el.focus(); return; }
    if (res.shortcuts) return mm.showShortcuts();
    if (res.preflight) { state.preflight = res.preflight; paintPreflight(); return; }
    if (res.update) { state.update = res.update; mm.renderUpdate(state.update); mm.paintUpdateBadge(); mm.openUpdate(); return; }
    if (res.config) { state.config = res.config; fill(); paintPreflight(); }
    if (res.started) { mm.progress({ i: 0, n: 1, p: 0 }); return; }
    if (res.stopped) return toast("Stopping…");
    if (res.opened) return;
    if (res.call === "batch") return mm.renderBatch();
    if (res.js) return mm.paletteJs(res.js);
  },
  paletteJs(id) {
    if (id === "thumbnail") return mm.thumb();
    if (id === "new_run") return mm.restart();
    if (id === "themes") { const d = [...document.querySelectorAll("details")].find((x) => /Themes/.test(x.querySelector("summary") || {}).textContent || ""); if (d) { d.open = true; if (d.scrollIntoView) d.scrollIntoView({ block: "center" }); } return; }
    if (id === "upload") { mm.openPublish().then(() => mm.startUpload()); return; }
    if (id === "auto_upload") return mm.autoUploadToggle();
  },

  // Every page the palette can send you to.
  goPage(id) {
    if (id === "library") return mm.openLibrary();
    if (id === "publish") return mm.openPublish();
    if (id === "colab") return mm.openColab();
    if (id && id.startsWith("sec-")) {
      const d = document.getElementById(id);
      if (d) { d.open = true; if (d.scrollIntoView) d.scrollIntoView({ block: "center", behavior: "smooth" }); }
    }
  },

  // The palette index wants labels for every control, so settings are searchable by what
  // the user sees ("Gravity"), not by their key ("gravity_strength").
  settingLabels() {
    const out = {};
    document.querySelectorAll("[data-k],[data-csv]").forEach((el) => {
      const key = el.dataset.k || el.dataset.csv;
      if (!key) return;
      const row = el.closest(".row");
      let label = "";
      if (row) {
        const span = row.querySelector(":scope > span");
        if (span) label = span.textContent.replace(/\s+/g, " ").trim();
      }
      if (!label && el.closest("label")) label = el.closest("label").textContent.trim();
      out[key] = label || key.replace(/_/g, " ");
    });
    return out;
  },

  // ---- ⌨️ shortcuts sheet ----
  showShortcuts() {
    const el = $("#shortcuts"), box = $("#keyslist");
    if (el) el.hidden = false;
    const rows = (state.palIndex && state.palIndex.shortcuts) || [];
    if (box && rows.length) {
      box.innerHTML = rows.map((r) => `<div class="keysrow"><span>${esc(r.what)}</span><kbd>${esc(r.keys)}</kbd></div>`).join("");
    } else if (box) {
      box.innerHTML = `<div class="keysrow"><span>Search everything</span><kbd>⌘K / Ctrl+K</kbd></div>`;
    }
  },
  closeShortcuts() { const el = $("#shortcuts"); if (el) el.hidden = true; },

  // ---- ☁️ Colab GPU rendering ----
  async openColab() {
    const el = $("#colabpage");
    if (el) el.hidden = false;
    await mm.refreshColab();
  },
  closeColab() { const el = $("#colabpage"); if (el) el.hidden = true; },
  async refreshColab() {
    let r = null;
    try { r = await call("colab_status"); } catch (e) { return; }
    state.colab = r;
    const sel = $("#colabgpu");
    if (sel) sel.innerHTML = (r.gpus || []).map((g) => `<option value="${esc(g.id)}" title="${esc(g.note || "")}">${esc(g.label || g.id)}</option>`).join("");
    const steps = $("#colabsteps"), status = $("#colabstatus"), acts = $("#colabacts"), go = $("#colabgo");
    if (status) status.textContent = r.ready ? "Colab is ready" : (r.wsl === false && r.platform === "windows"
      ? "Needs WSL2 + the Colab CLI (Windows cannot run it directly)" : (r.hint || "Not ready yet"));
    if (steps) {
      const rows = (r.steps || []).map((t) => t);
      const done = [r.cli, r.cli, r.ready];
      let firstOpen = true;
      steps.innerHTML = rows.map((t, i) => {
        const d = !!done[i];
        const cls = d ? "done" : (firstOpen ? "now" : "");
        if (!d) firstOpen = false;
        return `<li class="${cls}"><span class="n">${d ? "✓" : i + 1}</span><span>${t}</span></li>`;
      }).join("") + (r.notebook ? "" : `<li><span class="n">!</span><span>The render notebook is missing from this build.</span></li>`);
    }
    if (acts) {
      acts.innerHTML = r.ready
        ? `<span class="hint">GPU: ${(r.gpus || []).map((g) => esc(g.id)).join(" · ")}</span>`
        : `<button class="ghost sm" onclick="mm.colabSetup()">Setup guide</button>`;
    }
    if (go) go.disabled = !r.ready;
  },
  colabSetup() { call("colab_open_setup"); },
  async refreshColabDot() {
    let r = null;
    try { r = await call("colab_status"); } catch (e) { return; }
    const dot = $("#colabdot");
    if (dot) {
      dot.hidden = false;
      dot.style.background = r.ready ? "#2ECC71" : "#D9D9DE";
      $("#colabnav").title = r.ready ? "Colab ready — render on a GPU" : "Colab GPU rendering (needs setup)";
    }
  },
  async colabQuota() {
    const el = $("#colabquota");
    if (el) el.textContent = "Checking compute units…";
    let r = null;
    try { r = await call("colab_quota"); } catch (e) { return; }
    if (el) el.textContent = r.error ? `Quota: ${r.error}` : (r.output || "No quota information returned.").slice(0, 400);
  },
  async startColab() {
    const gpu = (($("#colabgpu") || {}).value) || "T4";
    const count = Math.max(0, parseInt((($("#colabcount") || {}).value) || "0") || 0);
    const keep = !!($("#colabkeep") || {}).checked;
    const r = await call("colab_render", gpu, count, keep);
    if (!r || r.ok === false) {
      toast((r && r.error) || "Colab could not start");
      if (r && r.setup) return mm.refreshColab();
      return;
    }
    const prog = $("#colabprog"); if (prog) prog.hidden = false;
  },
  colabProgress(m) {
    const prog = $("#colabprog"), bar = $("#colabbar"), text = $("#colabptext"), res = $("#colabresults");
    if (m.state === "packing") { if (prog) prog.hidden = false; if (text) text.textContent = m.note; return; }
    if (prog) prog.hidden = true;
    if (m.state === "error") {
      if (res) res.innerHTML = `<div class="bad">✗ ${esc(m.error)}</div>`;
      return toast("Colab render failed");
    }
    if (m.state === "done") {
      const vids = m.videos || [];
      if (res) res.innerHTML = vids.length
        ? `${vids.length} video(s) downloaded:<br>` + vids.map((v) => `<div>✓ ${esc(String(v).split(/[\\/]/).pop())}</div>`).join("")
        : `<span class="hint">${esc(m.note || "No videos came back.")}</span>`;
      toast(m.note || "Colab render finished");
      if (state.lib) mm.refreshLibrary();
    }
  },

  // ---- 📚 library ----
  async openLibrary() {
    const el = $("#library");
    if (el) el.hidden = false;
    mm.refreshUploadState();
    await mm.refreshLibrary();
  },
  closeLibrary() { const el = $("#library"); if (el) el.hidden = true; },

  async refreshLibrary() {
    let r = null;
    try { r = await call("library"); } catch (e) { return; }
    state.lib = r;
    // thumbnails come from Python as data URLs (the web view cannot read file paths)
    await Promise.all((r.videos || []).filter((v) => v.thumb && !v.thumb.startsWith("data:"))
      .slice(0, 80).map(async (v) => {
        try { v.thumb = await call("library_thumb", v.thumb); } catch (e) { v.thumb = ""; }
      }));
    const cnt = $("#libcount");
    if (cnt) { cnt.hidden = !r.count; cnt.textContent = r.count; }
    mm.paintLibrary();
  },

  paintLibrary() {
    const r = state.lib || { videos: [] };
    const q = (($("#libsearch") || {}).value || "").trim().toLowerCase();
    const f = ($("#libfilter") || {}).value || "";
    const list = (r.videos || []).filter((v) => {
      if (q && !(`${v.title} ${v.mode} ${v.file}`.toLowerCase().includes(q))) return false;
      if (f === "won" && !v.won) return false;
      if (f === "uploaded" && !v.uploaded) return false;
      if (f === "notuploaded" && v.uploaded) return false;
      return true;
    });
    const grid = $("#libgrid"), stats = $("#libstats"), sub = $("#libsub");
    if (sub) sub.textContent = `${r.count || 0} video(s) · ${r.total_mb || 0} MB · ${String(r.folder || "").split(/[\\/]/).pop() || "output"}`;
    if (stats) stats.textContent = list.length === (r.videos || []).length ? "" : `${list.length} shown`;
    if (!grid) return;
    grid.innerHTML = list.length ? list.map((v) => `
      <div class="libcard" data-file="${esc(v.file)}">
        <div class="libthumb" ${v.thumb ? `style="background-image:url('${esc(v.thumb)}')"` : ""}>
          ${v.thumb ? `<img src="${esc(v.thumb)}" alt="">` : "no thumbnail"}
          ${v.won ? '<span class="badge won">🏆 won</span>' : ""}
          ${v.uploaded ? '<span class="badge up">✓ uploaded</span>' : ""}
        </div>
        <div class="libbody">
          <b title="${esc(v.title)}">${esc(v.title)}</b>
          <small>${esc(v.when)} · ${esc(v.mb)} MB${v.mode ? " · " + esc(v.mode) : ""}</small>
          <small>${v.seed ? "seed " + esc(v.seed) : ""}${v.palette ? " · " + esc(v.palette) : ""}${v.shape ? " · " + esc(v.shape) : ""}</small>
          <div class="libacts">
            <button onclick="mm.libPlay('${esc(v.file)}')">▶ Play</button>
            <button onclick="mm.libLook('${esc(v.file)}')">↺ Use this look</button>
            <button onclick="mm.libReveal('${esc(v.file)}')">📁</button>
            <button class="muted" onclick="mm.libDelete('${esc(v.file)}')">🗑</button>
          </div>
        </div>
      </div>`).join("")
      : `<div class="libempty">${r.count ? "Nothing matches that filter." : "No videos yet — render one and it shows up here."}</div>`;
  },

  libPlay(name) { call("library_play", name); },
  libReveal(name) { call("library_reveal", name); },
  async libLook(name) {
    const r = await call("look_of", name);
    if (!r || !Object.keys(r).length) return toast("This video predates looks — render it once more to save its look.");
    const a = await call("apply_look", name, false);
    if (a.error) return toast(a.error);
    state.config = a.config; fill(); paintPreflight();
    toast("Look applied ✓ — render to make a new video with it");
    mm.closeLibrary();
  },
  async libVary(name) {
    const a = await call("apply_look", name, true);
    if (a.error) return toast(a.error);
    state.config = a.config; fill(); paintPreflight();
    toast("Same look, new seed 🎲");
    mm.closeLibrary();
  },
  async libDelete(name) {
    if (!confirm("Delete " + name + " and its thumbnail?")) return;
    const r = await call("library_delete", name);
    if (r.error) return toast(r.error);
    toast("Deleted ✓");
    mm.refreshLibrary();
  },

  // ---- undo / redo ----
  async undo() {
    const r = await call("undo");
    if (!r.done) return toast("Nothing to undo");
    state.config = (await call("bootstrap")).config;
    fill(); paintPreflight(); mm.paintHistory();
    toast("Undone");
  },
  async redo() {
    const r = await call("redo");
    if (!r.done) return toast("Nothing to redo");
    state.config = (await call("bootstrap")).config;
    fill(); paintPreflight(); mm.paintHistory();
    toast("Redone");
  },
  async refreshHistory() {
    try { state.history = await pywebview.api.history_status(); } catch (e) { return; }
    mm.paintHistory();
  },
  paintHistory() {
    const b = $("#undobtn"), f = $("#redobtn"), st = state.history || {};
    if (b) b.disabled = !st.undo;
    if (f) f.disabled = !st.redo;
    if (b) b.title = st.undo ? `Undo (${st.undo})` : "Nothing to undo";
    if (f) f.title = st.redo ? `Redo (${st.redo})` : "Nothing to redo";
  },

  // ---- 📤 publish studio ----
  async openPublish() {
    const st = $("#studio");
    if (st) st.hidden = false;
    await mm.refreshPublish();
    mm.refreshPlan();
  },
  closePublish() { const st = $("#studio"); if (st) st.hidden = true; },

  async refreshPublish() {
    let r = null;
    try { r = await call("publish_status"); } catch (e) { return; }
    state.pub = r;
    if (r.deps) $("#pubdot").title = r.signed_in ? "YouTube connected" : "YouTube not connected";
    const set = (id, v) => { const el = $(id); if (el) el.checked = !!v; };
    const s = r.settings || {};
    set("#pubauto", s.enabled); set("#pubonlywins", s.only_wins);
    if ($("#pubprivacy")) $("#pubprivacy").value = s.privacy || "private";
    if ($("#pubdays")) $("#pubdays").value = s.spread_days || 1;
    if ($("#pubtimes")) $("#pubtimes").value = s.times || "10:00,17:30";
    const dot = $("#pubdot"); if (dot) dot.hidden = !!r.signed_in;
    mm.renderSetup(r);
  },

  // The wizard is data-driven: each step is done / now / later, so the user always sees the
  // one thing to do next instead of a wall of instructions.
  renderSetup(r) {
    const steps = $("#pubsteps"), acts = $("#pubacts"), stat = $("#pubstatus");
    if (!steps) return;
    const okDeps = r.deps, okSecret = !!r.client_secret, okAuth = !!r.signed_in;
    const items = [
      { done: okDeps, title: "Google libraries",
        body: okDeps ? "installed" : `install once: <code>${esc(r.pip)}</code>`,
        act: okDeps ? "" : `<button class="link" onclick="mm.copyText('${esc(r.pip)}')">copy</button>` },
      { done: okSecret, title: "OAuth client (client_secret.json)",
        body: okSecret ? esc(String(r.client_secret).split(/[\\/]/).pop())
                       : `Google Cloud Console ▸ APIs &amp; Services ▸ Credentials ▸ Create credentials ▸ OAuth client ID ▸ <b>Desktop app</b>`,
        act: (okSecret ? "" : `<button class="link" onclick="mm.openConsole()">open console</button> `)
             + `<button class="link" onclick="mm.addSecret()">Add client secret…</button>` },
      { done: okAuth, title: "Sign in to YouTube",
        body: okAuth ? (r.channel ? `signed in as <b>${esc(r.channel)}</b>` : "signed in")
                     : "opens your browser; the app waits for Google to hand back the token",
        act: okAuth ? `<button class="link" onclick="mm.signOut()">sign out</button>`
                    : `<button class="link" onclick="mm.signIn()">Sign in with Google</button>` },
    ];
    let firstOpen = true;
    steps.innerHTML = items.map((s, i) => {
      const cls = s.done ? "done" : (firstOpen ? "now" : "");
      if (!s.done) firstOpen = false;
      return `<li class="${cls}"><span class="n">${s.done ? "✓" : i + 1}</span>
        <span><b>${esc(s.title)}</b><br>${s.body} ${s.act || ""}</span></li>`;
    }).join("");
    if (stat) {
      stat.textContent = r.error ? r.error
        : okAuth ? "Ready to upload" : okSecret ? "Next: sign in" : "Next: add your client secret";
      stat.className = r.error ? "hint bad" : "hint";
    }
    if (acts) acts.innerHTML = okAuth && r.channel
      ? `<img class="th" src="${esc(r.thumb)}" alt="" style="width:26px;height:26px;border-radius:6px">
         <span class="hint">${esc(r.channel)}</span>`
      : "";
  },

  async addSecret() {
    const r = await call("publish_add_secret");
    if (r.cancelled) return;
    if (r.error) return toast(r.error);
    toast("Client secret added ✓");
    mm.refreshPublish();
  },
  openConsole() { const r = state.pub || {}; call("publish_open_url", r.console_url || "https://console.cloud.google.com/apis/credentials"); },
  async signIn() {
    const r = await call("publish_sign_in");
    if (r.error) return toast(r.error + (r.pip ? " — " + r.pip : ""));
    toast("Finish sign-in in your browser…");
    const t0 = Date.now();
    const poll = setInterval(async () => {
      let p = null;
      try { p = await pywebview.api.publish_signin_progress(); } catch (e) { clearInterval(poll); return; }
      const steps = $("#pubsteps");
      if (p.url && steps && !document.querySelector(".authurl")) {
        const d = document.createElement("div");
        d.className = "authurl";
        d.innerHTML = `Browser didn't open? <a href="#" onclick="mm.copyText('${esc(p.url)}');return false">copy this link</a>`;
        steps.append(d);
      }
      if (p.done) { clearInterval(poll); toast("Signed in ✓"); mm.refreshPublish(); }
      else if (p.error) { clearInterval(poll); toast(p.error); mm.refreshPublish(); }
      else if (!p.running && Date.now() - t0 > 4000) { clearInterval(poll); mm.refreshPublish(); }
    }, 1200);
  },
  async signOut() {
    const r = await call("publish_sign_out");
    toast(r.error || "Signed out");
    mm.refreshPublish();
  },
  copyText(t) {
    if (navigator.clipboard) navigator.clipboard.writeText(t).then(() => toast("Copied ✓")).catch(() => toast(t));
    else toast(t);
  },
  async savePublish() {
    const patch = {
      enabled: !!($("#pubauto") || {}).checked,
      only_wins: !!($("#pubonlywins") || {}).checked,
      privacy: ($("#pubprivacy") || {}).value || "private",
      spread_days: Math.max(1, Math.min(30, parseInt(($("#pubdays") || {}).value || "1") || 1)),
      times: ($("#pubtimes") || {}).value || "10:00,17:30",
    };
    try { await call("_set_publish_settings", patch); } catch (e) { /* toast shown */ }
    toast(patch.enabled ? "Auto-upload on" : "Auto-upload off");
    mm.refreshPlan();
  },
  paintQuota(q) {
    const box = $("#pubquota");
    if (!box) return;
    if (!q) { box.hidden = true; return; }
    box.hidden = false;
    const over = q.left < 6;
    box.className = "quotabar" + (over ? " low" : "");
    const pct = Math.max(0, Math.min(100, (q.used / Math.max(1, q.limit)) * 100));
    box.innerHTML = `<span>${q.used} of ${q.limit} uploads used today</span>
      <i><b style="width:${pct}%"></b></i>
      <span>${q.left} left · resets 00:00 PT</span>`;
  },
  async refreshPlan() {
    let r = null;
    try { r = await call("publish_plan"); } catch (e) { return; }
    state.plan = r;
    const sum = $("#pubplansum"), box = $("#pubqueue"), go = $("#pubgo");
    if (sum) sum.textContent = r.summary || "";
    mm.paintQuota(r.quota);
    if (box) {
      box.innerHTML = (r.plan || []).map((p, i) => `
        <div class="pubrow ${p.uploaded ? "up" : ""}">
          <div class="t">
            <input value="${esc(p.title)}" title="Title" onchange="mm.editPlan(${i},{title:this.value})">
            <small>${esc(String(p.video || "").split(/[\\/]/).pop())}${p.publish_at ? " · " + esc(p.publish_at.replace("T", " ").replace("Z", "")) : ""}</small>
          </div>
          <select onchange="mm.editPlan(${i},{privacy:this.value})" ${p.uploaded ? "disabled" : ""}>
            ${["private", "unlisted", "public"].map((v) => `<option value="${v}" ${v === p.privacy ? "selected" : ""}>${v}</option>`).join("")}
          </select>
          ${p.uploaded ? `<span class="pubbadge" title="already uploaded">✓</span>` : `<span></span>`}
        </div>`).join("") || `<div class="hint">Render a video (or a batch) and it shows up here.</div>`;
    }
    if (go) go.disabled = !(r.todo > 0);
  },
  editPlan(i, patch) { call("publish_update_plan", i, patch).catch(() => {}); },
  async startUpload() {
    if ($("#pubdry") && $("#pubdry").checked) return toast("Dry run: nothing is uploaded");
    const ok = await call("publish_upload", null);
    if (!ok) return toast("Already uploading, or nothing to upload");
    const prog = $("#pubprog"); if (prog) prog.hidden = false;
  },
  // progress frames from Python (pub / pubdone) are pushed with the render progress
  pubProgress(m) {
    const prog = $("#pubprog"), bar = $("#pubbar"), text = $("#pubptext");
    if (prog) prog.hidden = false;
    if (bar) bar.style.width = (m.n ? ((m.i + (m.p || 0)) / m.n) * 100 : 0).toFixed(1) + "%";
    if (text) text.textContent = `Uploading ${m.i + 1} of ${m.n}${m.title ? " · " + m.title : ""}`;
  },
  pubDone(m) {
    const prog = $("#pubprog"); if (prog) prog.hidden = true;
    const box = $("#pubresults");
    if (m.error) { toast(m.error); return; }
    const rows = (m.results || []).map((r) => r.error
      ? `<div class="bad">✗ ${esc(String(r.video || "").split(/[\\/]/).pop())} — ${esc(r.error)}</div>`
      : `<div>✓ <a href="#" onclick="mm.openVideo('${esc(r.url || "")}');return false">${esc(r.title || String(r.video).split(/[\\/]/).pop())}</a>
           ${r.publish_at ? `<span class="hint">scheduled ${esc(r.publish_at.replace("T", " ").replace("Z", ""))}</span>` : ""}</div>`).join("");
    if (box) box.innerHTML = rows || `<div class="hint">${esc(m.note || "Nothing uploaded")}</div>`;
    toast(m.note || "Upload finished");
    mm.refreshPlan();
  },
  openVideo(url) { if (url) call("publish_open_url", url); },

  // ---- preflight: what would stop this render (checked in Python, offline) ----
  togglePreflight() {
    const list = $("#pflist"), head = $(".pfhead");
    if (!list) return;
    list.hidden = !list.hidden;
    if (head) head.setAttribute("aria-expanded", String(!list.hidden));
  },
  // ---- settings search: find any control by label or key ----
  search(q) {
    q = (q === undefined ? ($("#setsearch") || {}).value || "" : q).trim().toLowerCase();
    const info = $("#searchinfo"), clear = $("#clearsearch");
    document.querySelectorAll(".row").forEach((r) => r.classList.remove("hit"));
    document.querySelectorAll("details").forEach((d) => {
      d.classList.remove("hit");
      // a searching section hides the sections that have nothing to show
      d.classList.toggle("searching", !!q);
    });
    if (!q) {
      if (info) info.hidden = true;
      if (clear) clear.hidden = true;
      document.querySelectorAll("details").forEach((d) => { d.hidden = false; });
      fill();
      return;
    }
    if (clear) clear.hidden = false;
    let hits = 0;
    document.querySelectorAll("details").forEach((d) => {
      let own = 0;
      d.querySelectorAll(".row").forEach((r) => {
        const label = (r.textContent || "").toLowerCase();
        const key = [...r.querySelectorAll("[data-k],[data-csv],[data-l]")].map((el) => (el.dataset.k || el.dataset.csv || el.dataset.l || "")).join(" ").toLowerCase();
        if (label.includes(q) || key.includes(q)) { r.classList.add("hit"); own++; hits++; }
      });
      const head = (d.querySelector("summary") || {}).textContent || "";
      if (head.toLowerCase().includes(q)) { own++; hits++; d.classList.add("hit"); }
      d.classList.toggle("searching", own === 0);
      if (own) d.open = true;
    });
    if (info) {
      info.hidden = false;
      info.textContent = hits ? `${hits} match(es) for “${q}”` : `Nothing matches “${q}” — try “sound”, “speed”, “colour” or a mode name`;
    }
  },
  clearSearch() { const el = $("#setsearch"); if (el) el.value = ""; mm.search(""); },
  // ---- update center ----
  async openUpdate() {
    const panel = $("#updpanel");
    if (panel && !panel.hidden) return mm.closeUpdate();
    if (panel) panel.hidden = false;
    if (state.update) return mm.renderUpdate(state.update);
    mm.renderUpdate(null, "Checking GitHub for a newer build…");
    let r = null;
    try { r = await call("update_check"); } catch (e) { /* toast shown */ }
    state.update = r || { error: "check failed", current: state.version };
    mm.renderUpdate(state.update);
    mm.paintUpdateBadge();
  },
  closeUpdate() { const p = $("#updpanel"); if (p) p.hidden = true; },
  paintUpdateBadge() {
    const u = state.update || {}, btn = $("#updbtn"), dot = $("#upddot"), label = $("#updlabel"), icon = $("#updicon");
    if (dot) dot.hidden = !u.newer;
    if (btn) btn.classList.toggle("new", !!u.newer);
    if (label) label.textContent = u.newer ? `Update ${u.latest} ready` : "Check for updates";
    if (icon) icon.textContent = u.newer ? "🚀" : "🔄";
  },
  renderUpdate(u, note) {
    const body = $("#updbody"), acts = $("#updacts");
    if (!body) return;
    if (!u) {
      body.innerHTML = `<span class="hint">${esc(note || "Checking…")}</span>`;
      if (acts) acts.innerHTML = "";
      return;
    }
    const notes = Array.isArray(u.notes) ? u.notes : [];
    const head = `<div class="updver">You have <b>v${esc(u.current || state.version)}</b>`
      + (u.latest ? ` · newest <b>v${esc(u.latest)}</b>${u.prerelease ? " (nightly)" : ""}` : "") + `</div>`;
    if (u.error) {
      body.innerHTML = head + `<div class="hint">${esc(u.error)}</div>`;
      if (acts) acts.innerHTML = `<button class="ghost sm" onclick="mm.openReleases()">Open releases</button>`;
      return;
    }
    if (!u.newer) {
      body.innerHTML = head + `<div class="hint">You are up to date 🎉</div>`;
      if (acts) acts.innerHTML = `<button class="ghost sm" onclick="mm.openReleases()">Release notes</button>`;
      return;
    }
    body.innerHTML = head + (notes.length
      ? `<ul>${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`
      : `<div class="hint">A newer build is available.</div>`);
    if (acts) acts.innerHTML = (state.frozenHint === false
      ? `<button class="ghost sm" onclick="mm.openReleases()">Open release page</button>`
      : `<button class="primary sm" onclick="mm.downloadUpdate()">Download ${esc(u.latest)}</button>
         <button class="ghost sm" onclick="mm.openReleases()">Release page</button>`);
  },
  async downloadUpdate() {
    const acts = $("#updacts");
    if (acts) acts.innerHTML = `<span class="hint">Downloading…</span>`;
    const r = await call("update_download");
    if (r.error) { toast(r.error); mm.renderUpdate(state.update); return; }
    state.updateFile = r.file;
    toast(`Downloaded ${(r.size / 1048576).toFixed(1)} MB ✓`);
    if (acts) acts.innerHTML = `<button class="primary sm" onclick="mm.installUpdate()">Restart &amp; install</button>
      <button class="ghost sm" onclick="mm.openReleases()">Later</button>`;
  },
  async installUpdate() {
    if (!state.updateFile) return toast("Download the update first");
    const r = await call("update_install", state.updateFile);
    if (r.error) return toast(r.error);
    toast(r.restarted ? "Installing — the app is restarting…" : "Installed. Start the app again to use it.");
  },
  openReleases() {
    const u = state.update || {};
    call("open_url", u.url || "https://github.com/TeamRealHacker/money-maker-911/releases");
  },
  async renderOne() {
    if (!(await call("render_one"))) return toast("Already rendering, hold on…");
    mm.progress({ i: 0, n: 1, p: 0 });
  },
  async renderBatch() {
    const n = Math.max(1, Math.min(500, parseInt($("#count").value || "10") || 10));
    if (!(await call("render_batch", n, $("#rand").checked, $("#wins").checked))) return toast("Already rendering, hold on…");
    mm.progress({ i: 0, n, p: 0 });
  },
};
window.mm = mm;

function swatches(el, onPick, current) {
  el.innerHTML = "";
  for (const [name, p] of Object.entries(state.palettes)) {
    const b = document.createElement("b");
    b.title = name;
    b.style.background = `linear-gradient(135deg, ${p.bg_top} 0 50%, ${p.tiers[4]} 50% 100%)`;
    if (name === current) b.className = "on";
    b.onclick = () => onPick(name);
    el.appendChild(b);
  }
}

function toast(msg) {
  let t = $(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg; clearTimeout(t._h); t._h = setTimeout(() => t.remove(), 2600);
}

const esc = (v) => String(v || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

async function tiers(rows) {
  rows = rows || await pywebview.api.tier_previews();
  $("#tierlist").innerHTML = rows.map((r) => `
    <div class="tier" title="${r.image ? esc(r.image) : "Tier " + (r.i + 1)}">
      <img src="data:image/png;base64,${r.png}" alt="" onclick="mm.tierImage(${r.i})" oncontextmenu="event.preventDefault();mm.clearTierImage(${r.i})" title="Click: choose a picture for form ${r.i + 1}${r.image ? " (" + esc(r.image) + "). Right-click: remove picture" : ""}">${r.cut ? '<i class="cut" title="AI cut-out">✂️</i>' : ""}
      <input type="text" value="${esc(r.name)}" placeholder="Tier ${r.i + 1} name" onchange="mm.setTier(${r.i},'name',this.value)">
      <input type="text" class="emo" value="${esc(r.emoji)}" placeholder="🙂" maxlength="8" onchange="mm.setTier(${r.i},'emoji',this.value)">
      <input type="color" value="${r.color}" onchange="mm.setTier(${r.i},'color',this.value)" ondblclick="mm.setTier(${r.i},'color','')" title="Colour (double-click = palette colour)">
    </div>`).join("");
}

function aiModels() {
  const st = state.cutout; if (!st) return;
  $("#cutmodel").innerHTML = st.models.map((m) => {
    const off = (m.id !== "quick" && !st.onnx) || m.too_big;
    return `<option value="${m.id}" ${off ? "disabled" : ""}>${m.ready && m.id !== "quick" ? "✓ " : ""}${esc(m.label)}</option>`;
  }).join("");
  $("#cutmodel").value = state.config.cutout_model;
}

function aiHint(r) {
  const c = state.config, st = state.cutout || {}, el = $("#aistatus");
  const bits = [];
  if (!st.onnx && (c.ai_cutout || c.reject_text))
    bits.push("AI add-on missing (pip install onnxruntime): Quick cut-out only, text check off.");
  if (r) {
    if (c.ai_cutout) bits.push(`${r.cut} of ${r.images} image(s) cut out.`);
    if (c.reject_text) bits.push(r.skipped.length ? `Skipped ${r.skipped.length} with text: ${r.skipped.slice(0, 3).join(", ")}${r.skipped.length > 3 ? "…" : ""}` : "No text found.");
    if (r.errors.length) bits.push("⚠ " + r.errors[0]);
  } else if (c.ai_cutout || c.reject_text) {
    bits.push("Runs offline. The model downloads once on first use.");
  }
  el.textContent = bits.join(" ");
}

async function soundRows(rows) {
  rows = rows || await pywebview.api.sound_rows();
  $("#stiers").innerHTML = rows.map((r) => `
    <div class="stier">
      <b>${esc(r.label)}</b>
      <span class="${r.own ? "own" : ""}" title="${esc(r.sound)}">${esc(r.sound)}</span>
      <button class="play" onclick="mm.previewTier('${r.key}')" title="Hear it">▶</button>
      <input type="number" step="0.1" value="${r.manual ? r.pitch : ""}" placeholder="${r.pitch}" title="Semitones" onchange="mm.setPitch('${r.key}', this.value)">
      <button class="link xs" onclick="mm.pickSound('${r.key}')" title="Choose a file">file</button>
      <button class="link xs" onclick="mm.clearSound('${r.key}')" title="Reset">×</button>
    </div>`).join("");
}

function themes(list) {
  $("#themes").innerHTML = `<option value="">Saved themes…</option>` + (list || []).map((t) => `<option>${esc(t)}</option>`).join("");
}

function textStyles() {
  document.querySelectorAll(".textstyle").forEach((el) => {
    const p = el.dataset.p;
    el.innerHTML = `
      <div class="row"><span>Size</span><input type="range" data-k="${p}_size" min="16" max="140"></div>
      <div class="row"><span>Height</span><input type="range" data-k="${p}_y" min="0.02" max="0.97" step="0.005"></div>
      <div class="row"><span>Colour</span><span><input type="color" data-k="${p}_color" data-def="#FFFFFF"><button class="link" onclick="mm.set({${p}_color:''})">palette</button></span></div>
      <div class="row"><span>Font</span><span><button class="ghost sm" onclick="mm.pick('${p}_font_path','font')">.ttf…</button><button class="link" onclick="mm.set({${p}_font_path:''})">default</button></span></div>`;
  });
}

function knobs() {
  $("#knobs").innerHTML = Object.entries(state.random_knobs || {}).map(([k, label]) =>
    `<label class="chk"><input type="checkbox" data-knob="${k}"> ${esc(label)}</label>`).join("");
  document.querySelectorAll("[data-knob]").forEach((el) => el.addEventListener("change", () => {
    const on = [...document.querySelectorAll("[data-knob]")].filter((x) => x.checked).map((x) => x.dataset.knob);
    mm.set({ random_knobs: on });
  }));
}

function lengths() {
  const cur = state.config.max_seconds;
  $("#lengths").innerHTML = Object.entries(state.lengths).map(([k, v]) =>
    `<button class="${Math.abs(cur - v) < 0.5 ? "on" : ""}" onclick="mm.set({max_seconds:${v}})">${k}</button>`).join("");
}

// ---- v0.23.0 mode sections (bowling, stacker, bubble, hole, zoom) ----
const MODE_SECTIONS_V023 = `
  <details open data-modes="bowling"><summary>🎳 Bowling Strike</summary>
    <div class="row"><span>Pins</span><input type="range" data-k="bowling_pins" min="1" max="15"></div>
    <div class="row"><span>Rows</span><input type="range" data-k="bowling_rows" min="1" max="8"></div>
    <div class="row"><span>Pin size</span><input type="range" data-k="bowling_pin_radius" min="8" max="40"></div>
    <div class="row"><span>Pin toughness</span><input type="range" data-k="bowling_pin_hp" min="1" max="3"></div>
    <div class="row"><span>Pin spread</span><input type="range" data-k="bowling_pin_spread" min="0.8" max="2" step="0.1"></div>
    <div class="row"><span>Ball size</span><input type="range" data-k="bowling_ball_radius" min="14" max="60"></div>
    <div class="row"><span>Throw speed</span><input type="range" data-k="bowling_speed" min="400" max="2500" step="25"></div>
    <div class="row"><span>Max throws</span><input type="range" data-k="bowling_max_throws" min="1" max="30"></div>
    <div class="row col"><span>Counter <em class="hint">{broken} {total}</em></span><input type="text" data-k="bowling_counter_text"></div>
    <div class="row col"><span>Ending text</span><input type="text" data-k="bowling_final_text"></div>
    <div class="hint">The ball is thrown from the bottom and re-thrown until every pin is down.</div>
  </details>
  <details open data-modes="stacker"><summary>🏗️ Tower Stack</summary>
    <div class="row"><span>Blocks to stack</span><input type="range" data-k="stacker_target" min="2" max="40"></div>
    <div class="row"><span>Block width</span><input type="range" data-k="stacker_block_w" min="60" max="300" step="5"></div>
    <div class="row"><span>Block height</span><input type="range" data-k="stacker_block_h" min="20" max="110" step="2"></div>
    <div class="row"><span>Clean-drop window</span><input type="range" data-k="stacker_tolerance" min="0.15" max="1.2" step="0.05"></div>
    <div class="row"><span>Sloppy drops before topple</span><input type="range" data-k="stacker_miss_limit" min="1" max="10"></div>
    <div class="row"><span>Crane sway</span><input type="range" data-k="stacker_swing" min="0" max="1.2" step="0.05"></div>
    <div class="row"><span>Sway period</span><input type="range" data-k="stacker_swing_period" min="1" max="10" step="0.2"></div>
    <div class="row"><span>Seconds between blocks</span><input type="range" data-k="stacker_interval" min="0.25" max="5" step="0.05"></div>
    <div class="row col"><span>Counter <em class="hint">{broken} {total}</em></span><input type="text" data-k="stacker_counter_text"></div>
    <div class="row col"><span>Ending text</span><input type="text" data-k="stacker_final_text"></div>
    <div class="hint">Blocks are real physics: they land, settle and freeze into the tower.</div>
  </details>
  <details open data-modes="bubble"><summary>🫧 Bubble Pop</summary>
    <div class="row"><span>Bubbles to pop</span><input type="range" data-k="bubble_target" min="5" max="200"></div>
    <div class="row"><span>Spawn every (s)</span><input type="range" data-k="bubble_spawn_interval" min="0.05" max="3" step="0.05"></div>
    <div class="row"><span>Bubble size</span><input type="range" data-k="bubble_radius" min="14" max="80"></div>
    <div class="row"><span>Rise speed</span><input type="range" data-k="bubble_speed" min="40" max="500" step="10"></div>
    <div class="row"><span>Wobble</span><input type="range" data-k="bubble_wobble" min="0" max="100"></div>
    <div class="row"><span>Ball size</span><input type="range" data-k="bubble_ball_radius" min="10" max="60"></div>
    <div class="row"><span>Ball speed</span><input type="range" data-k="bubble_ball_speed" min="300" max="2000" step="25"></div>
    <div class="row col"><span>Counter <em class="hint">{broken} {total}</em></span><input type="text" data-k="bubble_counter_text"></div>
    <div class="row col"><span>Ending text</span><input type="text" data-k="bubble_final_text"></div>
    <div class="hint">Bubbles rise from the bottom; your ball hunts them down.</div>
  </details>
  <details open data-modes="hole"><summary>🕳️ Hole Eater</summary>
    <div class="row"><span>Balls</span><input type="range" data-k="hole_balls" min="2" max="120"></div>
    <div class="row"><span>Hole size</span><input type="range" data-k="hole_radius" min="20" max="140"></div>
    <div class="row"><span>Growth per ball</span><input type="range" data-k="hole_growth" min="0" max="0.2" step="0.005"></div>
    <div class="row"><span>Hole speed</span><input type="range" data-k="hole_speed" min="60" max="900" step="10"></div>
    <div class="row"><span>Ball drift</span><input type="range" data-k="hole_drift" min="50" max="800" step="10"></div>
    <div class="row"><span>Ball size</span><input type="range" data-k="hole_ball_radius" min="10" max="60"></div>
    <div class="row"><span>Balls flee</span><input type="range" data-k="hole_flee" min="0" max="1" step="0.05"></div>
    <div class="row col"><span>Counter <em class="hint">{broken} {total}</em></span><input type="text" data-k="hole_counter_text"></div>
    <div class="row col"><span>Ending text</span><input type="text" data-k="hole_final_text"></div>
    <div class="hint">The hole always catches up. Balls wear your Tiers pictures.</div>
  </details>
  <details open data-modes="zoom"><summary>♾️ Infinite Zoom</summary>
    <div class="row"><span>Stairs</span><input type="range" data-k="zoom_target" min="3" max="60"></div>
    <div class="row"><span>Zoom per step</span><input type="range" data-k="zoom_growth" min="1.1" max="2" step="0.02"></div>
    <div class="row"><span>First step (s)</span><input type="range" data-k="zoom_step_time" min="0.3" max="2" step="0.05"></div>
    <div class="row"><span>Slower every step</span><input type="range" data-k="zoom_slow" min="1" max="1.2" step="0.01"></div>
    <div class="row"><span>Platform width</span><input type="range" data-k="zoom_platform_w" min="0.35" max="0.9" step="0.05"></div>
    <div class="row"><span>Line glow</span><input type="range" data-k="zoom_glow" min="0" max="1" step="0.05"></div>
    <div class="row"><span>Stars</span><input type="range" data-k="zoom_stars" min="0" max="600" step="10"></div>
    <div class="row"><span>Star twinkle</span><input type="range" data-k="zoom_star_twinkle" min="0" max="1" step="0.05"></div>
    <div class="row"><span>Spin</span><input type="range" data-k="zoom_ball_spin" min="0" max="8" step="0.2"></div>
    <div class="row"><span>First bounce pitch</span><input type="range" data-k="zoom_pitch_start" min="-6" max="12" step="0.5"></div>
    <div class="row"><span>Deeper per step</span><input type="range" data-k="zoom_pitch_drop" min="0" max="2" step="0.05"></div>
    <div class="row col"><span>Line colour</span><span><input type="color" data-k="zoom_line_color" data-def="#35C8FF"><button class="link" onclick="mm.set({zoom_line_color:'#35C8FF'})">reset</button></span></div>
    <div class="row col"><span>Counter <em class="hint">{broken} {total}</em></span><input type="text" data-k="zoom_counter_text"></div>
    <div class="row col"><span>Ending text</span><input type="text" data-k="zoom_final_text"></div>
    <div class="hint">Dark-mode neon stairs in a star space; the camera zooms forever and every bounce sounds deeper.</div>
  </details>
`;

function injectModeSections() {
  const anchor = document.querySelector('[data-modes="battle weapon"]');
  if (anchor && !document.querySelector('[data-modes="zoom"]')) {
    anchor.insertAdjacentHTML("beforebegin", MODE_SECTIONS_V023);
    // boot() runs bindInputs() right after modeNav(), which wires these fresh controls
  }
}

function modeNav() {
  const cur = (state.config && state.config.mode) || "merge";
  $("#modes").innerHTML = MODES.map(([n, key]) => key
    ? `<a class="${key === cur ? "on" : "ready"}" data-mode="${key}" onclick="mm.setMode('${key}')">${n}</a>`
    : `<a class="off">${n}<em>Soon</em></a>`).join("");
}
function fill() {
  const c = state.config;
  const mode = c.mode || "merge";
  document.querySelectorAll("[data-modes]").forEach((el) => { el.hidden = !el.dataset.modes.split(" ").includes(mode); });
  document.querySelectorAll("#modes a[data-mode]").forEach((a) => a.classList.toggle("on", a.dataset.mode === mode));
  const mt = MODES.find((m) => m[1] === mode);
  if ($("#modetitle") && mt) $("#modetitle").textContent = mt[0].replace(/^\S+\s/, "");
  if ($("#winslabel")) $("#winslabel").textContent = { merge: "Only Final Form wins", escape: "Only full escapes", breaker: "Only cleared walls", glass: "Only fully shattered", ghost: "Only full escapes", rhythmic: "Only full escapes", accumulate: "Only reached target", drawer: "Only fully painted", tower: "Only fully shattered", battle: "Only a clear winner", weapon: "Only a clear winner", plinko: "Only reached the jackpot", race: "Only a clear winner", flip: "Only reached target", snake: "Only reached target", chain: "Only full chains", countdown: "Only one survivor", colorsort: "Only fully sorted", voting: "Only a clear winner", bowling: "Only a STRIKE", stacker: "Only full towers", bubble: "Only all popped", hole: "Only all eaten", zoom: "Only reached INFINITE" }[mode] || "Only wins";
  document.querySelectorAll("[data-k]").forEach((el) => {
    if (el === document.activeElement && el.type === "text") return;   // don't fight the user's typing
    const v = c[el.dataset.k];
    if (el.type === "checkbox") el.checked = !!v;
    else if (el.type === "color") el.value = /^#[0-9a-f]{6}$/i.test(v || "") ? v : (el.dataset.def || "#000000");
    else el.value = v;
    if (el.type === "range") showVal(el);
  });
  document.querySelectorAll("[data-l]").forEach((el) => {
    const lst = c[el.dataset.l] || [], v = lst[+el.dataset.i];
    el.value = /^#[0-9a-f]{6}$/i.test(v || "") ? v : el.dataset.def;
    el.style.opacity = v ? 1 : 0.45;
  });
  document.querySelectorAll("[data-csv]").forEach((el) => { if (el !== document.activeElement) el.value = (c[el.dataset.csv] || []).join(", "); });
  document.querySelectorAll("[data-knob]").forEach((el) => (el.checked = (c.random_knobs || []).includes(el.dataset.knob)));
  $("#custompts").hidden = c.container_shape !== "custom";
  if (c.container_shape === "custom" && document.activeElement !== $("#ptsbox")) $("#ptsbox").value = JSON.stringify(c.container_points || []);
  $("#customsizes").hidden = c.size_curve !== "custom";
  $("#bgname").textContent = c.bg_mode === "image" ? (c.background_image ? c.background_image.split(/[\\/]/).pop() : "Pick an image")
    : c.bg_mode === "video" ? (c.background_video ? c.background_video.split(/[\\/]/).pop() + " (loops)" : "Pick a video") : "";
  swatches($("#palettes"), (n) => mm.set({ palette: n }), c.palette);
  $("#imgcount").textContent = c.tier_image_folder ? "Folder: " + c.tier_image_folder.split(/[\\/]/).pop() + " (sorted by name)"
    : c.tier_images.length ? `${c.tier_images.length} image(s) loaded` : "Folder or files, one image per tier, smallest first. Name them 1, 2, 3…";
  if (state.lengths) lengths();
  $("#soundname").textContent = c.auto_sounds ? "New Myinstants sounds are fetched for every render (" + (c.auto_sound_keywords || "satisfying list") + ")"
    : c.tier_sounds.length ? `${new Set(c.tier_sounds.filter(Boolean)).size} different sounds across the tiers`
    : c.sound_path ? c.sound_path.split(/[\\/]/).pop() : "Built-in pop. Search Myinstants above or drop any file.";
  $("#outdir").textContent = state.output_dir || "";
  $("#musicname").textContent = c.music_path ? c.music_path.split(/[\\/]/).pop() : "No background music.";
  const res = { "720p": "720×1280", "1080p": "1080×1920", "1440p": "1440×2560", "4k": "2160×3840" }[c.export_resolution] || "";
  $("#exportsum").textContent = `${res} · ${c.fps} fps · ${c.export_codec.toUpperCase()} · ${c.export_format.toUpperCase()}${c.export_audio ? "" : " · no audio"}`;
  if (sfx.bufKey && sfx.bufKey !== (c.sound_path || "") + "|") sfx.load();
}

// Preflight: ask Python what would stop this render, and show it right above the Render button.
// Runs debounced (it is cheap and offline) so the banner is always about the current settings.
let pfTimer = null;
function paintPreflight() {
  clearTimeout(pfTimer);
  pfTimer = setTimeout(async () => {
    let r = null;
    try { r = await pywebview.api.preflight(); } catch (e) { return; }
    const box = $("#preflight"), sum = $("#pfsum"), icon = $("#pficon"), list = $("#pflist");
    if (!box || !r) return;
    state.preflight = r;
    const errs = r.items.filter((i) => i.level === "error");
    const warns = r.items.filter((i) => i.level === "warning");
    const show = errs.length + warns.length > 0;
    box.hidden = !show;
    box.classList.toggle("bad", errs.length > 0);
    box.classList.toggle("warn", errs.length === 0 && warns.length > 0);
    if (!show) return;
    icon.textContent = errs.length ? "⚠" : "!";
    sum.textContent = r.summary || (errs.length ? `${errs.length} problem(s)` : `${warns.length} warning(s)`);
    const shown = [...errs, ...warns, ...r.items.filter((i) => i.level === "info")];
    list.innerHTML = shown.map((i) => `
      <li class="lv-${esc(i.level)}"><span class="dot">${i.level === "error" ? "●" : i.level === "warning" ? "●" : "·"}</span>
        <b>${esc(i.area)}</b><span>${esc(i.message)}${i.fix ? ` <em>— ${esc(i.fix)}</em>` : ""}</span>
        <button class="link" onclick="mm.reveal('${esc(i.key || "")}')">${i.key && (document.querySelector(`[data-k="${i.key}"]`) || document.querySelector(`[data-csv="${i.key}"]`)) ? "fix" : "show"}</button>
      </li>`).join("");
  }, 220);
}

// Jump to the control a preflight item is about, so "fix" is one click.
mm.reveal = function (key) {
  const el = key && document.querySelector(`[data-k="${key}"],[data-csv="${key}"]`);
  if (el) {
    const d = el.closest("details");
    if (d) { d.open = true; scrollTo(d); }
    el.classList.add("hit");
    setTimeout(() => el.classList.remove("hit"), 1600);
    try { if (el.focus) el.focus({ preventScroll: true }); } catch (e) { /* not focusable */ }
    return;
  }
  // picker-driven settings (sound, pictures, output folder) have no control of their own:
  // open the section that owns them so the button you need is on screen
  const area = ((state.preflight || {}).items || []).find((i) => i.key === key) || {};
  const word = (key || area.area || "").toLowerCase().split("_")[0];
  const sec = [...document.querySelectorAll("details[data-sec]")]
    .find((d) => (d.dataset.sec || "").split(" ").some((w) => w === word || w.startsWith(word.slice(0, 4))));
  if (sec) scrollTo(sec);
};

// scrollIntoView is not present in every embedded engine/jsdom; never let it break a click
function scrollTo(el) {
  if (!el) return;
  try { el.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) { /* no scrolling here */ }
}

function showVal(el) {
  let o = el.nextElementSibling;
  if (!o || !o.classList.contains("v")) { o = document.createElement("i"); o.className = "v"; el.after(o); }
  const n = parseFloat(el.value);
  o.textContent = Math.abs(n) >= 100 || Number.isInteger(n) ? Math.round(n) : n.toFixed(2).replace(/0$/, "");
}

function bindInputs() {
  const pv = $("#pvsound");
  if (pv) { pv.checked = sfx.on; pv.onchange = () => { sfx.on = pv.checked; localStorage.setItem("mm_pvsound", pv.checked ? "1" : "0"); if (sfx.on) { sfx.ensure(); sfx.load(); } }; }
  document.querySelectorAll("[data-k]").forEach((el) => {
    const ev = el.type === "text" || el.type === "number" ? "change" : "input";
    el.addEventListener(ev, () => {
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (el.type === "range" || el.type === "number" || (el.tagName === "SELECT" && v !== "" && !isNaN(v))) v = parseFloat(v);
      if (el.type === "range") showVal(el);
      if (el.type === "range" || el.type === "color") queueSet({ [el.dataset.k]: v }); else mm.set({ [el.dataset.k]: v });
    });
  });
  document.querySelectorAll("[data-l]").forEach((el) => el.addEventListener("input", () => {
    const key = el.dataset.l, lst = [...(state.config[key] || [])];
    while (lst.length <= +el.dataset.i) lst.push(lst.length ? "#E2ECE9" : "#FDE2E4");
    lst[+el.dataset.i] = el.value;
    queueSet({ [key]: lst, bg_mode: lst.length === 1 ? "solid" : "gradient" });
  }));
  document.querySelectorAll("[data-csv]").forEach((el) => el.addEventListener("change", () => {
    let parts = el.value.split(",").map((x) => x.trim()).filter(Boolean);
    if (el.dataset.csv === "tier_sizes") parts = parts.map(parseFloat).filter((n) => n > 0);
    mm.set({ [el.dataset.csv]: parts });
  }));
  $("#sq").addEventListener("keydown", (e) => { if (e.key === "Enter") mm.soundSearch(); });
}

function onboarding() {
  const ob = $("#onboard");
  ob.hidden = false;
  let s = 0, pal = state.config.palette, finishing = false;
  const steps = [...document.querySelectorAll(".step")], dots = [...document.querySelectorAll(".dots i")];
  const last = steps.length - 1;
  const markPal = () => document.querySelectorAll("#obpal b").forEach((b) => b.classList.toggle("on", b.title === pal));
  swatches($("#obpal"), (n) => { pal = n; markPal(); }, pal);   // build once, not on every step
  const draw = () => {
    steps.forEach((el, i) => (el.hidden = i !== s));
    dots.forEach((d, i) => d.classList.toggle("on", i === s));
    $("#obback").style.visibility = s ? "visible" : "hidden";
    $("#obnext").textContent = s === last ? "Get started" : "Continue";
  };
  let forms = state.config.tiers;
  const drawForms = () => {
    const lo = state.min_tiers || 3, hi = Math.min(12, state.max_tiers || 15);
    let html = "";
    for (let n = lo; n <= hi; n++) html += `<button class="${n === forms ? "on" : ""}" data-n="${n}">${n}</button>`;
    $("#obforms").innerHTML = html;
    $("#obforms").querySelectorAll("button").forEach((b) => (b.onclick = () => { forms = +b.dataset.n; drawForms(); }));
  };
  drawForms();
  const afterImages = async () => {
    state.config = (await call("bootstrap")).config; forms = state.config.tiers; drawForms(); fill(); tiers();
    const n = state.config.tier_image_folder ? "Folder" : state.config.tier_images.length + " picture(s)";
    $("#obimghint").textContent = `${n} loaded · ${forms} forms`;
  };
  $("#obimgfiles").onclick = async () => { await call("pick_images"); afterImages(); };
  $("#obimgfolder").onclick = async () => { await call("pick_image_folder"); afterImages(); };
  const close = () => { ob.hidden = true; state.onboarded = true; setPreview(true); };
  $("#obback").onclick = () => { s = Math.max(0, s - 1); draw(); };
  $("#obnext").onclick = async () => {
    if (s < last) { s++; draw(); return; }
    if (finishing) return;            // double clicks used to fire this twice
    finishing = true;
    $("#obnext").disabled = true;
    const theme = $("#obtheme").value.trim() || "Fruit";
    try {
      await call("finish_onboarding", { palette: pal, theme_name: theme, tiers: forms });
      state.config.palette = pal; state.config.theme_name = theme; state.config.tiers = forms; fill(); tiers();
    } catch (e) { /* settings will be asked again next launch, but never trap the user */ }
    finally { $("#obnext").disabled = false; finishing = false; close(); }
  };
  document.addEventListener("keydown", function key(e) {
    if (ob.hidden) return document.removeEventListener("keydown", key);
    if (e.key === "Enter" && e.target.tagName !== "INPUT") $("#obnext").click();
    if (e.key === "Escape") { call("finish_onboarding", { palette: pal }).catch(() => {}); close(); }
  });
  draw();
}

async function boot() {
  if (booted || !window.pywebview || !pywebview.api || !pywebview.api.bootstrap) return;
  booted = true;
  try {
    state = await pywebview.api.bootstrap();
  } catch (e) {
    booted = false; setTimeout(boot, 300); return;   // API not wired yet, retry
  }
  $("#ver").textContent = "v" + state.version;
  modeNav();
  injectModeSections();
  $("#shapes").innerHTML = state.shapes.map((s) => `<option>${s}</option>`).join("");
  $("#hooks").innerHTML = state.hooks.map((h) => `<option value="${esc(h)}">`).join("");
  $("#emojiset").innerHTML += Object.entries(state.emoji_sets).map(([k, v]) => `<option value="${k}">${v.slice(0, 3).join("")} ${k}</option>`).join("");
  $("#emojiset").onchange = (e) => mm.emojiSet(e.target.value);
  $("#bgmodes").innerHTML = (state.bg_modes || []).map((s) => `<option>${s}</option>`).join("");
  $("#curves").innerHTML = (state.size_curves || []).map((s) => `<option>${s}</option>`).join("");
  $("#pstyles").innerHTML = (state.particle_styles || []).map((s) => `<option>${s}</option>`).join("");
  $("#kwchips").innerHTML = (state.keywords || []).map((k) => `<button onclick="mm.soundSearch('${esc(k)}')">${esc(k)}</button>`).join("");
  themes(state.themes);
  textStyles();
  knobs();
  aiModels();
  bindInputs();
  fill();
  aiHint();
  mm.prep().catch(() => {});   // cached after the first run, so this is instant
  soundRows().catch(() => {});
  const search = $("#setsearch");
  if (search) {
    let st = null;
    search.addEventListener("input", () => { clearTimeout(st); st = setTimeout(() => mm.search(), 140); });
  }
  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || "");
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); return mm.openPalette(); }
    if (mod && e.key.toLowerCase() === "r") { e.preventDefault(); return e.shiftKey ? mm.renderBatch() : mm.renderOne(); }
    if (mod && e.key.toLowerCase() === "p") { e.preventDefault(); return mm.openPublish().then(() => mm.startUpload()); }
    if (mod && e.key.toLowerCase() === "l") { e.preventDefault(); return mm.openLibrary(); }
    if (mod && e.key.toLowerCase() === "z") {
      e.preventDefault();
      return e.shiftKey ? mm.redo() : mm.undo();
    }
    if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); return mm.redo(); }
    if (e.key === "/" && !typing) { e.preventDefault(); if (search) search.focus(); }
    if (e.key === "?" && !typing) { e.preventDefault(); return mm.showShortcuts(); }
    if (e.key === "Escape" && document.activeElement === search) mm.clearSearch();
    if (e.key === "Escape") { mm.closePalette(); mm.closeLibrary(); mm.closePublish(); mm.closeColab(); mm.closeShortcuts(); }
  });
  mm.refreshHistory();
  paintPreflight();
  // build the palette index early: it also feeds the shortcuts sheet
  call("palette").then((idx) => { state.palIndex = idx; }).catch(() => {});
  mm.refreshUploadState();
  mm.refreshColabDot();
  if (state.onboarded) setPreview(true); else onboarding();   // preview waits until onboarding is done
}

// pywebviewready can fire before this script runs; handle both orders.
window.addEventListener("pywebviewready", boot);
if (window.pywebview && window.pywebview.api) boot();
