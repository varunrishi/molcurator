/* config.js — namespace, persisted settings (API base URL, theme).
 * Everything attaches to a single global `MOL` so the modules load as ordered <script> tags
 * without a bundler. All localStorage access is wrapped (it can throw in private mode). */
(function () {
  "use strict";
  window.MOL = window.MOL || {};

  var KEY_API = "molc.apiBase";
  var KEY_THEME = "molc.theme";

  function lsGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }
  function lsSet(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* ignore */ }
  }

  function defaultApiBase() {
    // Served over http(s): same origin (""). Opened from disk: a sensible local default.
    if (location.protocol === "http:" || location.protocol === "https:") return "";
    return "http://localhost:8000";
  }

  MOL.config = {
    getApiBase: function () {
      var v = lsGet(KEY_API);
      return v === null ? defaultApiBase() : v;
    },
    setApiBase: function (value) { lsSet(KEY_API, value.trim()); },
    defaultApiBase: defaultApiBase,
    getTheme: function () { return lsGet(KEY_THEME); },
    setTheme: function (value) { lsSet(KEY_THEME, value); }
  };
})();
