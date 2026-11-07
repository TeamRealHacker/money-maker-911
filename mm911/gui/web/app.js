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
      if (f) { lastFrame = f.id; mm.frame(f.jpg, f.tier, f.t); }
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

// Sliders fire dozens of events a second: send only the last value every 120 ms.
let pending = {}, pendTimer = null;
function queueSet(patch) {
  Object.assign(pending, patch);
  clearTimeout(pendTimer);
  pendTimer = setTimeout(() => { const p = pending; pending = {}; mm.set(p); }, 120);
}

const mm = {
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
    if (["tiers", "palette", "tier_images", "show_tier_labels"].some((k) => k in patch)) tiers();
  },
  async pick(key, kind) {
    const f = await pywebview.api.pick_file(kind);
    if (f) await mm.set({ [key]: f });
  },
  async pickImages() { const imgs = await pywebview.api.pick_images(); state.config.tier_images = imgs; state.config.tier_image_folder = ""; fill(); tiers(); },
  async pickImageFolder() { tiers(await pywebview.api.pick_image_folder()); state.config = (await pywebview.api.bootstrap()).config; fill(); },
  async setTier(i, key, v) { tiers(await pywebview.api.set_tier(i, key, v)); },
  async emojiSet(name) { tiers(await pywebview.api.apply_emoji_set(name)); state.config = (await pywebview.api.bootstrap()).config; fill(); },
  async clearTiers() { tiers(await pywebview.api.clear_tiers()); state.config = (await pywebview.api.bootstrap()).config; fill(); },
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
      <img src="data:image/png;base64,${r.png}" alt="">
      <input type="text" value="${esc(r.name)}" placeholder="Tier ${r.i + 1} name" onchange="mm.setTier(${r.i},'name',this.value)">
      <input type="text" class="emo" value="${esc(r.emoji)}" placeholder="🙂" maxlength="8" onchange="mm.setTier(${r.i},'emoji',this.value)">
      <input type="color" value="${r.color}" onchange="mm.setTier(${r.i},'color',this.value)" ondblclick="mm.setTier(${r.i},'color','')" title="Colour (double-click = palette colour)">
    </div>`).join("");
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
}

function bindInputs() {
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
  const close = () => { ob.hidden = true; state.onboarded = true; setPreview(true); };
  $("#obback").onclick = () => { s = Math.max(0, s - 1); draw(); };
  $("#obnext").onclick = async () => {
    if (s < last) { s++; draw(); return; }
    if (finishing) return;            // double clicks used to fire this twice
    finishing = true;
    $("#obnext").disabled = true;
    const theme = $("#obtheme").value.trim() || "Fruit";
    try {
      await call("finish_onboarding", { palette: pal, theme_name: theme });
      state.config.palette = pal; state.config.theme_name = theme; fill(); tiers();
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
  bindInputs();
  fill();
  tiers().catch(() => {});
  if (state.onboarded) setPreview(true); else onboarding();   // preview waits until onboarding is done
}

// pywebviewready can fire before this script runs; handle both orders.
window.addEventListener("pywebviewready", boot);
if (window.pywebview && window.pywebview.api) boot();
