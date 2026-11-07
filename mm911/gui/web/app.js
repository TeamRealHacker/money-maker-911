const MODES = [
  ["🍉 Merge Evolution", true], ["🌀 Escape"], ["🎵 Rhythmic"], ["✏️ Drawer"], ["➕ Accumulate"],
  ["👻 Ghost Escape"], ["🧱 Breaker"], ["🏢 Glass Tower"], ["🚩 Flag Battle"], ["⚔️ Weapon Battle"],
  ["🥛 Glass Rush"], ["🏁 Race"], ["🎯 Plinko"], ["🌊 Wave 3D"], ["🎢 Marble Run 3D"], ["🧲 Magnet 3D"],
];
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
function setPreview(on) {
  if (on === previewOn) return;
  previewOn = on;
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
      const semis = ({ drop: -4, merge: 0, final: 7 }[kind] || 0) + tier * 1.6;
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
  async set(patch) {
    state.config = await call("set_config", patch); fill();
    if (PREP_KEYS.some((k) => k in patch)) mm.prep();
    else if (["tiers", "palette", "tier_images", "show_tier_labels", "cutout_outline"].some((k) => k in patch)) tiers();
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
  async pick(key, kind) {
    const f = await pywebview.api.pick_file(kind);
    if (f) await mm.set({ [key]: f });
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

function lengths() {
  const cur = state.config.max_seconds;
  $("#lengths").innerHTML = Object.entries(state.lengths).map(([k, v]) =>
    `<button class="${Math.abs(cur - v) < 0.5 ? "on" : ""}" onclick="mm.set({max_seconds:${v}})">${k}</button>`).join("");
}

function fill() {
  const c = state.config;
  document.querySelectorAll("[data-k]").forEach((el) => {
    const v = c[el.dataset.k];
    if (el.type === "checkbox") el.checked = !!v; else el.value = v;
  });
  swatches($("#palettes"), (n) => mm.set({ palette: n }), c.palette);
  $("#imgcount").textContent = c.tier_image_folder ? "Folder: " + c.tier_image_folder.split(/[\\/]/).pop() + " (sorted by name)"
    : c.tier_images.length ? `${c.tier_images.length} image(s) loaded` : "Folder or files, one image per tier, smallest first. Name them 1, 2, 3…";
  if (state.lengths) lengths();
  $("#soundname").textContent = c.sound_path ? c.sound_path.split(/[\\/]/).pop() : "Built-in pop. Any Myinstants mp3 works.";
  $("#outdir").textContent = state.output_dir || "";
  $("#musicname").textContent = c.music_path ? c.music_path.split(/[\\/]/).pop() : "No background music.";
  const res = { "720p": "720×1280", "1080p": "1080×1920", "1440p": "1440×2560", "4k": "2160×3840" }[c.export_resolution] || "";
  $("#exportsum").textContent = `${res} · ${c.fps} fps · ${c.export_codec.toUpperCase()} · ${c.export_format.toUpperCase()}${c.export_audio ? "" : " · no audio"}`;
  if (sfx.bufKey && sfx.bufKey !== (c.sound_path || "") + "|") sfx.load();
}

function bindInputs() {
  const pv = $("#pvsound");
  if (pv) { pv.checked = sfx.on; pv.onchange = () => { sfx.on = pv.checked; localStorage.setItem("mm_pvsound", pv.checked ? "1" : "0"); if (sfx.on) { sfx.ensure(); sfx.load(); } }; }
  document.querySelectorAll("[data-k]").forEach((el) => {
    const ev = el.type === "text" ? "change" : "input";
    el.addEventListener(ev, () => {
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (el.type === "range" || (el.tagName === "SELECT" && !isNaN(v))) v = parseFloat(v);
      if (el.type === "range") queueSet({ [el.dataset.k]: v }); else mm.set({ [el.dataset.k]: v });
    });
  });
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
  $("#modes").innerHTML = MODES.map(([n, on]) => `<a class="${on ? "on" : "off"}">${n}${on ? "" : "<em>Soon</em>"}</a>`).join("");
  $("#shapes").innerHTML = state.shapes.map((s) => `<option>${s}</option>`).join("");
  $("#hooks").innerHTML = state.hooks.map((h) => `<option value="${esc(h)}">`).join("");
  $("#emojiset").innerHTML += Object.entries(state.emoji_sets).map(([k, v]) => `<option value="${k}">${v.slice(0, 3).join("")} ${k}</option>`).join("");
  $("#emojiset").onchange = (e) => mm.emojiSet(e.target.value);
  aiModels();
  bindInputs();
  fill();
  aiHint();
  mm.prep().catch(() => {});   // cached after the first run, so this is instant
  if (state.onboarded) setPreview(true); else onboarding();   // preview waits until onboarding is done
}

// pywebviewready can fire before this script runs; handle both orders.
window.addEventListener("pywebviewready", boot);
if (window.pywebview && window.pywebview.api) boot();
