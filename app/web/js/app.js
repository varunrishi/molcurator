/* app.js — starts the app: asks for the server address and API token (Connect dialog, opened
 * as soon as the page loads), connects, and moves to the agent view. Also wires the header
 * (connection status, Docs, Source code, Settings, theme) and the Settings and Documentation
 * dialogs. The documentation text comes from templates/documentation.html. The panels
 * themselves live in form.js, monitor.js and assistant.js. */
(function () {
  "use strict";
  const { $, esc, toast } = MOL.ui;
  const api = MOL.api, config = MOL.config;

  let serverRepoUrl = "";      // repo link reported by the server (/api/health)

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

  // opts.toAgent: after a successful connection, open the agent view (if the server has Claude).
  async function connect(opts) {
    opts = opts || {};
    setConnection("checking", "Connecting…");
    const where = esc(api.base() || location.origin);
    let health;
    try {
      health = await api.health();
    } catch (e) {
      setConnection("down", "Offline", "Cannot reach " + (api.base() || location.origin));
      banner("error", `Cannot reach the MolCurator server at <code>${where}</code> (${esc(e.message)}). ` +
        'Start it with <code>scripts/run.sh</code>, or <a href="#" data-open-connect>connect to another server</a>.');
      MOL.form.setConnected(false);
      setAgentAvailable(false);
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
      const xtb = system.tools.xtb.found, orca = system.tools.orca.found;
      setConnection(xtb ? "live" : "warn", xtb ? "Connected" : "Connected · no xTB",
        `Server ${health.version} at ${api.base() || location.origin}`);
      if (!xtb) {
        banner("warn", "Connected, but the server can run no xTB: " + esc(system.tools.xtb.note) +
          " Runs whose PREDICT uses xTB cannot start (see app/server/README.md).");
      } else if (!orca) {
        banner("warn", "Connected. ORCA was not found on the server, so QM validation is off and targets whose " +
          "PREDICT needs ORCA (e.g. the S1–T1 gap) cannot run. Set <code>ORCA_BIN</code> on the server to enable them.");
      } else {
        banner(null);
      }
      MOL.form.setConnected(true, system, presets);
      MOL.assistant.setModel(system.assistant && system.assistant.model);
      setAgentAvailable(!!(system.assistant && system.assistant.available), opts.toAgent);
      MOL.monitor.refreshList();
    } catch (e) {
      if (e.status === 401) { needToken(where); return; }
      setConnection("down", "Error", e.message);
      setAgentAvailable(false);
      banner("error", esc(e.message));
      MOL.form.setConnected(false);
    }
  }

  function needToken(where) {
    setConnection("warn", "Token needed", "The server needs an API token");
    banner("warn", `The server at <code>${where}</code> needs an API token. The server prints it when it starts; ` +
      '<a href="#" data-open-connect>enter it here</a>.');
    MOL.form.setConnected(false);
    setAgentAvailable(false);
  }

  // ------------------------------------------------------------------ connect dialog
  // Opens as soon as the app loads, prefilled with the saved address and token (or a #token= link).
  // The dialog stays open until the server answers with the token accepted, or "Not now".
  function openConnect(note) {
    $("connectNote").textContent = note || "Enter the server's address and the API token it printed at startup.";
    $("conApi").value = config.apiBase();
    $("conApi").placeholder = config.defaultApiBase() || location.origin;
    $("conToken").value = config.token();
    $("conToken").type = "password"; $("conShowToken").textContent = "Show";
    $("connectResult").innerHTML = "";
    $("connectGo").disabled = false;
    if (!$("connectDialog").open) $("connectDialog").showModal();
    const empty = ["conApi", "conToken"].find((id) => !$(id).value && !(id === "conApi" && config.defaultApiBase() === ""));
    (empty ? $(empty) : $("connectGo")).focus();
  }

  async function submitConnect(event) {
    event.preventDefault();
    const base = $("conApi").value.trim().replace(/\/+$/, ""), token = $("conToken").value.trim();
    const out = $("connectResult");
    $("connectGo").disabled = true;
    out.innerHTML = '<div class="note">Connecting…</div>';
    const result = await probe(base, token);
    $("connectGo").disabled = false;
    if (!result.ok) { out.innerHTML = `<div class="problem">✕ ${result.message}</div>`; return; }
    config.save({ apiBase: base, token: token });
    $("connectDialog").close();
    updateLinks();
    await connect({ toAgent: true });
  }

  function bindConnect() {
    $("connectForm").addEventListener("submit", submitConnect);
    $("connectLater").addEventListener("click", () => { $("connectDialog").close(); connect(); });
    $("connectDialog").addEventListener("cancel", (e) => { e.preventDefault(); $("connectDialog").close(); connect(); });
    $("conShowToken").addEventListener("click", () => {
      const field = $("conToken");
      field.type = field.type === "password" ? "text" : "password";
      $("conShowToken").textContent = field.type === "password" ? "Show" : "Hide";
    });
    document.addEventListener("click", (e) => {             // links in banners: "connect to another server"
      if (e.target.closest("[data-open-connect]")) { e.preventDefault(); openConnect(); }
    });
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

  // Tries an address and token without saving them: {ok, message (HTML), health, system}.
  async function probe(base, token) {
    const headers = { "ngrok-skip-browser-warning": "1" };
    if (token) headers.Authorization = "Bearer " + token;
    const timed = (url) => fetch(url, { headers: headers, signal: AbortSignal.timeout ? AbortSignal.timeout(15000) : undefined });
    try {
      const h = await timed(base + "/api/health");
      if (!h.ok) throw new Error("HTTP " + h.status);
      const health = await h.json();
      const s = await timed(base + "/api/system");
      if (s.status === 401) return { ok: false, message: "Server reached, but the API token is missing or wrong." };
      if (!s.ok) throw new Error("HTTP " + s.status);
      const system = await s.json();
      return { ok: true, health: health, system: system,
        message: `Connected to MolCurator API ${esc(health.version)}. xTB ${system.tools.xtb.found ? "available" : "not available"}, ` +
          `ORCA ${system.tools.orca.found ? "found" : "not found"}, assistant ${system.assistant && system.assistant.available ? "on" : "off"}.` };
    } catch (e) {
      const reason = e.name === "TimeoutError" ? "no answer within 15 s" : e.message;
      return { ok: false, message: `Cannot reach ${esc(base || location.origin)}: ${esc(reason)}. ` +
        "Check the address; if the app is on another site, the server must allow it (MOLCURATOR_CORS_ORIGINS)." };
    }
  }

  async function testConnection() {
    const out = $("settingsResult");
    out.innerHTML = '<div class="note">Testing…</div>';
    const r = await probe($("setApi").value.trim().replace(/\/+$/, ""), $("setToken").value.trim());
    out.innerHTML = r.ok ? `<div class="okline">✓ ${r.message}</div>` : `<div class="problem">✕ ${r.message}</div>`;
  }

  function bindSettings() {
    $("settingsBtn").addEventListener("click", () => openSettings());
    $("connPill").addEventListener("click", () => openConnect());
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

  // ------------------------------------------------------------------ views: agent / dashboard
  // The agent view is offered only when the server has Claude; otherwise the dashboard is shown and
  // the switch button is hidden. The last choice is remembered in this browser (agent by default).
  let agentAvailable = false;

  function setView(view) {
    const agent = view === "agent" && agentAvailable;
    $("agentView").hidden = !agent;
    $("dashboardView").hidden = agent;
    $("viewFab").classList.toggle("to-agent", !agent);
    document.body.classList.toggle("view-agent", agent);
    $("viewFabLabel").textContent = agent ? "Dashboard" : "Agent";
    $("viewFab").setAttribute("aria-label", agent ? "Switch to the dashboard" : "Switch to the agent");
    if (agentAvailable) config.save({ view: agent ? "agent" : "dashboard" });
    if (agent) $("agentInput").focus();
  }

  // preferAgent: open the agent view now (after the user connected), whatever was used last.
  function setAgentAvailable(available, preferAgent) {
    agentAvailable = available;
    $("viewFab").hidden = !available;
    setView(available ? (preferAgent ? "agent" : (config.view() || "agent")) : "dashboard");
  }

  // ------------------------------------------------------------------ start
  // A link like https://…/#token=XYZ (printed by the Kaggle notebook) saves the token and removes it
  // from the address bar. The part after "#" is never sent to the server or the tunnel.
  function takeTokenFromLink() {
    const match = location.hash.match(/(?:^#|&)token=([^&]+)/);
    if (!match) return;
    config.save({ token: decodeURIComponent(match[1]) });
    history.replaceState(null, "", location.pathname + location.search);
  }

  // The structure libraries (about 1 MB compressed) load in the background; the app starts without
  // waiting for them and draws molecules once they are there.
  function librariesReady() {
    if (!MOL.chem.hasOCL()) {
      banner("warn", "The structure library (OpenChemLib) did not load, so molecules cannot be drawn. Runs still work.");
    }
    MOL.form.librariesReady();
    MOL.monitor.librariesReady();
  }

  function boot() {
    takeTokenFromLink();
    initTheme();
    bindSettings();
    bindConnect();
    $("docsBtn").addEventListener("click", openDocs);
    updateLinks();
    MOL.form.init((runId) => MOL.monitor.refreshList(runId));
    MOL.monitor.init();
    MOL.assistant.init();
    $("viewFab").addEventListener("click", () => {
      const toAgent = $("agentView").hidden;
      setView(toAgent ? "agent" : "dashboard");
      // Opening the dashboard after starting a run in the agent view: show that run.
      const started = toAgent ? null : MOL.assistant.takeStartedRun();
      if (started && MOL.monitor.selected() !== started) MOL.monitor.refreshList(started);
    });
    setConnection("warn", "Not connected", "Not connected to a server yet");
    openConnect();
    if (window.__molcLibs) librariesReady(); else window.addEventListener("molc-libs-ready", librariesReady);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  MOL.app = { setView: setView };
})();
