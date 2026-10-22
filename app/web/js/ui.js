/* ui.js — small shared helpers: DOM lookup, escaping, number/time formatting, toasts,
 * clipboard and file saving. Used by form.js, monitor.js and app.js. */
(function () {
  "use strict";
  window.MOL = window.MOL || {};

  const $ = (id) => document.getElementById(id);

  // Escape text before putting it into innerHTML (all server strings go through this).
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function fmt(x, digits) {
    return x == null || isNaN(x) ? "—" : Number(x).toFixed(digits == null ? 2 : digits);
  }

  function duration(seconds) {
    if (seconds == null || isNaN(seconds)) return "—";
    const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    if (h) return h + " h " + m + " min";
    if (m) return m + " min " + (s % 60) + " s";
    return s + " s";
  }

  function clock(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return isNaN(d) ? "—" : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function toast(message) {
    const t = $("toast");
    t.textContent = message;
    t.classList.add("show");
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove("show"), 2200);
  }

  function copy(text, message) {
    const done = () => toast(message || "Copied");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
  }
  function fallbackCopy(text, done) {
    const ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) { toast("Copy blocked by the browser"); }
    document.body.removeChild(ta);
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 500);
  }

  function debounce(fn, ms) {
    let timer;
    return function () { clearTimeout(timer); timer = setTimeout(fn, ms); };
  }

  MOL.ui = { $, esc, fmt, duration, clock, toast, copy, saveBlob, debounce };
})();
