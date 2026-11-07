const MODES = [
  ["🍉 Merge Evolution", true], ["🌀 Escape"], ["🎵 Rhythmic"], ["✏️ Drawer"], ["➕ Accumulate"],
  ["👻 Ghost Escape"], ["🧱 Breaker"], ["🏢 Glass Tower"], ["🚩 Flag Battle"], ["⚔️ Weapon Battle"],
  ["🥛 Glass Rush"], ["🏁 Race"], ["🎯 Plinko"], ["🌊 Wave 3D"], ["🎢 Marble Run 3D"], ["🧲 Magnet 3D"],
];
const $ = (s) => document.querySelector(s);
let state = {};

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
  async set(patch) { state.config = await pywebview.api.set_config(patch); fill(); },
  async pick(key, kind) {
    const f = await pywebview.api.pick_file(kind);
    if (f) await mm.set({ [key]: f });
  },
  async pickImages() { const imgs = await pywebview.api.pick_images(); state.config.tier_images = imgs; fill(); },
  async folder() { state.output_dir = await pywebview.api.pick_folder(); fill(); },
  restart() { pywebview.api.restart_preview(); },
  async reset() { state.config = await pywebview.api.reset_config(); fill(); },
  renderOne() { pywebview.api.render_one(); mm.progress({ i: 0, n: 1, p: 0 }); },
  renderBatch() {
    const n = parseInt($("#count").value || "10");
    pywebview.api.render_batch(n, $("#rand").checked, $("#wins").checked);
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

function fill() {
  const c = state.config;
  document.querySelectorAll("[data-k]").forEach((el) => {
    const v = c[el.dataset.k];
    if (el.type === "checkbox") el.checked = !!v; else el.value = v;
  });
  swatches($("#palettes"), (n) => mm.set({ palette: n }), c.palette);
  $("#imgcount").textContent = c.tier_images.length ? `${c.tier_images.length} image(s) loaded` : "Pick one image per tier, smallest first.";
  $("#soundname").textContent = c.sound_path ? c.sound_path.split(/[\\/]/).pop() : "Built-in pop. Any Myinstants mp3 works.";
  $("#outdir").textContent = state.output_dir || "";
}

function bindInputs() {
  document.querySelectorAll("[data-k]").forEach((el) => {
    const ev = el.type === "text" ? "change" : "input";
    el.addEventListener(ev, () => {
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (el.type === "range" || el.tagName === "SELECT" && !isNaN(v)) v = parseFloat(v);
      mm.set({ [el.dataset.k]: v });
    });
  });
}

function onboarding() {
  const ob = $("#onboard");
  ob.hidden = false;
  let s = 0, pal = state.config.palette;
  const steps = [...document.querySelectorAll(".step")], dots = [...document.querySelectorAll(".dots i")];
  const draw = () => {
    steps.forEach((el, i) => (el.hidden = i !== s));
    dots.forEach((d, i) => d.classList.toggle("on", i === s));
    $("#obback").style.visibility = s ? "visible" : "hidden";
    $("#obnext").textContent = s === 2 ? "Get started" : "Continue";
    swatches($("#obpal"), (n) => { pal = n; draw(); }, pal);
  };
  $("#obback").onclick = () => { s = Math.max(0, s - 1); draw(); };
  $("#obnext").onclick = async () => {
    if (s < 2) { s++; draw(); return; }
    await pywebview.api.finish_onboarding({ palette: pal, theme_name: $("#obtheme").value });
    state.config.palette = pal; state.config.theme_name = $("#obtheme").value; fill();
    ob.hidden = true;
  };
  draw();
}

window.addEventListener("pywebviewready", async () => {
  state = await pywebview.api.bootstrap();
  $("#ver").textContent = "v" + state.version;
  $("#modes").innerHTML = MODES.map(([n, on]) => `<a class="${on ? "on" : "off"}">${n}${on ? "" : "<em>Soon</em>"}</a>`).join("");
  $("#shapes").innerHTML = state.shapes.map((s) => `<option>${s}</option>`).join("");
  $("#hooks").innerHTML = state.hooks.map((h) => `<option value="${h}">`).join("");
  bindInputs();
  fill();
  pywebview.api.preview(true);
  if (!state.onboarded) onboarding();
});
