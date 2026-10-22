/* api.js — client for the MolCurator API (reference: docs/api/).
 * Adds the API token and the ngrok browser-warning header to every request, applies a timeout,
 * and turns every failure into an Error with a readable `message` (and `problems`, a list,
 * when the server explains what is wrong with a config). */
(function () {
  "use strict";
  window.MOL = window.MOL || {};
  const config = MOL.config;

  function base() {
    const b = config.apiBase();
    return b.endsWith("/") ? b.slice(0, -1) : b;
  }

  // Server error bodies are {"detail": "text"} or {"detail": {"message", "problems"}}
  // (or FastAPI's own list of validation errors).
  function errorFrom(status, body) {
    const detail = body && body.detail;
    let message = "HTTP " + status, problems = [];
    if (typeof detail === "string") message = detail;
    else if (Array.isArray(detail)) problems = detail.map((d) => (d.loc || []).join(".") + ": " + d.msg);
    else if (detail && detail.message) { message = detail.message; problems = detail.problems || []; }
    if (status === 401) message = "The server needs a valid API token (open Settings).";
    const err = new Error(message);
    err.status = status; err.problems = problems;
    return err;
  }

  async function request(path, options) {
    options = options || {};
    const headers = { "ngrok-skip-browser-warning": "1" }; // ngrok free plan: skip its HTML warning page
    if (config.token()) headers["Authorization"] = "Bearer " + config.token();
    const init = { method: options.method || "GET", headers: headers };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    const controller = new AbortController();
    init.signal = controller.signal;
    const timer = setTimeout(() => controller.abort(), options.timeout || 30000);

    let response;
    try {
      response = await fetch(base() + path, init);
    } catch (e) {
      throw new Error(e.name === "AbortError" ? "The server did not answer in time." : "Cannot reach the server.");
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) {
      let body = null;
      try { body = await response.json(); } catch (e) { /* not JSON */ }
      throw errorFrom(response.status, body);
    }
    if (options.as === "blob") return response.blob();
    if (options.as === "text") return response.text();
    return response.json();
  }

  const enc = encodeURIComponent;
  MOL.api = {
    base: base,
    docsUrl: () => (base() || location.origin) + "/api/docs",
    health: () => request("/api/health", { timeout: 8000 }),
    system: () => request("/api/system"),
    presets: () => request("/api/presets"),
    validate: (cfg) => request("/api/config/validate", { method: "POST", body: { config: cfg } }),
    inspect: (smiles) => request("/api/chem/inspect", { method: "POST", body: { smiles: smiles, xyz: true }, timeout: 60000 }),
    runs: () => request("/api/runs"),
    start: (cfg, runId) => request("/api/runs", { method: "POST", body: { config: cfg, run_id: runId || null } }),
    run: (id, eventsSince) => request("/api/runs/" + enc(id) + (eventsSince == null ? "" : "?events_since=" + eventsSince)),
    molecules: (id) => request("/api/runs/" + enc(id) + "/molecules"),
    xyz: (id, mol) => request("/api/runs/" + enc(id) + "/molecules/" + enc(mol) + "/xyz", { as: "text" }),
    file: (id, name) => request("/api/runs/" + enc(id) + "/files/" + enc(name), { as: "blob", timeout: 120000 }),
    archive: (id) => request("/api/runs/" + enc(id) + "/archive", { as: "blob", timeout: 300000 }),
    log: (id) => request("/api/runs/" + enc(id) + "/log?lines=400", { as: "text" }),
    evaluation: (id) => request("/api/runs/" + enc(id) + "/evaluation", { timeout: 120000 }),
    stop: (id) => request("/api/runs/" + enc(id) + "/stop", { method: "POST" }),
    resume: (id) => request("/api/runs/" + enc(id) + "/resume", { method: "POST" })
  };
})();
