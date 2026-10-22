/* app.js — starts the app: connects to the server, and wires the header (connection status,
 * Docs, Source code, Settings, theme) and the Settings and Documentation dialogs. The
 * documentation text comes from templates/documentation.html. The panels themselves live in
 * form.js and monitor.js. */
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
      banner(xtb ? null : "warn", "Connected, but xTB is not available on the server, so runs cannot start. " +
        "Install <code>tblite</code> there, or set <code>ORCA_BIN</code> for ORCA's built-in xTB (see app/server/README.md).");
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
  // The source code link is fixed: the server's repo_url, else the project's GitHub repository.
  function repoUrl() {
    return (serverRepoUrl || config.DEFAULT_REPO_URL).replace(/\/+$/, "");
  }

  function updateLinks() {
    $("sourceBtn").href = repoUrl();
  }

  // ------------------------------------------------------------------ settings dialog
  function openSettings(note) {
    $("settingsNote").textContent = note || "These settings are stored in this browser only.";
    $("setApi").value = config.apiBase();
    $("setApi").placeholder = config.defaultApiBase() || "(this page's server)";
    $("setToken").value = config.token();
    $("setToken").type = "password"; $("showToken").textContent = "Show";
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
      config.save({ apiBase: $("setApi").value, token: $("setToken").value, pollSeconds: $("setPoll").value });
      toast("Settings saved");
      updateLinks();
      connect();
    });
  }

  // ------------------------------------------------------------------ documentation
  // The dialog shows templates/documentation.html with its {{PLACEHOLDERS}} filled in. The file is
  // read again each time, so edits show up without reloading the app.
  async function openDocs() {
    const body = $("docsBody");
    $("docsDialog").showModal();
    try {
      const response = await fetch("templates/documentation.html", { cache: "no-cache" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const html = (await response.text()).replace(/<!--[\s\S]*?-->/g, "");
      const values = { REPO_URL: esc(repoUrl()), API_DOCS_URL: esc(api.docsUrl()), CONTRIBUTORS: contributorsHtml() };
      body.innerHTML = html.replace(/\{\{(\w+)\}\}/g, (match, key) => (key in values ? values[key] : match));
      body.querySelectorAll("img.avatar").forEach((img) => img.addEventListener("error", () => {
        const fallback = document.createElement("span");      // GitHub unreachable: show the initial
        fallback.className = "avatar";
        fallback.textContent = img.dataset.initial;
        img.replaceWith(fallback);
      }));
    } catch (e) {
      body.innerHTML = '<p class="problem">The documentation could not be loaded (' + esc(e.message) + "). " +
        "It is read from <code>templates/documentation.html</code>, which needs the app to be opened from a web server, " +
        "not from a file on disk.</p>";
    }
  }

  // One card per person in js/contributors.js. The avatar comes from GitHub; if it cannot load,
  // the person's initial is shown instead.
  function contributorsHtml() {
    const people = MOL.contributors || [];
    if (!people.length) return '<p class="note">No contributors listed yet.</p>';
    return '<div class="people">' + people.map((p) => {
      const initial = esc((p.name || "?").trim().charAt(0).toUpperCase());
      const avatar = p.github
        ? `<img class="avatar" src="https://github.com/${encodeURIComponent(p.github)}.png?size=96" alt="" loading="lazy" data-initial="${initial}">`
        : `<span class="avatar">${initial}</span>`;
      const links = [
        p.email ? `<a href="mailto:${esc(p.email)}">${esc(p.email)}</a>` : "",
        p.github ? `<a href="https://github.com/${encodeURIComponent(p.github)}" target="_blank" rel="noopener">github.com/${esc(p.github)}</a>` : ""
      ].filter(Boolean).join("");
      const also = (p.also || []).map((a) => `<span class="chip">${esc(a)}</span>`).join("");
      return `<div class="person">${avatar}<div class="person-text">` +
        `<div class="person-name">${esc(p.name)}</div>` +
        (p.focus ? `<div class="person-focus">${esc(p.focus)}</div>` : "") +
        (also ? `<div class="person-also">${also}</div>` : "") +
        (p.note ? `<div class="note">${esc(p.note)}</div>` : "") +
        `<div class="person-links">${links}</div></div></div>`;
    }).join("") + "</div>";
  }

  // ------------------------------------------------------------------ theme
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

  // ------------------------------------------------------------------ start
  function boot() {
    if (!MOL.chem.hasOCL()) {
      banner("warn", "The structure library (OpenChemLib) did not load, so molecules cannot be drawn. Runs still work.");
    }
    initTheme();
    bindSettings();
    $("docsBtn").addEventListener("click", openDocs);
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
