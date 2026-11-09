const MODES = [
  ["🍉 Merge Evolution", "merge"], ["🌀 Escape", "escape"], ["🧱 Breaker", "breaker"], ["🥛 Glass Rush", "glass"], ["👻 Ghost Escape", "ghost"], ["🎵 Rhythmic", "rhythmic"], ["➕ Accumulate", "accumulate"], ["✏️ Drawer", "drawer"],
  ["🏢 Glass Tower"], ["🚩 Flag Battle"], ["⚔️ Weapon Battle"],
  ["🏁 Race"], ["🎯 Plinko"], ["🌊 Wave 3D"], ["🎢 Marble Run 3D"], ["🧲 Magnet 3D"],
];
const MODE_HOOKS = { merge: "Will it reach the Final Form?", escape: "Can it escape all 8 rings?",
  breaker: "Can it break every brick?", glass: "Will the glass hold?", ghost: "Can the ghost escape the dark?", rhythmic: "Can the ball play the whole song?", accumulate: "Can it reach 100 balls?", drawer: "Can it paint the whole picture?" };
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
    state.config = await call("set_config", patch); fill();
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
  async reset() { state.config = await pywebview.api.reset_config(); fill(); },
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
  if ($("#winslabel")) $("#winslabel").textContent = { merge: "Only Final Form wins", escape: "Only full escapes", breaker: "Only cleared walls", glass: "Only fully shattered", ghost: "Only full escapes", rhythmic: "Only full escapes", accumulate: "Only reached target", drawer: "Only fully painted" }[mode] || "Only wins";
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
  if (state.onboarded) setPreview(true); else onboarding();   // preview waits until onboarding is done
}

// pywebviewready can fire before this script runs; handle both orders.
window.addEventListener("pywebviewready", boot);
if (window.pywebview && window.pywebview.api) boot();
