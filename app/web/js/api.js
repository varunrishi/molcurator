/* api.js — typed client for the MolCurator HTTP API.
 * Base URL comes from MOL.config (user-configurable). Every call has a timeout and rejects
 * with an Error carrying a readable message, so the UI can show a "backend unreachable" state. */
(function () {
  "use strict";
  window.MOL = window.MOL || {};

  function base() {
    var b = MOL.config.getApiBase();
    return b && b.charAt(b.length - 1) === "/" ? b.slice(0, -1) : b;
  }

  function request(path, options) {
    options = options || {};
    var init = { method: options.method || "GET", headers: {} };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    var controller = ("AbortController" in window) ? new AbortController() : null;
    if (controller) init.signal = controller.signal;
    var timer = controller ? setTimeout(function () { controller.abort(); }, options.timeout || 30000) : null;

    return fetch(base() + path, init).then(
      function (response) {
        if (timer) clearTimeout(timer);
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      },
      function (error) {
        if (timer) clearTimeout(timer);
        throw new Error(error && error.name === "AbortError" ? "request timed out" : "network error");
      }
    );
  }

  MOL.api = {
    base: base,
    health: function () { return request("/api/health", { method: "GET", timeout: 8000 }); },
    predict: function (smiles, predictor) {
      return request("/api/predict", { method: "POST", body: { smiles: smiles, predictor: predictor || null } });
    },
    embed: function (smiles) {
      return request("/api/embed", { method: "POST", body: { smiles: smiles } });
    },
    generate: function (payload) {
      return request("/api/generate", { method: "POST", body: payload, timeout: 120000 });
    }
  };
})();
