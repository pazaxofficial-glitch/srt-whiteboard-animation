/* Simple Whiteboard Animation — front end (no build step, works offline). */
"use strict";

const state = { info: null, project: null, hands: [], backgrounds: [], polling: {}, audio: null };

/* ── tiny helpers ─────────────────────────────────────── */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "html") el.innerHTML = v;            // only used with our own static icons
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (sel) => document.querySelector(sel);

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; }
  if (opts.form) init.body = opts.form;
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res;
}

function toast(msg, kind = "") {
  const el = h("div", { class: "toast " + kind }, msg);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), kind === "error" ? 7000 : 3500);
}
function fail(e) { console.error(e); toast(e.message || String(e), "error"); }

function fmtTime(s) {
  if (s === null || s === undefined || isNaN(s)) return "–";
  const m = Math.floor(s / 60), sec = s - m * 60;
  return `${m}:${sec.toFixed(1).padStart(4, "0")}`;
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

const ICONS = {
  projects: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 21h8M12 18v3"/></svg>',
  hand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 11V6a2 2 0 0 0-4 0v5M14 10V4a2 2 0 0 0-4 0v6M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg>',
  image: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/></svg>',
  help: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
  film: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2.2"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  sparkle: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.9 5.6L19.5 9.5l-5.6 1.9L12 17l-1.9-5.6L4.5 9.5l5.6-1.9zM19 15l.9 2.6 2.6.9-2.6.9L19 22l-.9-2.6-2.6-.9 2.6-.9z"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5"/></svg>',
};
const icon = (name) => h("span", { html: ICONS[name], style: { display: "inline-flex" } });

/* ── theme & language ─────────────────────────────────── */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("swa-theme", theme);
  $("#themeBtn").innerHTML = theme === "dark" ? ICONS.sun : ICONS.moon;
}
function applyLang(lang) {
  setLang(lang);
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  localStorage.setItem("swa-lang", lang);
  $("#langBtn").textContent = lang === "fa" ? "English" : "فارسی";
}

/* ── sidebar ──────────────────────────────────────────── */
function renderNav() {
  const route = location.hash || "#/projects";
  const items = [
    ["#/projects", "projects", t("nav.projects")],
    ["#/hands", "hand", t("nav.hands")],
    ["#/backgrounds", "image", t("nav.backgrounds")],
    ["#/help", "help", t("nav.help")],
  ];
  const nav = $("#nav");
  nav.replaceChildren(...items.map(([href, ic, label]) => {
    const active = route.startsWith(href) || (href === "#/projects" && route.startsWith("#/p/"));
    return h("a", { href, class: active ? "active" : "" }, icon(ic), label);
  }));
  const sys = $("#sys");
  if (state.info) {
    const w = state.info.whisper.length > 0, f = state.info.ffmpeg;
    sys.replaceChildren(
      h("span", {}, h("i", { class: "dot " + (w ? "ok" : "bad") }), w ? `Whisper (${state.info.whisper[0]})` : t("sys.noWhisper")),
      h("span", {}, h("i", { class: "dot " + (f ? "ok" : "bad") }), f ? "FFmpeg" : t("sys.noFfmpeg")),
      h("span", { class: "faint" }, "v" + state.info.version),
    );
  }
}

/* ── router ───────────────────────────────────────────── */
async function route() {
  Object.values(state.polling).forEach(clearInterval);
  state.polling = {};
  if (state.audio) { state.audio.pause(); state.audio = null; }
  renderNav();
  const hash = location.hash || "#/projects";
  const parts = hash.slice(2).split("/");
  const view = $("#view");
  try {
    if (parts[0] === "p" && parts[1]) await viewProject(decodeURIComponent(parts[1]), parts[2] || "content");
    else if (parts[0] === "hands") await viewHands();
    else if (parts[0] === "backgrounds") await viewBackgrounds();
    else if (parts[0] === "help") viewHelp();
    else await viewProjects();
  } catch (e) {
    view.replaceChildren(h("div", { class: "card empty" }, e.message));
  }
}

/* ── projects list ───────────────────────────────────── */
async function viewProjects() {
  const list = await api("/api/projects");
  const view = $("#view");
  const hero = h("div", { class: "hero" },
    h("h1", {}, t("home.title")),
    h("p", {}, t("home.lead")),
    h("button", { class: "btn big", onclick: newProject }, icon("sparkle"), t("home.new")),
    h("span", { html: '<svg class="doodle" viewBox="0 0 260 120" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round"><path d="M10 100 C 40 20, 80 20, 100 70 S 160 110, 180 40 S 240 10, 250 60"/><circle cx="60" cy="40" r="14"/><path d="M200 100 l20 -40 20 40 z"/></svg>' }),
  );
  const cards = list.map((p) => {
    const img = p.images ? h("img", { src: `/api/projects/${encodeURIComponent(p.slug)}/cover`, loading: "lazy", onerror: (e) => e.target.remove() }) : null;
    return h("div", { class: "card flat pcard", onclick: () => (location.hash = `#/p/${encodeURIComponent(p.slug)}`) },
      h("div", { class: "thumb" }, img || icon("film")),
      h("div", {},
        h("h2", { dir: "auto" }, p.name),
        h("div", { class: "row small muted" },
          `${p.lines} ${t("w.lines")} · ${p.images} ${t("w.images")}`,
          p.renders.length ? h("span", { class: "badge ok" }, t("st.rendered")) :
            p.aligned ? h("span", { class: "badge" }, t("st.synced")) : h("span", { class: "badge" }, t("st.draft"))),
      ));
  });
  view.replaceChildren(hero,
    h("div", { class: "row spread", style: { marginBottom: "14px" } }, h("h3", {}, t("home.your"))),
    cards.length ? h("div", { class: "projects" }, cards) : h("div", { class: "card empty" }, t("home.none")));
}

async function newProject() {
  const name = await promptModal(t("home.new"), t("home.namePh"));
  if (!name) return;
  try {
    const p = await api("/api/projects", { method: "POST", json: { name } });
    location.hash = `#/p/${encodeURIComponent(p.slug)}`;
  } catch (e) { fail(e); }
}

function promptModal(title, placeholder, value = "") {
  return new Promise((resolve) => {
    const modal = $("#modal");
    const input = h("input", { type: "text", placeholder, value });
    const close = (v) => { modal.hidden = true; modal.replaceChildren(); resolve(v); };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") close(input.value.trim()); if (e.key === "Escape") close(null); });
    modal.replaceChildren(h("div", { class: "card stack" }, h("h2", {}, title), input,
      h("div", { class: "row", style: { justifyContent: "flex-end" } },
        h("button", { class: "btn ghost", onclick: () => close(null) }, t("w.cancel")),
        h("button", { class: "btn primary", onclick: () => close(input.value.trim()) }, t("w.create")))));
    modal.hidden = false;
    input.focus();
  });
}

function confirmModal(text) {
  return new Promise((resolve) => {
    const modal = $("#modal");
    const close = (v) => { modal.hidden = true; modal.replaceChildren(); resolve(v); };
    modal.replaceChildren(h("div", { class: "card stack" }, h("p", {}, text),
      h("div", { class: "row", style: { justifyContent: "flex-end" } },
        h("button", { class: "btn ghost", onclick: () => close(false) }, t("w.cancel")),
        h("button", { class: "btn primary", onclick: () => close(true) }, t("w.ok")))));
    modal.hidden = false;
  });
}

/* ── project ─────────────────────────────────────────── */
const TABS = ["content", "images", "style", "audio", "sync", "export"];
const NEUTRAL_TABS = ["style", "audio"];

async function loadProject(slug) {
  state.project = await api(`/api/projects/${encodeURIComponent(slug)}`);
  return state.project;
}

async function viewProject(slug, tab) {
  const p = await loadProject(slug);
  const enc = encodeURIComponent(slug);
  const done = {
    content: !!p.narration && p.lines > 0,
    images: p.lines > 0 && p.missing_images.length === 0,
    style: true,
    audio: true,
    sync: p.aligned,
    export: p.renders.length > 0,
  };
  const title = h("input", { class: "title-input", value: p.name, onchange: async (e) => {
    try { await api(`/api/projects/${enc}`, { method: "PATCH", json: { name: e.target.value } }); toast(t("msg.saved"), "ok"); } catch (err) { fail(err); }
  } });
  const chips = h("div", { class: "row" },
    h("span", { class: "badge " + (p.narration ? "ok" : "warn") }, p.narration ? t("st.narrationOk") : t("st.noNarration")),
    h("span", { class: "badge" }, `${p.lines} ${t("w.lines")}`),
    h("span", { class: "badge " + (p.lines && !p.missing_images.length ? "ok" : "warn") }, `${p.images}/${p.lines} ${t("w.images")}`),
    h("span", { class: "badge " + (p.aligned ? "ok" : "") }, p.aligned ? t("st.synced") : t("st.notSynced")));
  const head = h("div", { class: "page-head" },
    h("div", { class: "stack", style: { gap: "8px" } },
      h("div", { class: "row" }, h("a", { href: "#/projects", class: "muted" }, t("w.back")), title), chips),
    h("div", { class: "row" },
      h("button", { class: "btn ghost", onclick: () => api(`/api/projects/${enc}/open-folder`, { method: "POST" }).catch(fail) }, icon("folder"), t("p.openFolder")),
      h("button", { class: "btn ghost danger", onclick: async () => {
        if (!(await confirmModal(t("p.deleteConfirm")))) return;
        await api(`/api/projects/${enc}`, { method: "DELETE" }).catch(fail);
        location.hash = "#/projects";
      } }, t("w.delete")),
      h("button", { class: "btn primary big", onclick: () => oneClick(slug) }, icon("sparkle"), t("p.makeVideo"))));
  const tabs = h("div", { class: "tabs" }, TABS.map((k, i) =>
    h("a", { href: `#/p/${enc}/${k}`, class: (k === tab ? "active " : "") + (done[k] && !NEUTRAL_TABS.includes(k) ? "done" : "") },
      h("span", { class: "n" }, done[k] && !NEUTRAL_TABS.includes(k) ? "✓" : i + 1), t("tab." + k))));
  const body = h("div", {});
  $("#view").replaceChildren(head, tabs, body);
  const fn = { content: tabContent, images: tabImages, style: tabStyle, audio: tabAudio, sync: tabSync, export: tabExport }[tab] || tabContent;
  await fn(body, p);
  for (const j of p.jobs || []) if (j.status === "running") watchJob(j, body.querySelector(".jobslot"));
}

/* One click: sync (if needed), let Claude draw missing scenes (Claude mode), then render. */
async function oneClick(slug) {
  const p = state.project;
  const enc = encodeURIComponent(slug);
  const claudeMode = p.settings.engine === "claude" && state.info && state.info.claude;
  if (!p.narration) return toast(t("msg.needNarration"), "error");
  if (!p.lines) return toast(t("msg.needScript"), "error");
  if (!p.images && p.settings.text_lines !== "write" && !claudeMode) return toast(t("msg.needImages"), "error");
  location.hash = `#/p/${enc}/export`;
  await new Promise((r) => setTimeout(r, 150));
  try {
    if (!p.aligned) {
      const method = state.info.whisper.length ? "whisper" : "estimate";
      if (method === "estimate") toast(t("msg.estimating"));
      const job = await api(`/api/projects/${enc}/align`, { method: "POST", json: { method } });
      const res = await watchJob(job, document.querySelector(".jobslot"));
      if (res.status !== "done") return;
    }
    if (claudeMode && p.missing_images.length) {
      const job = await api(`/api/projects/${enc}/claude`, { method: "POST", json: {} });
      const res = await watchJob(job, document.querySelector(".jobslot"));
      if (res.status !== "done") return;
    }
    const job = await api(`/api/projects/${enc}/render`, { method: "POST", json: {} });
    await watchJob(job, document.querySelector(".jobslot"), true);
  } catch (e) { fail(e); }
}

/* What a running job is doing, in the interface language when the server says which step it is on. */
function jobText(j) {
  const info = j.info || {};
  if (j.kind === "claude" && info.step) {
    return t("cl.step." + info.step) + (info.line ? ` #${info.line}` : "") +
      (info.total ? ` · ${info.drawn || 0}/${info.total}` : "");
  }
  return j.message || "";
}

function jobError(j) {
  const code = (j.info || {}).code;
  const key = code ? "cl.err." + code : null;
  return key && t(key) !== key ? t(key) : j.error;
}

function watchJob(job, slot, reloadOnDone = true) {
  return new Promise((resolve) => {
    if (!slot) slot = h("div", {});
    const bar = h("i", {});
    const msg = h("span", { class: "grow" }, job.message || t("job.starting"));
    const pct = h("b", {}, "0%");
    const eta = h("span", { class: "muted" }, "");
    const cancel = h("button", { class: "btn ghost small", onclick: () => api(`/api/jobs/${job.id}/cancel`, { method: "POST" }).catch(fail) }, t("w.cancel"));
    slot.replaceChildren(h("div", { class: "card job" },
      h("div", { class: "row" }, h("b", {}, t("job." + job.kind)), msg, eta, pct, cancel),
      h("div", { class: "progress" }, bar)));
    const tick = async () => {
      let j;
      try { j = await api(`/api/jobs/${job.id}`); } catch (e) { return; }
      bar.style.width = `${(j.progress * 100).toFixed(1)}%`;
      pct.textContent = `${Math.round(j.progress * 100)}%`;
      msg.textContent = jobText(j);
      if (j.info && j.info.eta !== undefined && j.status === "running") eta.textContent = `${t("job.eta")} ${fmtTime(j.info.eta)}`;
      if (j.status !== "running") {
        clearInterval(state.polling[job.id]);
        delete state.polling[job.id];
        if (j.status === "done") toast(t("job.done." + job.kind), "ok");
        if (j.status === "done" && job.kind === "claude" && j.result && (j.result.missing || []).length)
          toast(`${t("cl.notDrawn")}: ${j.result.missing.map((n) => "#" + n).join(", ")}`, "error");
        else if (j.status === "cancelled") toast(t("job.cancelled"));
        else toast(`${t("job.failed")}: ${jobError(j)}`, "error");
        resolve(j);
        if (reloadOnDone && j.status === "done" && !(j.result && j.result.preview)) route();
        else if (j.status !== "done") slot.replaceChildren();
      }
    };
    state.polling[job.id] = setInterval(tick, 700);
    tick();
  });
}

/* ── tab 1: narration + script ───────────────────────── */
function dropzone(label, hint, accept, multiple, onFiles) {
  const input = h("input", { type: "file", accept, multiple: multiple || null, hidden: true,
    onchange: (e) => { if (e.target.files.length) onFiles([...e.target.files]); e.target.value = ""; } });
  const zone = h("div", { class: "drop", onclick: () => input.click() }, icon("upload"), h("b", {}, label), h("span", { class: "muted small" }, hint), input);
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); if (e.dataTransfer.files.length) onFiles([...e.dataTransfer.files]); });
  return zone;
}

async function tabContent(body, p) {
  const enc = encodeURIComponent(p.slug);
  const audio = p.narration ? h("audio", { controls: true, src: `/api/projects/${enc}/narration?ts=${Date.now()}`, style: { width: "100%" } }) : null;
  const narr = h("div", { class: "card stack" },
    h("div", {}, h("h2", {}, t("c.narration")), h("p", { class: "muted small" }, t("c.narrationHint"))),
    dropzone(p.narration ? t("c.replaceAudio") : t("c.dropAudio"), "MP3 · WAV · M4A · OGG · FLAC", "audio/*,video/*", false, async (files) => {
      const fd = new FormData(); fd.append("file", files[0]);
      try { toast(t("msg.uploading")); await api(`/api/projects/${enc}/narration`, { method: "POST", form: fd }); toast(t("msg.saved"), "ok"); route(); } catch (e) { fail(e); }
    }),
    audio, p.narration ? h("p", { class: "small faint" }, p.narration) : null);

  const ta = h("textarea", { class: "script", dir: "auto", placeholder: t("c.scriptPh"), spellcheck: "false" });
  ta.value = p.script;
  const parsedBox = h("div", { class: "lines" });
  const count = h("span", { class: "badge" });
  const drawParsed = (lines) => {
    count.textContent = `${lines.length} ${t("w.lines")}`;
    parsedBox.replaceChildren(...lines.slice(0, 400).map((ln) =>
      h("div", {}, h("span", { class: "n" }, ln.id), h("span", { class: "grow", dir: "auto" }, ln.text),
        ln.image ? h("span", { class: "faint small" }, "🖼 " + ln.image) : h("span", { class: "small", style: { color: "var(--warn)" } }, t("i.noImage")))));
  };
  drawParsed(p.parsed);
  const status = h("span", { class: "small faint" }, "");
  const save = debounce(async () => {
    try {
      const np = await api(`/api/projects/${enc}/script`, { method: "PUT", json: { text: ta.value } });
      state.project = np; drawParsed(np.parsed); status.textContent = t("msg.saved");
    } catch (e) { fail(e); }
  }, 700);
  ta.addEventListener("input", () => { status.textContent = t("msg.saving"); save(); });
  const script = h("div", { class: "card stack" },
    h("div", { class: "row spread" }, h("div", {}, h("h2", {}, t("c.script")), h("p", { class: "muted small" }, t("c.scriptHint"))), count),
    h("p", { class: "tip small" }, t("c.marksHint")),
    ta, status, h("h3", {}, t("c.parsed")), parsedBox);
  body.replaceChildren(h("div", { class: "stack" }, narr, script,
    h("div", { class: "row", style: { justifyContent: "flex-end" } },
      h("a", { class: "btn primary", href: `#/p/${enc}/images` }, t("w.next")))));
}

/* ── tab 2: images ───────────────────────────────────── */
const CLIP_RE = /\.(mp4|webm|mov|m4v)$/i;

/* Colouring for one picture: auto → off → on → auto. */
function colorChip(p, ln) {
  const enc = encodeURIComponent(p.slug);
  const btn = h("button", { type: "button", class: "chip" });
  const draw = () => {
    const cur = ((p.line_options || {})[String(ln.id)] || {}).coloring || "auto";
    btn.className = "chip " + cur;
    btn.textContent = "🎨 " + t("i.color." + cur);
    btn.title = t("i.colorTitle");
  };
  btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const cur = ((p.line_options || {})[String(ln.id)] || {}).coloring || "auto";
    const next = { auto: "off", off: "on", on: "auto" }[cur];
    try {
      const r = await api(`/api/projects/${enc}/lines/${ln.id}`, { method: "PUT", json: { coloring: next } });
      p.line_options = r.line_options;
      draw();
    } catch (err) { fail(err); }
  });
  draw();
  return btn;
}

function copyText(text) {
  const done = () => toast(t("cl.copied"), "ok");
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done, fail);
  const ta = h("textarea", { style: { position: "fixed", opacity: "0" } });
  ta.value = text;
  document.body.append(ta);
  ta.select();
  try { document.execCommand("copy"); done(); } catch (e) { fail(e); }
  ta.remove();
}

/* Claude draws the scenes: the author's brief, the button that runs Claude Code, or what to paste by hand. */
function claudePanel(p, slot, run) {
  const enc = encodeURIComponent(p.slug);
  const brief = h("textarea", { class: "brief", dir: "auto", placeholder: t("cl.briefPh"), spellcheck: "false" });
  brief.value = p.settings.claude_brief || "";
  const status = h("span", { class: "small faint" }, "");
  const save = debounce(async () => {
    try { await api(`/api/projects/${enc}/settings`, { method: "PUT", json: { claude_brief: brief.value } }); status.textContent = t("msg.saved"); }
    catch (e) { fail(e); }
  }, 700);
  brief.addEventListener("input", () => { status.textContent = t("msg.saving"); save(); });
  const missing = p.missing_images.length;
  const actions = state.info && state.info.claude
    ? h("div", { class: "row" },
        h("button", { class: "btn primary", disabled: missing ? null : true, onclick: () => run(null, false) },
          icon("sparkle"), missing ? `${t("cl.drawMissing")} (${missing})` : t("cl.allDrawn")),
        p.images ? h("button", { class: "btn ghost", onclick: async () => {
          if (await confirmModal(t("cl.redoAllConfirm"))) run(null, true);
        } }, icon("refresh"), t("cl.redoAll")) : null)
    : h("p", { class: "tip small" }, t("cl.noCli"));
  return h("div", { class: "card stack" },
    h("div", {}, h("h2", {}, t("cl.title")), h("p", { class: "muted small" }, t("cl.hint"))),
    h("label", { class: "field" }, t("cl.brief"), brief), status,
    actions, slot,
    h("details", { class: "small" },
      h("summary", { class: "muted" }, t("cl.manualTitle")),
      h("div", { class: "stack", style: { gap: "8px", marginTop: "8px" } },
        h("p", { class: "muted" }, t("cl.manual")),
        h("div", { class: "cmd" }, h("code", { dir: "ltr" }, p.claude_prompt),
          h("button", { class: "btn ghost small", onclick: () => copyText(p.claude_prompt) }, t("cl.copy"))),
        h("p", { class: "faint" }, t("cl.clips")))));
}

async function tabImages(body, p) {
  const enc = encodeURIComponent(p.slug);
  const engine = p.settings.engine === "claude" ? "claude" : "images";
  const claudeOn = engine === "claude" && state.info && state.info.claude;
  const slot = h("div", { class: "jobslot" });
  const setEngine = async (v) => {
    if (v === engine) return;
    try { await api(`/api/projects/${enc}/settings`, { method: "PUT", json: { engine: v } }); route(); } catch (e) { fail(e); }
  };
  const runClaude = async (lines, redo) => {
    try {
      const job = await api(`/api/projects/${enc}/claude`, { method: "POST", json: { lines, redo } });
      watchJob(job, slot);
    } catch (e) { fail(e); }
  };
  const source = h("div", { class: "methods two" },
    h("div", { class: "method" + (engine === "images" ? " on" : ""), onclick: () => setEngine("images") },
      h("b", {}, t("src.images")), h("p", {}, t("src.imagesHint"))),
    h("div", { class: "method" + (engine === "claude" ? " on" : ""), onclick: () => setEngine("claude") },
      h("b", {}, t("src.claude")), h("p", {}, t("src.claudeHint"))));

  let replace = false;
  const upload = async (files) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("replace", replace ? "true" : "false");
    try {
      toast(`${t("msg.uploading")} (${files.length})`);
      const r = await api(`/api/projects/${enc}/images`, { method: "POST", form: fd });
      toast(`${r.saved} ${t("i.saved")}${r.skipped.length ? ` · ${r.skipped.length} ${t("i.skipped")}` : ""}`, "ok");
      route();
    } catch (e) { fail(e); }
  };
  const replaceToggle = h("label", { class: "row small muted", style: { cursor: "pointer" } },
    h("input", { type: "checkbox", onchange: (e) => (replace = e.target.checked) }), t("i.replace"));
  const imgs = p.image_files;
  const cards = p.parsed.map((ln) => {
    const name = imgs[String(ln.id)];
    if (!name) {
      const label = engine === "claude" ? t("i.byClaude") : p.settings.text_lines === "write" ? t("i.asText") : `${t("i.missing")} #${ln.id}`;
      const asText = engine === "claude" || p.settings.text_lines === "write";
      return h("div", { class: "icard missing" + (asText ? " as-text" : "") }, h("div", { class: "pic" }, label),
        h("div", { class: "meta" }, h("span", { class: "num" }, ln.id), h("span", { class: "txt", dir: "auto" }, ln.text)),
        claudeOn ? h("button", { class: "iconbtn redo", title: t("cl.drawThis"), html: ICONS.sparkle, onclick: () => runClaude([ln.id], false) }) : null);
    }
    const clip = CLIP_RE.test(name);
    return h("div", { class: "icard" },
      h("div", { class: "pic" }, h("img", { src: `/api/projects/${enc}/images/${encodeURIComponent(name)}?thumb=1`, loading: "lazy", alt: name }),
        clip ? h("span", { class: "clipmark" }, "▶ " + t("i.clip")) : null),
      h("div", { class: "meta" }, h("span", { class: "num" }, ln.id), h("span", { class: "txt", dir: "auto", title: ln.text }, ln.text)),
      h("div", { class: "foot" }, clip ? h("span", {}) : colorChip(p, ln),
        claudeOn ? h("button", { class: "iconbtn", title: t("cl.redoThis"), html: ICONS.refresh, onclick: async () => {
          if (await confirmModal(t("cl.redoThisConfirm"))) runClaude([ln.id], true);
        } }) : null),
      h("button", { class: "iconbtn x", title: t("w.delete"), html: ICONS.x, onclick: async () => {
        await api(`/api/projects/${enc}/images/${encodeURIComponent(name)}`, { method: "DELETE" }).catch(fail); route();
      } }));
  });
  const extra = p.extra_images.length ? h("p", { class: "small", style: { color: "var(--warn)" } },
    `${t("i.extra")}: ${p.extra_images.map((n) => "#" + n).join(", ")}`) : null;
  const warns = (p.warnings || []).map((w) => h("p", { class: "small", style: { color: "var(--warn)" } }, w));
  const uploadCard = h("div", { class: "card stack" },
    h("div", {}, h("h2", {}, t("i.title")), h("p", { class: "muted small" }, t("i.hint"))),
    dropzone(t("i.drop"), "PNG · JPG · WebP · SVG · ZIP · MP4/WebM", "image/*,.svg,.zip,video/*", true, upload),
    h("div", { class: "row spread" }, replaceToggle,
      h("div", { class: "row" },
        h("span", { class: "badge " + (!p.missing_images.length ? "ok" : p.settings.text_lines === "write" ? "" : "warn") },
          !p.missing_images.length ? t("i.allGood") : p.settings.text_lines === "write"
            ? `${p.missing_images.length} ${t("i.textCount")}` : `${p.missing_images.length} ${t("i.missingCount")}`),
        p.images ? h("button", { class: "btn ghost danger", onclick: async () => {
          if (!(await confirmModal(t("i.clearConfirm")))) return;
          await api(`/api/projects/${enc}/images`, { method: "DELETE" }).catch(fail); route();
        } }, t("i.clear")) : null)),
    extra, warns);
  body.replaceChildren(h("div", { class: "stack" },
    h("div", { class: "card stack" }, h("div", {}, h("h2", {}, t("src.title")), h("p", { class: "muted small" }, t("src.hint"))), source),
    engine === "claude" ? claudePanel(p, slot, runClaude) : uploadCard,
    p.parsed.length ? h("div", { class: "imgs" }, cards) : h("div", { class: "card empty" }, t("i.noScript")),
    engine === "claude" ? h("details", { class: "card small" }, h("summary", { class: "muted" }, t("cl.ownImages")),
      h("div", { style: { marginTop: "12px" } }, dropzone(t("i.drop"), "PNG · JPG · WebP · SVG · ZIP · MP4/WebM", "image/*,.svg,.zip,video/*", true, upload))) : null,
    h("div", { class: "row", style: { justifyContent: "flex-end" } }, h("a", { class: "btn primary", href: `#/p/${enc}/style` }, t("w.next")))));
}

/* ── settings controls (shared by Style and Audio) ────── */
function settingsKit(p, onSaved) {
  const enc = encodeURIComponent(p.slug);
  const s = { ...p.settings };
  let pending = {};
  const flush = debounce(async () => {
    const patch = pending;
    pending = {};
    try { await api(`/api/projects/${enc}/settings`, { method: "PUT", json: patch }); if (onSaved) onSaved(); } catch (e) { fail(e); }
  }, 250);
  const set = (k, v) => { s[k] = v; pending[k] = v; flush(); };
  const seg = (key, options) => {
    const wrap = h("div", { class: "seg" });
    const draw = () => wrap.replaceChildren(...options.map(([val, label]) =>
      h("button", { type: "button", class: String(s[key]) === String(val) ? "on" : "", onclick: () => { set(key, val); draw(); } }, label)));
    draw();
    return wrap;
  };
  const slider = (key, min, max, step, fmt) => {
    const out = h("output", {}, fmt(s[key]));
    const input = h("input", { type: "range", min, max, step, value: s[key],
      oninput: (e) => (out.textContent = fmt(+e.target.value)), onchange: (e) => set(key, +e.target.value) });
    return h("div", { class: "slider-row" }, input, out);
  };
  const toggle = (key, onChange) => {
    const input = h("input", { type: "checkbox", checked: s[key] ? true : null,
      onchange: (e) => { set(key, e.target.checked); if (onChange) onChange(e.target.checked); } });
    return h("label", { class: "switch" }, input, h("span", {}));
  };
  const setting = (label, hint, control) => h("div", { class: "setting" },
    h("div", { class: "lbl" }, label, hint ? h("div", { class: "hint" }, hint) : null), control);
  return { s, set, seg, slider, toggle, setting };
}

const pct = (v) => `${Math.round(v * 100)}%`;

/* ── tab 3: style ────────────────────────────────────── */
async function tabStyle(body, p) {
  const enc = encodeURIComponent(p.slug);
  let fonts;
  [state.hands, state.backgrounds, fonts] = await Promise.all([api("/api/hands"), api("/api/backgrounds"), api("/api/fonts")]);
  const previewImg = h("img", { alt: "" });
  const refresh = debounce(() => { previewImg.src = `/api/projects/${enc}/still?ts=${Date.now()}`; }, 350);
  const { s, set, seg, slider, toggle, setting } = settingsKit(p, refresh);

  // backgrounds
  const bgGrid = h("div", { class: "opt-grid" });
  const drawBg = () => bgGrid.replaceChildren(
    ...state.backgrounds.map((b) => h("div", { class: "opt" + (s.background === b.id ? " on" : ""), onclick: () => { set("background", b.id); drawBg(); } },
      h("img", { src: `/api/backgrounds/preview?id=${encodeURIComponent(b.id)}`, loading: "lazy" }),
      h("div", { class: "cap" }, b.builtin ? t("bg." + b.id) : b.name))),
    h("div", { class: "opt", onclick: () => (location.hash = "#/backgrounds") }, h("div", { class: "none" }, "+ " + t("bg.upload"))));
  drawBg();

  // hands
  const handGrid = h("div", { class: "opt-grid" });
  const drawHands = () => handGrid.replaceChildren(
    ...state.hands.map((hd) => h("div", { class: "opt hand" + (s.hand === hd.id ? " on" : ""), onclick: () => { set("hand", hd.id); drawHands(); } },
      h("img", { src: `/api/hands/${encodeURIComponent(hd.id)}/image`, loading: "lazy" }), h("div", { class: "cap" }, hd.name))),
    h("div", { class: "opt" + (s.hand === "none" ? " on" : ""), onclick: () => { set("hand", "none"); drawHands(); } }, h("div", { class: "none" }, t("st.noHand"))),
    h("div", { class: "opt", onclick: () => (location.hash = "#/hands") }, h("div", { class: "none" }, "+ " + t("hands.upload"))));
  drawHands();

  // handwriting fonts
  const fontGrid = (key, list) => {
    const grid = h("div", { class: "opt-grid fonts" });
    const draw = () => grid.replaceChildren(...list.map((f) =>
      h("div", { class: "opt font" + (s[key] === f.id ? " on" : ""), onclick: () => { set(key, f.id); draw(); } },
        h("div", { class: "pic" }, h("img", { src: `/api/fonts/preview?id=${encodeURIComponent(f.id)}`, loading: "lazy", alt: f.name })),
        h("div", { class: "cap" }, t("font." + f.id)))));
    draw();
    return grid;
  };
  const swatches = (key, colors) => {
    const wrap = h("div", { class: "row", style: { gap: "8px" } });
    const draw = () => wrap.replaceChildren(...colors.map(([id, css]) =>
      h("button", { type: "button", class: "swatch" + (s[key] === id ? " on" : ""), title: t("color." + id),
        style: { background: css }, onclick: () => { set(key, id); draw(); } }, id === "auto" ? "A" : "")));
    draw();
    return wrap;
  };
  const colorInput = (key) => h("input", { type: "color", value: s[key] || "#FFD43B", class: "color",
    onchange: (e) => set(key, e.target.value) });

  const form = h("div", { class: "stack" },
    h("div", { class: "card" }, h("h3", {}, t("s.board")), bgGrid),
    h("div", { class: "card" }, h("h3", {}, t("s.hand")), handGrid,
      setting(t("s.handSize"), null, slider("hand_scale", 0.5, 1.8, 0.05, pct)),
      setting(t("s.handMotion"), t("s.handMotionHint"), toggle("hand_motion")),
      setting(t("s.handShadow"), null, toggle("hand_shadow")),
      setting(t("s.handMirror"), t("s.handMirrorHint"), toggle("hand_mirror"))),
    h("div", { class: "card" }, h("h3", {}, t("s.writing")),
      setting(t("s.handwriting"), t("s.handwritingHint"), toggle("handwriting")),
      setting(t("s.textLines"), t("s.textLinesHint"), seg("text_lines", [["write", t("s.writeText")], ["keep", t("s.keepDrawing")]])),
      setting(t("s.fontLatin"), null, fontGrid("font_latin", fonts.filter((f) => f.script === "latin"))),
      setting(t("s.fontRtl"), null, fontGrid("font_rtl", fonts.filter((f) => f.script === "rtl"))),
      setting(t("s.textColor"), null, swatches("text_color", [["auto", "linear-gradient(135deg,#222 50%,#eee 50%)"], ["black", "#26221e"],
        ["blue", "#1e50a0"], ["red", "#c83232"], ["green", "#288246"], ["purple", "#783caa"]])),
      setting(t("s.textPosition"), t("s.textPositionHint"), seg("text_position", [["bottom", t("s.bottom")], ["top", t("s.top")]])),
      setting(t("s.writeSpeed"), null, slider("write_speed", 0.5, 2, 0.1, (v) => `×${(+v).toFixed(1)}`))),
    h("div", { class: "card" }, h("h3", {}, t("s.captions")),
      setting(t("s.captionStyle"), t("s.captionsHint"), seg("captions", [["off", t("s.off")], ["clean", t("s.capClean")], ["box", t("s.capBox")],
        ["highlight", t("s.capHighlight")], ["pop", t("s.capPop")]])),
      setting(t("s.capPosition"), null, seg("caption_position", [["bottom", t("s.bottom")], ["top", t("s.top")]])),
      setting(t("s.capSize"), null, slider("caption_size", 0.6, 1.6, 0.05, pct)),
      setting(t("s.capColor"), t("s.capColorHint"), colorInput("caption_color"))),
    h("div", { class: "card" }, h("h3", {}, t("s.drawing")),
      setting(t("s.colorMode"), t("s.colorModeHint"), seg("color_mode", [["ink_then_color", t("s.inkThenColor")], ["color_strokes", t("s.colorStrokes")], ["ink_only", t("s.inkOnly")]])),
      setting(t("s.coloring"), t("s.coloringHint"), seg("coloring", [["auto", t("s.auto")], ["on", t("s.always")], ["off", t("s.never")]])),
      setting(t("s.shortLines"), t("s.shortLinesHint"), seg("short_lines", [["show", t("s.showPicture")], ["text", t("s.showText")], ["draw", t("s.drawAnyway")]])),
      setting(t("s.shortThreshold"), t("s.shortThresholdHint"), slider("short_threshold", 1, 6, 0.5, (v) => `${(+v).toFixed(1)}s`)),
      setting(t("s.sync"), t("s.syncHint"), seg("sync_mode", [["speech", t("s.speech")], ["linear", t("s.linear")]])),
      setting(t("s.drawFill"), t("s.drawFillHint"), slider("draw_fill", 0.3, 1, 0.05, pct)),
      setting(t("s.inkShare"), t("s.inkShareHint"), slider("ink_share", 0.3, 0.95, 0.05, pct)),
      setting(t("s.maxDraw"), t("s.maxDrawHint"), slider("max_draw", 2, 30, 0.5, (v) => `${v}s`)),
      setting(t("s.order"), null, seg("stroke_order", [["auto", t("s.auto")], ["left_to_right", t("s.ltr")], ["right_to_left", t("s.rtl")], ["top_to_bottom", t("s.ttb")]])),
      setting(t("s.margin"), null, slider("image_margin", 0, 0.2, 0.01, pct)),
      setting(t("s.thickness"), t("s.thicknessHint"), slider("line_thickness", 0.5, 2.5, 0.1, (v) => `×${(+v).toFixed(1)}`))),
    h("div", { class: "card" }, h("h3", {}, t("s.transition")),
      setting(t("s.transitionType"), t("s.transitionHint"), seg("transition", [["slide", t("s.slide")], ["fade", t("s.fade")], ["wipe", t("s.wipe")], ["zoom", t("s.zoom")], ["cut", t("s.cut")], ["mix", t("s.mix")]])),
      setting(t("s.transitionDur"), null, slider("transition_duration", 0.2, 1.5, 0.05, (v) => `${(+v).toFixed(2)}s`))),
    h("div", { class: "card" }, h("h3", {}, t("s.video")),
      setting(t("s.aspect"), null, seg("aspect", [["16:9", "16:9 YouTube"], ["9:16", "9:16 Shorts"], ["1:1", "1:1"], ["4:5", "4:5"]])),
      setting(t("s.resolution"), null, seg("resolution", [[720, "720p"], [1080, "1080p"], [1440, "1440p"], [2160, "4K"]])),
      setting("FPS", null, seg("fps", [[24, "24"], [30, "30"], [60, "60"]])),
      setting(t("s.language"), t("s.languageHint"), seg("language", [["auto", t("s.auto")], ["en", "English"], ["fa", "فارسی"]]))));
  const preview = h("div", { class: "preview-box stack" },
    h("div", { class: "card stack" },
      h("div", { class: "row spread" }, h("h3", { style: { margin: 0 } }, t("s.preview")),
        h("button", { class: "iconbtn", html: ICONS.refresh, onclick: refresh })),
      previewImg, h("p", { class: "small faint" }, t("s.previewHint"))));
  body.replaceChildren(h("div", { class: "grid-style" }, form, preview));
  refresh();
}

/* ── tab 4: audio ────────────────────────────────────── */
async function tabAudio(body, p) {
  const { s, set, seg, slider, toggle, setting } = settingsKit(p);
  const player = h("audio", { controls: true, style: { width: "100%" } });
  const play = (url, label) => {
    player.src = url;
    nowPlaying.textContent = label;
    player.play().catch(() => {});
  };
  const nowPlaying = h("span", { class: "small muted" }, "");
  const tracks = await api("/api/music");
  const grid = h("div", { class: "opt-grid tracks" });
  const draw = (list) => grid.replaceChildren(
    h("div", { class: "opt track" + (s.music === "none" ? " on" : ""), onclick: () => { set("music", "none"); draw(list); } },
      h("div", { class: "track-body" }, h("b", {}, t("a.noMusic")), h("span", { class: "small muted" }, t("a.voiceOnly")))),
    ...list.map((m) => h("div", { class: "opt track" + (s.music === m.id ? " on" : ""), onclick: () => { set("music", m.id); draw(list); } },
      h("div", { class: "track-body" },
        h("b", {}, m.builtin ? t("music." + m.id.split(":")[1]) : m.name),
        h("span", { class: "small muted" }, m.builtin ? t("music." + m.id.split(":")[1] + ".hint") : t("a.yourTrack"))),
      h("div", { class: "row", style: { gap: "6px" } },
        h("button", { class: "iconbtn", html: ICONS.play, title: t("a.listen"), onclick: (e) => {
          e.stopPropagation();
          if (m.builtin) toast(t("a.preparing"));
          play(`/api/music/play?id=${encodeURIComponent(m.id)}`, m.builtin ? t("music." + m.id.split(":")[1]) : m.name);
        } }),
        m.builtin ? null : h("button", { class: "iconbtn", html: ICONS.x, title: t("w.delete"), onclick: async (e) => {
          e.stopPropagation();
          if (!(await confirmModal(t("a.deleteConfirm")))) return;
          await api(`/api/music/${encodeURIComponent(m.id.slice(5))}`, { method: "DELETE" }).catch(fail);
          if (s.music === m.id) set("music", "none");
          draw(await api("/api/music"));
        } })))));
  draw(tracks);
  const upload = dropzone(t("a.drop"), "MP3 · WAV · M4A · OGG · FLAC", "audio/*", true, async (files) => {
    for (const f of files) {
      const fd = new FormData(); fd.append("file", f);
      try { const r = await api("/api/music", { method: "POST", form: fd }); set("music", r.id); } catch (e) { fail(e); }
    }
    toast(t("msg.saved"), "ok");
    draw(await api("/api/music"));
  });
  body.replaceChildren(h("div", { class: "stack" },
    h("div", { class: "card stack" },
      h("div", {}, h("h2", {}, t("a.sfx")), h("p", { class: "muted small" }, t("a.sfxHint"))),
      setting(t("a.sfxOn"), null, toggle("sfx")),
      setting(t("a.sfxVolume"), t("a.relative"), slider("sfx_volume", 0, 1, 0.05, pct)),
      setting(t("a.sample"), null, h("div", { class: "row" },
        h("button", { class: "btn", onclick: () => play("/api/sfx/preview?dark=false", t("a.marker")) }, icon("play"), t("a.marker")),
        h("button", { class: "btn", onclick: () => play("/api/sfx/preview?dark=true", t("a.chalk")) }, icon("play"), t("a.chalk"))))),
    h("div", { class: "card stack" },
      h("div", {}, h("h2", {}, t("a.music")), h("p", { class: "muted small" }, t("a.musicHint"))),
      grid, upload,
      setting(t("a.musicVolume"), t("a.relative"), slider("music_volume", 0, 1, 0.05, pct)),
      setting(t("a.ducking"), t("a.duckingHint"), slider("ducking", 0, 1, 0.05, pct))),
    h("div", { class: "card stack" },
      h("div", {}, h("h2", {}, t("a.loudness")), h("p", { class: "muted small" }, t("a.loudnessHint"))),
      setting(t("a.normalize"), null, toggle("normalize_audio")),
      setting(t("a.target"), null, seg("loudness", [[-14, "YouTube −14"], [-16, "Podcast −16"], [-23, "TV −23"]]))),
    h("div", { class: "card stack" }, h("div", { class: "row spread" }, h("h3", { style: { margin: 0 } }, t("a.player")), nowPlaying), player),
    h("div", { class: "row", style: { justifyContent: "flex-end" } }, h("a", { class: "btn primary", href: `#/p/${encodeURIComponent(p.slug)}/sync` }, t("w.next")))));
}

/* ── tab 5: sync ─────────────────────────────────────── */
async function tabSync(body, p) {
  const enc = encodeURIComponent(p.slug);
  const hasWhisper = state.info.whisper.length > 0;
  let method = hasWhisper ? "whisper" : "estimate";
  let srtText = "";
  const model = h("select", {}, ["tiny", "base", "small", "medium", "large-v3", "turbo"].map((m) =>
    h("option", { value: m, selected: p.settings.whisper_model === m ? true : null }, m)));
  const methods = h("div", { class: "methods" });
  const srtInput = h("input", { type: "file", accept: ".srt", hidden: true, onchange: async (e) => {
    srtText = await e.target.files[0].text(); srtName.textContent = e.target.files[0].name; } });
  const srtName = h("span", { class: "small muted" }, "");
  const drawMethods = () => methods.replaceChildren(
    h("div", { class: "method" + (method === "whisper" ? " on" : ""), onclick: () => { method = "whisper"; drawMethods(); } },
      h("b", {}, "Whisper " + (hasWhisper ? "✓" : "✗")), h("p", {}, hasWhisper ? t("y.whisper") : t("y.noWhisper"))),
    h("div", { class: "method" + (method === "srt" ? " on" : ""), onclick: () => { method = "srt"; drawMethods(); srtInput.click(); } },
      h("b", {}, t("y.srt")), h("p", {}, t("y.srtHint")), srtName),
    h("div", { class: "method" + (method === "estimate" ? " on" : ""), onclick: () => { method = "estimate"; drawMethods(); } },
      h("b", {}, t("y.estimate")), h("p", {}, t("y.estimateHint"))));
  drawMethods();
  const retrans = h("input", { type: "checkbox" });
  const slot = h("div", { class: "jobslot" });
  const run = async () => {
    if (!p.narration) return toast(t("msg.needNarration"), "error");
    if (method === "srt" && !srtText) return toast(t("y.pickSrt"), "error");
    try {
      const job = await api(`/api/projects/${enc}/align`, { method: "POST", json: { method, srt: srtText, whisper_model: model.value, retranscribe: retrans.checked } });
      watchJob(job, slot);
    } catch (e) { fail(e); }
  };
  const top = h("div", { class: "card stack" },
    h("div", {}, h("h2", {}, t("y.title")), h("p", { class: "muted small" }, t("y.hint"))),
    methods,
    h("div", { class: "row" },
      h("label", { class: "row small muted" }, t("y.model"), model),
      h("label", { class: "row small muted", style: { cursor: "pointer" } }, retrans, t("y.retranscribe")),
      h("span", { class: "grow" }),
      h("button", { class: "btn primary", onclick: run }, icon("sparkle"), p.aligned ? t("y.rerun") : t("y.run"))),
    srtInput, slot);

  const children = [top];
  const tl = p.timeline;
  if (tl) {
    const audio = new Audio(`/api/projects/${enc}/narration`);
    state.audio = audio;
    let stopAt = null, playingRow = null;
    audio.addEventListener("timeupdate", () => { if (stopAt !== null && audio.currentTime >= stopAt) { audio.pause(); stopAt = null; playingRow && playingRow.classList.remove("playing"); } });
    const edits = {};
    const imgs = p.image_files;
    const previewSlot = h("div", { class: "jobslot" });
    const order = [...tl.lines].sort((a, b) => a.start - b.start);
    const quick = new Set(p.settings.short_lines === "draw" ? [] : order.filter((ln, i) =>
      ((i + 1 < order.length ? order[i + 1].start : tl.duration + (+p.settings.tail || 0.6)) - ln.start) < +p.settings.short_threshold).map((ln) => ln.id));
    const previewVideo = h("div", {});
    const rows = tl.lines.map((ln) => {
      const s = h("input", { type: "number", step: "0.05", value: ln.start.toFixed(2), onchange: (e) => { (edits[ln.id] ||= { id: ln.id, start: ln.start, end: ln.end }).start = +e.target.value; } });
      const e2 = h("input", { type: "number", step: "0.05", value: ln.end.toFixed(2), onchange: (e) => { (edits[ln.id] ||= { id: ln.id, start: ln.start, end: ln.end }).end = +e.target.value; } });
      const name = imgs[String(ln.id)];
      const tr = h("tr", {},
        h("td", {}, h("b", {}, ln.id)),
        h("td", {}, name ? h("img", { src: `/api/projects/${enc}/images/${encodeURIComponent(name)}?thumb=1`, loading: "lazy" }) : h("span", { class: "faint small" }, "—")),
        h("td", { dir: "auto", style: { maxWidth: "420px" } }, ln.text,
          quick.has(ln.id) ? h("span", { class: "badge quick", title: t("y.quickHint") }, t(p.settings.short_lines === "text" ? "y.quickText" : "y.quick")) : null),
        h("td", {}, s), h("td", {}, e2),
        h("td", {}, h("div", { class: "row", style: { gap: "6px", flexWrap: "nowrap" } },
          h("button", { class: "iconbtn", title: t("y.play"), html: ICONS.play, onclick: () => {
            playingRow && playingRow.classList.remove("playing");
            playingRow = tr; tr.classList.add("playing");
            audio.currentTime = +s.value; stopAt = +e2.value + 0.15; audio.play();
          } }),
          name ? h("button", { class: "iconbtn", title: t("y.previewLine"), html: ICONS.film, onclick: async () => {
            try {
              const job = await api(`/api/projects/${enc}/render`, { method: "POST", json: { line: ln.id, draft: true } });
              const res = await watchJob(job, previewSlot, false);
              if (res.status === "done") {
                previewVideo.replaceChildren(h("div", { class: "card stack" }, h("h3", {}, `${t("y.previewOf")} #${ln.id}`),
                  h("video", { src: `/api/projects/${enc}/output/${encodeURIComponent(res.result.file)}`, controls: true, autoplay: true, style: { width: "100%", borderRadius: "10px" } })));
                previewSlot.replaceChildren();
                previewVideo.scrollIntoView({ behavior: "smooth", block: "center" });
              }
            } catch (err) { fail(err); }
          } }) : null)));
      return tr;
    });
    children.push(h("div", { class: "card stack" },
      h("div", { class: "row spread" },
        h("div", {}, h("h2", {}, t("y.timeline")), h("p", { class: "muted small" }, `${t("y.source")}: ${tl.source} · ${t("y.duration")} ${fmtTime(tl.duration)}`)),
        h("button", { class: "btn", onclick: async () => {
          try { await api(`/api/projects/${enc}/timeline`, { method: "PUT", json: { lines: Object.values(edits) } }); toast(t("msg.saved"), "ok"); route(); } catch (e) { fail(e); }
        } }, t("y.saveTimes"))),
      previewSlot, previewVideo,
      h("div", { class: "tl-wrap" }, h("table", { class: "tl" },
        h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, t("w.image")), h("th", {}, t("w.text")), h("th", {}, t("y.start")), h("th", {}, t("y.end")), h("th", {}, ""))),
        h("tbody", {}, rows)))));
    children.push(h("div", { class: "row", style: { justifyContent: "flex-end" } }, h("a", { class: "btn primary", href: `#/p/${enc}/export` }, t("w.next"))));
  }
  body.replaceChildren(h("div", { class: "stack" }, children));
}

/* ── tab 6: export ───────────────────────────────────── */
async function tabExport(body, p) {
  const enc = encodeURIComponent(p.slug);
  const s = p.settings;
  const quality = h("div", { class: "seg" });
  let q = s.quality;
  const drawQ = () => quality.replaceChildren(...[["high", t("e.high")], ["draft", t("e.draft")]].map(([v, l]) =>
    h("button", { class: q === v ? "on" : "", onclick: async () => { q = v; drawQ(); await api(`/api/projects/${enc}/settings`, { method: "PUT", json: { quality: v } }).catch(fail); } }, l)));
  drawQ();
  const slot = h("div", { class: "jobslot" });
  const problems = [];
  if (!p.narration) problems.push(t("msg.needNarration"));
  if (!p.lines) problems.push(t("msg.needScript"));
  const claudeMode = s.engine === "claude";
  if (!p.images && p.settings.text_lines !== "write" && !claudeMode) problems.push(t("msg.needImages"));
  if (claudeMode && p.missing_images.length) problems.push(`${p.missing_images.length} ${t((state.info || {}).claude ? "e.claudeWillDraw" : "e.claudeMissing")}`);
  else if (p.missing_images.length && p.settings.text_lines !== "write") problems.push(`${p.missing_images.length} ${t("i.missingCount")} (${t("e.missingOk")})`);
  if (!p.aligned) problems.push(t("e.notSynced"));
  const render = async () => {
    try {
      if (!p.aligned) return oneClick(p.slug);
      const job = await api(`/api/projects/${enc}/render`, { method: "POST", json: {} });
      watchJob(job, slot);
    } catch (e) { fail(e); }
  };
  const summary = h("div", { class: "card stack" },
    h("div", { class: "row spread" },
      h("div", {}, h("h2", {}, t("e.title")),
        h("p", { class: "muted small" }, `${s.aspect} · ${s.resolution}p · ${s.fps} fps · ${s.background.startsWith("custom:") ? s.background.slice(7) : t("bg." + s.background)} · ${p.lines} ${t("w.lines")}${p.timeline ? " · " + fmtTime(p.timeline.duration) : ""}`)),
      h("div", { class: "row" }, quality, h("button", { class: "btn primary big", onclick: render }, icon("film"), t("e.render")))),
    problems.length ? h("ul", { class: "small", style: { color: "var(--warn)", margin: 0 } }, problems.map((x) => h("li", {}, x))) : null,
    slot);
  const vids = p.renders.map((name) => h("div", { class: "card stack" },
    h("video", { src: `/api/projects/${enc}/output/${encodeURIComponent(name)}`, controls: true, preload: "metadata" }),
    h("div", { class: "row spread" }, h("span", { class: "small muted" }, name),
      h("div", { class: "row" },
        h("a", { class: "btn", href: `/api/projects/${enc}/output/${encodeURIComponent(name)}?download=1` }, icon("download"), t("e.download")),
        (p.subtitles || []).includes(name.replace(/\.mp4$/, ".srt"))
          ? h("a", { class: "btn ghost", href: `/api/projects/${enc}/output/${encodeURIComponent(name.replace(/\.mp4$/, ".srt"))}?download=1` }, t("e.srt")) : null,
        h("button", { class: "iconbtn", html: ICONS.x, title: t("w.delete"), onclick: async () => {
          if (!(await confirmModal(t("e.deleteConfirm")))) return;
          await api(`/api/projects/${enc}/output/${encodeURIComponent(name)}`, { method: "DELETE" }).catch(fail); route();
        } })))));
  body.replaceChildren(h("div", { class: "stack" }, summary,
    vids.length ? h("h3", {}, t("e.videos")) : null,
    vids.length ? h("div", { class: "videos" }, vids) : null));
}

/* ── hands library ───────────────────────────────────── */
async function viewHands() {
  state.hands = await api("/api/hands");
  const grid = h("div", { class: "opt-grid", style: { gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))" } },
    state.hands.map((hd) => h("div", { class: "opt hand" },
      h("img", { src: `/api/hands/${encodeURIComponent(hd.id)}/image?ts=${Date.now()}` }),
      h("div", { class: "cap" }, hd.name, hd.builtin ? h("span", { class: "faint" }, t("w.builtin")) :
        h("span", { class: "row", style: { gap: "4px" } },
          h("button", { class: "btn ghost small", onclick: () => tipEditor(hd) }, t("hands.tip")),
          h("button", { class: "iconbtn", html: ICONS.x, onclick: async () => {
            if (!(await confirmModal(t("hands.deleteConfirm")))) return;
            await api(`/api/hands/${encodeURIComponent(hd.id)}`, { method: "DELETE" }).catch(fail); route();
          } }))))));
  $("#view").replaceChildren(h("div", { class: "stack" },
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, t("nav.hands")), h("p", { class: "muted" }, t("hands.lead")))),
    h("div", { class: "card stack" },
      dropzone(t("hands.drop"), t("hands.dropHint"), "image/png,image/webp,image/*", true, async (files) => {
        for (const f of files) {
          const fd = new FormData(); fd.append("file", f); fd.append("name", f.name.replace(/\.[^.]+$/, ""));
          try {
            const r = await api("/api/hands", { method: "POST", form: fd });
            toast(t("msg.saved"), "ok");
            const hands = await api("/api/hands");
            const hd = hands.find((x) => x.id === r.id);
            if (hd && files.length === 1) { await tipEditor(hd); }
          } catch (e) { fail(e); }
        }
        route();
      })),
    grid));
}

function tipEditor(hd) {
  return new Promise((resolve) => {
    const modal = $("#modal");
    let tip = hd.tip ? [...hd.tip] : [0, 0];
    const mark = h("i", { class: "mark" });
    const img = h("img", { src: `/api/hands/${encodeURIComponent(hd.id)}/image?ts=${Date.now()}` });
    const place = () => {
      if (!img.naturalWidth) return;
      mark.style.left = `${(tip[0] / img.naturalWidth) * img.clientWidth}px`;
      mark.style.top = `${(tip[1] / img.naturalHeight) * img.clientHeight}px`;
    };
    img.addEventListener("load", place);
    const pick = h("div", { class: "tip-pick", onclick: (e) => {
      const r = img.getBoundingClientRect();
      tip = [Math.round(((e.clientX - r.left) / r.width) * img.naturalWidth), Math.round(((e.clientY - r.top) / r.height) * img.naturalHeight)];
      place();
    } }, img, mark);
    const size = h("input", { type: "range", min: 0.2, max: 0.9, step: 0.02, value: hd.size || 0.46 });
    const name = h("input", { type: "text", value: hd.name });
    const close = () => { modal.hidden = true; modal.replaceChildren(); resolve(); route(); };
    modal.replaceChildren(h("div", { class: "card stack" },
      h("h2", {}, t("hands.tipTitle")), h("p", { class: "muted small" }, t("hands.tipHint")),
      h("div", { style: { textAlign: "center" } }, pick),
      h("label", { class: "field" }, t("hands.name"), name),
      h("label", { class: "field" }, t("hands.size"), size),
      h("div", { class: "row", style: { justifyContent: "flex-end" } },
        h("button", { class: "btn ghost", onclick: close }, t("w.cancel")),
        h("button", { class: "btn primary", onclick: async () => {
          try { await api(`/api/hands/${encodeURIComponent(hd.id)}`, { method: "PUT", json: { tip, size: +size.value, name: name.value } }); toast(t("msg.saved"), "ok"); } catch (e) { fail(e); }
          close();
        } }, t("w.save")))));
    modal.hidden = false;
  });
}

/* ── backgrounds library ─────────────────────────────── */
async function viewBackgrounds() {
  state.backgrounds = await api("/api/backgrounds");
  const grid = h("div", { class: "opt-grid", style: { gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" } },
    state.backgrounds.map((b) => h("div", { class: "opt" },
      h("img", { src: `/api/backgrounds/preview?id=${encodeURIComponent(b.id)}` }),
      h("div", { class: "cap" }, b.builtin ? t("bg." + b.id) : b.name,
        b.builtin ? h("span", { class: "faint" }, b.dark ? t("bg.dark") : t("w.builtin")) :
          h("button", { class: "iconbtn", html: ICONS.x, onclick: async () => {
            await api(`/api/backgrounds/${encodeURIComponent(b.id.slice(7))}`, { method: "DELETE" }).catch(fail); route();
          } })))));
  $("#view").replaceChildren(h("div", { class: "stack" },
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, t("nav.backgrounds")), h("p", { class: "muted" }, t("bg.lead")))),
    h("div", { class: "card" }, dropzone(t("bg.drop"), "PNG · JPG · WebP", "image/*", true, async (files) => {
      for (const f of files) {
        const fd = new FormData(); fd.append("file", f);
        await api("/api/backgrounds", { method: "POST", form: fd }).catch(fail);
      }
      toast(t("msg.saved"), "ok"); route();
    })),
    grid));
}

/* ── help ────────────────────────────────────────────── */
function viewHelp() {
  $("#view").replaceChildren(h("div", { class: "card help", html: t("help.html") }));
}

/* ── boot ────────────────────────────────────────────── */
async function boot() {
  applyTheme(localStorage.getItem("swa-theme") || "dark");
  applyLang(localStorage.getItem("swa-lang") || "en");
  $("#themeBtn").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  $("#langBtn").addEventListener("click", () => { applyLang(getLang() === "fa" ? "en" : "fa"); route(); });
  window.addEventListener("hashchange", route);
  try { state.info = await api("/api/info"); } catch (e) { fail(e); }
  route();
}
boot();
