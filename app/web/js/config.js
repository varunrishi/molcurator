/* config.js — the web app's own settings, kept in this browser (localStorage).
 * Everything attaches to one global `MOL`, so the scripts load as plain ordered <script> tags
 * without a bundler. localStorage can throw (private mode, blocked storage), so every access
 * is wrapped and the app works with the defaults when it is unavailable. */
(function () {
  "use strict";
  window.MOL = window.MOL || {};

  const PREFIX = "molc.";
  const DEFAULT_REPO_URL = "https://github.com/varunrishi/molcurator"; // from the project README

  function read(key) {
    try { return localStorage.getItem(PREFIX + key); } catch (e) { return null; }
  }
  function write(key, value) {
    try {
      if (value === null || value === "") localStorage.removeItem(PREFIX + key);
      else localStorage.setItem(PREFIX + key, value);
    } catch (e) { /* storage unavailable: the setting lasts until the page is closed */ }
  }

  // Served by the backend (http/https): talk to the same server. Opened from disk: a local default.
  function defaultApiBase() {
    return location.protocol === "http:" || location.protocol === "https:" ? "" : "http://127.0.0.1:8000";
  }

  MOL.config = {
    DEFAULT_REPO_URL: DEFAULT_REPO_URL,
    defaultApiBase: defaultApiBase,
    apiBase: () => { const v = read("apiBase"); return v === null ? defaultApiBase() : v; },
    token: () => read("token") || "",
    repoUrl: () => read("repoUrl") || "",            // "" = use the server's or the default
    pollSeconds: () => Math.max(2, parseInt(read("pollSeconds"), 10) || 5),
    theme: () => read("theme"),
    save: function (values) {                        // values: any of apiBase, token, repoUrl, pollSeconds, theme
      Object.keys(values).forEach((k) => write(k, values[k] == null ? null : String(values[k]).trim()));
    }
  };
})();
