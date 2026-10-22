/* app.js — starts the app: connects to the server, and wires the header (connection status,
 * Docs, Source code, Settings, theme), the Settings and Documentation dialogs, and the
 * Contributors section. The panels themselves live in form.js and monitor.js. */
(function () {
  "use strict";
  const { $, esc, toast } = MOL.ui;
  const api = MOL.api, config = MOL.config;

  let serverRepoUrl = "";      // repo link reported by the server (/api/health)
  let askedForToken = false;   // open Settings by itself only once per page load

  // ------------------------------------------------------------------ connection
  function setConnection(kind, text, title) {
    const pill = $("connPill");
    pill.className = "conn " + kind;
    $("connText").textContent = text;
    pill.title = (title || text) + " — click for settings";
  }

  function banner(kind, html) {
    const b = $("globalBanner");
    if (!kind) { b.hidden = true; return; }
    b.className = "banner global " + kind;
    $("globalBannerText").innerHTML = html;
    b.hidden = false;
  }

  async function connect() {
    setConnection("checking", "Connecting…");
    const where = esc(api.base() || location.origin);
    let health;
    try {
      health = await api.health();
    } catch (e) {
      setConnection("down", "Offline", "Cannot reach " + (api.base() || location.origin));
      banner("error", `Cannot reach the MolCurator server at <code>${where}</code> (${esc(e.message)}). ` +
        "Start it with <code>./run.sh</code>, or set its address in <b>Settings</b>.");
      MOL.form.setConnected(false);
      return;
    }
    serverRepoUrl = health.repo_url || "";
    updateLinks();
    if (health.auth_required && !config.token()) {
      needToken(where);
      return;
    }
    try {
      const [system, presets] = await Promise.all([api.system(), api.presets()]);
      const xtb = system.tools.xtb.found;
      setConnection(xtb ? "live" : "warn", xtb ? "Connected" : "Connected · no xTB",
        `Server ${health.version} at ${api.base() || location.origin}`);
      banner(xtb ? null : "warn", "Connected, but xTB was not found on the server, so runs cannot start. " +
        "Set <code>XTB_BIN</code> on the server (see backend/README.md).");
      MOL.form.setConnected(true, system, presets);
      MOL.monitor.refreshList();
    } catch (e) {
      if (e.status === 401) { needToken(where); return; }
      setConnection("down", "Error", e.message);
      banner("error", esc(e.message));
      MOL.form.setConnected(false);
    }
  }

  function needToken(where) {
    setConnection("warn", "Token needed", "The server needs an API token");
    banner("warn", `The server at <code>${where}</code> needs an API token. The server prints it when it starts; ` +
      "enter it in <b>Settings</b>.");
    MOL.form.setConnected(false);
    if (!askedForToken) { askedForToken = true; openSettings("Enter the API token the server printed at startup."); }
  }

  // ------------------------------------------------------------------ links
  function repoUrl() {
    return (config.repoUrl() || serverRepoUrl || config.DEFAULT_REPO_URL).replace(/\/+$/, "");
  }

  function updateLinks() {
    const repo = repoUrl();
    $("sourceBtn").href = repo;
    $("footSource").href = repo;
    $("footApi").href = api.docsUrl();
    $("docApi").href = api.docsUrl();
    $("docGuide").href = repo + "/tree/main/docs/api";
    $("docReadme").href = repo + "#readme";
    $("docTrace").href = repo + "/blob/main/docs/trace-format.md";
  }

  // ------------------------------------------------------------------ settings dialog
  function openSettings(note) {
    $("settingsNote").textContent = note || "These settings are stored in this browser only.";
    $("setApi").value = config.apiBase();
    $("setApi").placeholder = config.defaultApiBase() || "(this page's server)";
    $("setToken").value = config.token();
    $("setToken").type = "password"; $("showToken").textContent = "Show";
    $("setRepo").value = config.repoUrl();
    $("setRepo").placeholder = serverRepoUrl || config.DEFAULT_REPO_URL;
    $("setPoll").value = config.pollSeconds();
    $("settingsResult").innerHTML = "";
    $("settingsDialog").showModal();
  }

  // Checks the values typed in the dialog without saving them.
  async function testConnection() {
    const out = $("settingsResult");
    const base = $("setApi").value.trim().replace(/\/+$/, "");
    const headers = { "ngrok-skip-browser-warning": "1" };
    if ($("setToken").value.trim()) headers.Authorization = "Bearer " + $("setToken").value.trim();
    out.innerHTML = '<div class="note">Testing…</div>';
    try {
      const h = await fetch(base + "/api/health", { headers: headers });
      if (!h.ok) throw new Error("HTTP " + h.status);
      const health = await h.json();
      const s = await fetch(base + "/api/system", { headers: headers });
      if (s.status === 401) { out.innerHTML = '<div class="problem">✕ Server reached, but the token is missing or wrong.</div>'; return; }
      if (!s.ok) throw new Error("HTTP " + s.status);
      const sys = await s.json();
      out.innerHTML = `<div class="okline">✓ Connected to MolCurator API ${esc(health.version)}. ` +
        `xTB ${sys.tools.xtb.found ? "found" : "not found"}, ORCA ${sys.tools.orca.found ? "found" : "not found"}.</div>`;
    } catch (e) {
      out.innerHTML = `<div class="problem">✕ Cannot reach ${esc(base || location.origin)}: ${esc(e.message)}. ` +
        "Check the address; if the app is on another site, the server must allow it (MOLCURATOR_CORS_ORIGINS).</div>";
    }
  }

  function bindSettings() {
    $("settingsBtn").addEventListener("click", () => openSettings());
    $("connPill").addEventListener("click", () => openSettings());
    $("testConn").addEventListener("click", testConnection);
    $("showToken").addEventListener("click", () => {
      const field = $("setToken");
      field.type = field.type === "password" ? "text" : "password";
      $("showToken").textContent = field.type === "password" ? "Show" : "Hide";
    });
    $("settingsDialog").addEventListener("close", () => {
      if ($("settingsDialog").returnValue !== "save") return;
      config.save({ apiBase: $("setApi").value, token: $("setToken").value, repoUrl: $("setRepo").value,
                    pollSeconds: $("setPoll").value });
      toast("Settings saved");
      updateLinks();
      connect();
    });
  }

  // ------------------------------------------------------------------ docs, theme, contributors
  function bindDocs() {
    const open = () => { updateLinks(); $("docsDialog").showModal(); };
    $("docsBtn").addEventListener("click", open);
    $("footDocs").addEventListener("click", open);
  }

  function initTheme() {
    const saved = config.theme();
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    $("themeBtn").addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme");
      const dark = current ? current === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
      const next = dark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      config.save({ theme: next });
    });
  }

  function renderContributors() {
    const people = MOL.contributors || [];
    $("contributors").innerHTML = people.length
      ? people.map((p) => {
          const name = p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.name)}</a>` : esc(p.name);
          return `<div class="person"><span class="avatar">${esc((p.name || "?").trim().charAt(0).toUpperCase())}</span>` +
                 `<span><b>${name}</b>${p.role ? `<br><span class="note">${esc(p.role)}</span>` : ""}</span></div>`;
        }).join("")
      : '<p class="note">No contributors listed yet.</p>';
  }

  // ------------------------------------------------------------------ start
  function boot() {
    if (!MOL.chem.hasOCL()) {
      banner("warn", "The structure library (OpenChemLib) did not load, so molecules cannot be drawn. Runs still work.");
    }
    initTheme();
    bindSettings();
    bindDocs();
    renderContributors();
    updateLinks();
    MOL.form.init((runId) => MOL.monitor.refreshList(runId));
    MOL.monitor.init();
    connect();
  }

  // index.html loads OpenChemLib and 3Dmol first and fires "molc-libs-ready" when done.
  function start() {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
    else boot();
  }
  if (window.__molcLibs) start(); else window.addEventListener("molc-libs-ready", start);
})();
