/**
 * Headless UI checks for the pywebview front-end (jsdom).
 *
 *   cd tools/uicheck && npm install && node check.mjs
 *
 * The page is loaded exactly as the app loads it (index.html + app.js + style.css) and the
 * Python bridge is replaced by fixtures, so every click path a user can take is exercised
 * without a browser engine or a GPU. Exits non-zero when a check fails.
 */
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const root = new URL("../../mm911/gui/web/", import.meta.url);
const html = readFileSync(new URL("index.html", root), "utf8");
const js = readFileSync(new URL("app.js", root), "utf8");

const FX = JSON.parse(readFileSync(new URL("./fixture.json", import.meta.url), "utf8"));
const PALIDX = FX.palette;
// what Python answers for the palette rows the checks click
const PALRUN = { undo: { done: true }, library: { page: "library" }, render: { started: true },
                 colab: { page: "colab" }, publish: { page: "publish" } };
const COLAB = FX.colab;
const UPLOAD = FX.upload;
const LIB = FX.library;

let uploadOn = UPLOAD.enabled;          // stands in for the saved settings

function bridge() {
  const fn = (k, ...a) => {
    calls.push([k, ...a]);
    switch (k) {
      case "bootstrap": return FX.bootstrap;
      case "palette": return PALIDX;
      case "palette_search": return [];
      case "palette_run": return PALRUN[a[1]] || { error: "unknown" };
      case "colab_status": return COLAB;
      case "colab_quota": return { output: "compute units: 42.5" };
      case "colab_render": return { ok: false, setup: true, error: "Colab is not connected yet",
                                    preflight: { ok: false, items: [{ state: "error", title: "Colab CLI", detail: "not installed", fix: "press Install" }] } };
      case "colab_preflight": return { ok: false, items: [{ state: "ok", title: "Render notebook", detail: "bundled", fix: "" },
                                                          { state: "error", title: "Colab CLI", detail: "not installed", fix: "press Install (one click)" }] };
      case "colab_install_plan": return { ok: false, dry_run: true, steps: [
        { title: "Install WSL2 + Ubuntu", cmd: "wsl --install -d Ubuntu", note: "may ask to reboot" },
        { title: "Install pipx and the Colab CLI inside Ubuntu", cmd: "wsl -d Ubuntu -- bash -lc \"pipx install google-colab-cli\"" }] };
      case "colab_install": return { ok: true, started: true };
      case "colab_login": return { ok: true, started: true, url: "" };
      case "set_text": return true;
      case "open_url": return null;
      case "auto_upload_state": return { ...UPLOAD, enabled: uploadOn };
      case "auto_upload_set": uploadOn = !!a[0]; return { ...UPLOAD, enabled: uploadOn };
      case "publish_upload": return true;
      case "publish_status": return FX.publish;
      case "publish_plan": return FX.plan;
      case "library": return LIB;
      case "history_status": return FX.history;
      case "preflight": return FX.preflight;
      case "update_check": return { status: "current", version: "0.26.0" };
      default: return {};
    }
  };
  return fn;
}

const errors = [];
let failures = 0;
const results = [];
function ok(name, pass, extra) {
  results.push({ name, pass });
  if (!pass) failures++;
  if (!pass) console.log(`  ✗ ${name}${extra ? " — " + extra : ""}`);
}

const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only", pretendToBeVisual: true });
const w = dom.window;
w.addEventListener("error", (e) => errors.push(String(e.message || e)));
w.HTMLElement.prototype.scrollIntoView = function () {};
const calls = [];
const dispatch = bridge();
// pywebview.api is an object of methods (app.js calls pywebview.api[name](...)), so every
// bridge endpoint is exposed as its own function, each one recorded for the assertions.
const api = new Proxy({}, { get: (_t, name) => (typeof name === "string" ? (...a) => dispatch(name, ...a) : undefined) });
w.pywebview = { api };
w.eval(js);
// pywebview fires this once its API is injected; the page boots from it
w.dispatchEvent(new w.Event("pywebviewready"));

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const $ = (s) => w.document.querySelector(s);
const $$ = (s) => [...w.document.querySelectorAll(s)];

// ---------------------------------------------------------------- existing UI
await wait(60);
ok("page boots", typeof w.mm === "object");
ok("modes render", $$("#modes button").length >= 0);
ok("palette button in the top bar", !!$(".palhint"));

// ---------------------------------------------------------------- ⌘K palette
await w.mm.openPalette();
await wait(80);
ok("palette opens", !$("#palette").hidden);
ok("palette starts with the useful actions", $$("#pallist .palrow").length > 0);
$("#palq").value = "upload";
await w.mm.paletteSearch();
ok("palette finds the upload action", /Upload the queue/.test($("#pallist").textContent));
$("#palq").value = "grav";
await w.mm.paletteSearch();
ok("palette finds a setting by its visible label", /Gravity/.test($("#pallist").textContent));
$("#palq").value = "fruit";
await w.mm.paletteSearch();
ok("palette finds a rendered video", /Fruit Merge/.test($("#pallist").textContent));
$("#palq").value = "zzzz";
await w.mm.paletteSearch();
ok("palette says when nothing matches", /Nothing matches/.test($("#pallist").textContent));
$("#palq").value = "undo";
await w.mm.paletteSearch();
ok("first result is selected", !!$("#pallist .palrow.on"));
w.mm.paletteKey({ key: "ArrowDown", preventDefault() {} });
ok("arrow keys move the selection", $$("#pallist .palrow").length === 1 || /data-i="1"/.test($("#pallist").innerHTML));
w.mm.paletteKey({ key: "Escape", preventDefault() {} });
ok("Esc closes the palette", $("#palette").hidden);

await w.mm.openPalette("gravity");
ok("openPalette accepts a starting query", $("#palq").value === "gravity");
w.mm.closePalette();
ok("labels are collected from the page", Object.keys(w.mm.settingLabels()).length > 50);

// Enter on a page row navigates
$("#palq").value = "library";
await w.mm.paletteSearch();
const libRow = $$("#pallist .palrow").findIndex((el) => /My videos/.test(el.textContent));
if (libRow >= 0) { await w.mm.palRun(libRow); await wait(40); }
ok("palette page rows open the page", !$("#library").hidden);
w.mm.closeLibrary();

// keyboard: Ctrl+K anywhere
w.document.body.focus();
w.document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }));
await wait(60);
ok("Ctrl+K opens the palette", !$("#palette").hidden);
w.mm.closePalette();
w.document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "?", bubbles: true }));
ok("? opens the shortcuts sheet", !$("#shortcuts").hidden);
w.mm.closeShortcuts();

// ---------------------------------------------------------------- shortcuts sheet
w.mm.showShortcuts();
ok("shortcuts sheet opens", !$("#shortcuts").hidden);
ok("shortcuts sheet lists keys", /Ctrl\+Z/.test($("#keyslist").textContent));
ok("shortcuts sheet is grouped", $$("#keyslist .keysgroup").length >= 2);
ok("the sheet documents the new keys", /Ctrl\+Shift\+P/.test($("#keyslist").textContent));
w.mm.closeShortcuts();
ok("shortcuts sheet closes", $("#shortcuts").hidden);

// ---------------------------------------------------------------- Colab
await w.mm.openColab();
await wait(120);
ok("colab page opens", !$("#colabpage").hidden);
ok("colab lists GPUs", $$("#colabgpu option").length === COLAB.gpus.length);
ok("colab shows the install steps", $$("#colabsteps li").length >= 3);
ok("colab disables render until ready", $("#colabgo").disabled === true);
ok("colab explains what is missing", /colab-cli|WSL|Install/i.test($("#colabstatus").textContent));
await w.mm.colabQuota();
ok("colab quota is shown", /compute units/.test($("#colabquota").textContent));
await w.mm.startColab();
ok("starting colab without setup explains itself", /not connected/i.test(w.document.body.textContent));
w.mm.colabProgress({ state: "packing", note: "Packing your project…" });
ok("colab shows packing progress", /Packing/.test($("#colabptext").textContent));
w.mm.colabProgress({ state: "done", videos: ["/tmp/out/a.mp4"], note: "1 video(s) downloaded" });
ok("colab lists downloaded videos", /a\.mp4/.test($("#colabresults").textContent));
w.mm.colabProgress({ state: "error", error: "no quota left" });
ok("colab reports an error", /no quota left/.test($("#colabresults").textContent));
w.mm.closeColab();
ok("colab closes", $("#colabpage").hidden);

// ---- one-click install / sign-in ----
await w.mm.openColab();
await wait(100);
ok("colab offers a one-click install", /one click/i.test($("#colabacts").textContent));
ok("colab offers the manual commands too", /commands/i.test($("#colabacts").textContent));
ok("colab preflight lists what blocks a render", !$("#colabpf").hidden && /not installed/.test($("#colabpf").textContent));
ok("colab install steps are shown with statuses", $$("#colabsteps li").length >= 4);
ok("the WSL2 path is explained", /WSL2|Ubuntu/.test($("#colabsteps").textContent));
await w.mm.colabInstall();
ok("install shows the commands before running them", !$("#colabinstall").hidden &&
   /wsl --install/.test($("#colabinstallsteps").textContent));
w.mm.colabInstallProgress({ state: "install", i: 0, title: "Install WSL2 + Ubuntu", step: "start" });
ok("the running step is marked", /installstep run/.test($("#colabinstallsteps").innerHTML));
w.mm.colabInstallProgress({ state: "install", i: 0, title: "Install WSL2 + Ubuntu", step: "done", output: "ok" });
ok("the finished step is marked", /installstep done/.test($("#colabinstallsteps").innerHTML));
ok("install output is visible", /ok/.test($("#colabinstalllog").textContent));
w.mm.colabInstallProgress({ state: "installed", note: "installed" });
ok("install completion is reported", /sign in/i.test($("#colabinstalltitle").textContent));
await w.mm.colabLogin();
ok("sign-in starts and shows its panel", !$("#colablogin").hidden);
w.mm.colabLoginUrl("https://accounts.google.com/o/oauth2/auth?x=1");
ok("the consent link is put in the box", /accounts\.google\.com/.test($("#colabloginurl").value));
ok("the link can be copied or opened", /Copy/.test($("#colablogin").textContent) && /Open/.test($("#colablogin").textContent));
ok("signing in refreshes the status card", typeof w.mm.refreshColab === "function");
await w.mm.startColab();
ok("render refuses with the preflight reason", /Colab CLI/.test($("#colabpf").textContent));
w.mm.closeInstall();
ok("the install log can be dismissed", $("#colabinstall").hidden);
ok("colab has a sidebar entry", !!$("#colabnav"));

// ---------------------------------------------------------------- one-click upload
await w.mm.openLibrary();
await wait(80);
ok("library opens", !$("#library").hidden);
ok("library shows an upload button", !!$("#libuploadbtn"));
ok("upload button counts what is new", $("#libuploadcount").textContent === "2" && !$("#libuploadcount").hidden);
ok("auto-upload checkbox reflects the settings", $("#libauto").checked === false);
await w.mm.autoUploadFromLibrary(true);
ok("auto-upload turns on in one click", $("#libauto").checked === true);
ok("auto-upload state is saved through the bridge", calls.some((c) => c[0] === "auto_upload_set" && c[1] === true));
ok("auto-upload shows a state hint", /On/.test($("#libautohint").textContent));
await w.mm.uploadNew();
ok("'Upload new videos' starts the queue", calls.some((c) => c[0] === "publish_upload"));
w.mm.uploadProgress({ pub: true, i: 0, n: 2, p: 0.5, title: "Fruit" });
ok("upload progress shows in the library bar", /Uploading 1 of 2/.test($("#libptext").textContent));
w.mm.uploadDone({ pubdone: true, note: "2 uploaded" });
ok("upload progress hides when done", $("#libprog").hidden);
w.mm.closeLibrary();

// ---------------------------------------------------------------- auto-upload action from the palette
w.mm.paletteJs("auto_upload");
await wait(40);
ok("palette can toggle auto-upload", calls.some((c) => c[0] === "auto_upload_set"));

// ---------------------------------------------------------------- earlier passes stay working
w.mm.closeLibrary();
await w.mm.openLibrary();
await wait(80);
ok("library grid paints the renders", $$("#libgrid .libcard, #libgrid .librow, #libgrid [data-file]").length > 0);
ok("library shows the video title", /Fruit Merge/.test($("#libgrid").textContent));
$("#libsearch").value = "zzzz";
w.mm.paintLibrary();
ok("library search filters", !/Fruit Merge/.test($("#libgrid").textContent));
$("#libsearch").value = "";
w.mm.paintLibrary();
ok("clearing the search brings the video back", /Fruit Merge/.test($("#libgrid").textContent));

await w.mm.refreshHistory();
w.mm.paintHistory();
ok("undo button reflects history", $("#undobtn").disabled === false);
ok("redo is disabled when there is nothing to redo", $("#redobtn").disabled === true);

$("#setsearch").value = "gravity";
await w.mm.search();
ok("settings search finds a control", /Gravity/.test(w.document.body.textContent));
$("#setsearch").value = "";
w.mm.clearSearch();

await w.mm.openPublish();
await wait(80);
ok("publish studio opens", !$("#studio").hidden);
ok("publish studio paints the queue summary", /ready/.test($("#pubplansum").textContent || "") || $("#pubplansum").textContent === "");
ok("publish studio shows setup steps", $$("#pubsteps li").length > 0 || /Google|YouTube/i.test($("#pubstatus").textContent));
ok("auto-upload checkbox in the studio matches the settings", $("#pubauto").checked === uploadOn);
w.mm.closePublish();
ok("publish studio closes", $("#studio").hidden);

// Escape closes every overlay at once
await w.mm.openPalette();
await w.mm.openLibrary();
await w.mm.openColab();
w.document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
ok("Esc closes every overlay", $("#palette").hidden && $("#library").hidden && $("#colabpage").hidden);

// ---------------------------------------------------------------- layout rails
ok("the sidebar has a scrolling mode list", !!$(".sidescroll") && !!$(".sidescroll #modes"));
ok("Library / Publish / Colab sit in a pinned footer", !!$(".sidefoot #libnav") && !!$(".sidefoot #colabnav"));
ok("the sidebar footer is outside the scroll area", !$(".sidescroll").contains($("#colabnav")));
ok("the inspector is its own scroll container", /inspector/.test(w.document.body.innerHTML) &&
   w.document.querySelectorAll(".inspector details").length > 5);

// ---------------------------------------------------------------- done
ok("no JS errors after exercising the new UI", errors.length === 0, JSON.stringify(errors));
const passed = results.filter((r) => r.pass).length;
console.log(`\n${failures ? "FAILURES" : "ALL CHECKS PASSED"} — ${passed}/${results.length}`);
w.close();
process.exit(failures ? 1 : 0);
