/* app.js — MolCurator UI controller.
 * Wires the structure builder, target window, run settings and candidate explorer to the
 * backend API (MOL.api) with a configurable base URL, and falls back to an offline demo when
 * the backend is unreachable. Depends on config.js, api.js, chem.js, viewer.js (loaded first). */
(function () {
  "use strict";
  var chem = MOL.chem, api = MOL.api, viewer = MOL.viewer, config = MOL.config;

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function fmt(x, d) { return (x == null || isNaN(x)) ? "—" : Number(x).toFixed(d == null ? 2 : d); }
  function toast(msg) {
    var t = $("toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(t._t); t._t = setTimeout(function () { t.classList.remove("show"); }, 1700);
  }

  var state = {
    seedSmiles: "", seedValid: false, seedXyz: null,
    target: { min: 3.0, max: 5.0 },
    candidates: [], byId: {}, filter: "all", sort: "dist",
    connected: false, method: null, seedGap: null
  };

  /* ---------------- backend connection ---------------- */
  function connect() {
    setStatus("checking");
    return api.health().then(function (h) {
      var active = h.predictor && h.predictor.active;
      if (active && active !== "none") {
        state.connected = true;
        state.method = h.predictor.engines[active] ? h.predictor.engines[active].method : active;
        setStatus("live", h);
        configurePredictorSelect(h);
        hideBanner();
        return true;
      }
      // backend reachable but no predictor installed
      state.connected = false;
      configurePredictorSelect(h);
      setStatus("nopred", h);
      showBanner("warn", "Backend reached at <code>" + esc(api.base() || location.origin) +
        "</code>, but <b>no gap predictor is installed</b> (DelFTa or tblite). Install one for real values — " +
        "see <code>docs/API.md</code>. Using the demo estimator meanwhile.");
      return false;
    }).catch(function (err) {
      state.connected = false;
      configurePredictorSelect(null);
      setStatus("down");
      showBanner("error", "Cannot reach the backend at <code>" + esc(api.base() || "(same origin)") +
        "</code> (" + esc(err.message) + "). Start the server, or set the correct URL above. " +
        "Running in <b>demo mode</b> — values are a labelled estimator, not a real prediction.");
      return false;
    });
  }

  function setStatus(kind, h) {
    var dot = $("mode"); dot.classList.remove("live", "warn", "down");
    if (kind === "live") {
      dot.classList.add("live");
      var label = h.predictor.active === "tblite" ? "GFN2-xTB (tblite)" : h.predictor.active === "delfta" ? "DelFTa" : h.predictor.active;
      dot.title = "Connected · " + label + "\n" + (state.method || "") + "\nGenerator: " + (h.generator || "—");
    } else if (kind === "nopred") {
      dot.classList.add("warn"); dot.title = "Backend up, but no gap predictor installed — demo mode";
    } else if (kind === "down") {
      dot.classList.add("down"); dot.title = "Backend unreachable — demo mode";
    } else {
      dot.title = "Checking backend…";
    }
  }

  function showBanner(kind, html) {
    var b = $("banner"); b.className = "banner " + kind; $("bannerText").innerHTML = html; b.hidden = false;
  }
  function hideBanner() { $("banner").hidden = true; }

  function configurePredictorSelect(h) {
    var sel = $("predSel"); if (!sel) return;
    var avail = (h && h.predictor && h.predictor.available) || {};
    var connected = !!(h && h.predictor && h.predictor.active && h.predictor.active !== "none");
    for (var i = 0; i < sel.options.length; i++) {
      var o = sel.options[i];
      if (o.value === "delfta") { o.disabled = !avail.delfta; o.textContent = "DelFTa — ML, ≈ ωB97X-D/def2-SVP" + (avail.delfta ? "" : " (not installed)"); }
      else if (o.value === "tblite") { o.disabled = !avail.tblite; o.textContent = "GFN2-xTB (tblite) — semi-empirical" + (avail.tblite ? "" : " (not installed)"); }
    }
    sel.disabled = !connected;
    if (connected && (h.predictor.active === "delfta" || h.predictor.active === "tblite")) sel.value = h.predictor.active;
    sel.title = connected ? "Engine used to compute the HOMO–LUMO gap for the next run"
      : "Connect a backend to choose a prediction model";
  }

  /* ---------------- seed ---------------- */
  var editor = null, syncing = false;

  function setSeed(smiles, source) {
    var res = chem.canonical(smiles);
    state.seedValid = res.ok;
    state.seedSmiles = res.ok ? res.smiles : "";
    $("seedSmiles").textContent = res.ok ? res.smiles : "—";
    var v = $("smilesValid");
    if (res.ok) {
      v.innerHTML = '<span class="ok">✓ valid</span> <span class="note">' + res.atoms + ' atoms parsed</span>';
      state.seedGap = state.connected ? null : chem.toyGap(res.smiles).gap;
    } else {
      v.innerHTML = '<span class="err">✗ ' + esc(res.error || "invalid") + '</span>';
      state.seedGap = null;
    }
    if (res.ok && chem.hasEditor() && editor && source !== "editor") {
      try { syncing = true; editor.setMolecule(OCL.Molecule.fromSmiles(res.smiles)); } catch (e) {} finally { syncing = false; }
    }
    $("runBtn").disabled = !res.ok;
    renderSeed3D();
    renderDistribution();
  }

  function renderSeed3D() {
    if (!state.seedValid) {
      $("viewer3d").innerHTML = '<div class="v3d-empty">Enter a valid structure to preview its 3D geometry.</div>';
      return;
    }
    function go(xyz) { state.seedXyz = xyz; state._seedViewer = viewer.render("viewer3d", xyz); }
    if (state.connected) {
      api.embed(state.seedSmiles).then(function (r) { go(r && r.xyz ? r.xyz : chem.toXYZ(state.seedSmiles)); })
        .catch(function () { go(chem.toXYZ(state.seedSmiles)); });
    } else {
      go(chem.toXYZ(state.seedSmiles));
    }
  }

  function initEditor() {
    if (!chem.hasEditor()) {
      $("editorFallback").style.display = "flex";
      selectTab("smiles"); $("tabDraw").disabled = true; $("tabDraw").style.opacity = 0.5;
      return;
    }
    try {
      editor = new OCL.CanvasEditor($("editor"));
      editor.setOnChangeListener(function () {
        if (syncing) return;
        try {
          var m = editor.getMolecule();
          var smi = (m && m.getAllAtoms() > 0) ? m.toSmiles() : "";
          $("smilesIn").value = smi;
          setSeed(smi, "editor");
        } catch (e) {}
      });
      editor.setMolecule(OCL.Molecule.fromSmiles($("smilesIn").value));
    } catch (e) { $("editorFallback").style.display = "flex"; }
  }

  function selectTab(which) {
    var draw = which === "draw";
    $("tabDraw").setAttribute("aria-selected", draw);
    $("tabSmiles").setAttribute("aria-selected", !draw);
    $("paneDraw").hidden = !draw; $("paneSmiles").hidden = draw;
    if (draw && editor) { try { editor.setMolecule(OCL.Molecule.fromSmiles(state.seedSmiles || $("smilesIn").value)); } catch (e) {} }
  }

  /* ---------------- target range ---------------- */
  function syncRange(from) {
    var lo, hi;
    if (from === "num") { lo = parseFloat($("minIn").value); hi = parseFloat($("maxIn").value); }
    else { lo = parseFloat($("rMin").value); hi = parseFloat($("rMax").value); }
    if (isNaN(lo)) lo = 0; if (isNaN(hi)) hi = 10;
    lo = chem.clamp(lo, 0, 10); hi = chem.clamp(hi, 0, 10);
    if (lo > hi) { var t = lo; lo = hi; hi = t; }
    state.target.min = lo; state.target.max = hi;
    $("rMin").value = lo; $("rMax").value = hi; $("minIn").value = lo.toFixed(2); $("maxIn").value = hi.toFixed(2);
    var fill = $("rangeFill"); fill.style.left = (lo / 10 * 100) + "%"; fill.style.width = ((hi - lo) / 10 * 100) + "%";
    $("rangeNote").textContent = "window width " + (hi - lo).toFixed(2) + " eV";
    render();
  }

  /* ---------------- scoring ---------------- */
  function inTarget(c) { return c.status === "ok" && c.gap != null && c.gap >= state.target.min && c.gap <= state.target.max; }
  function distance(c) {
    if (c.status !== "ok" || c.gap == null) return 1e9;
    if (c.gap < state.target.min) return state.target.min - c.gap;
    if (c.gap > state.target.max) return c.gap - state.target.max;
    return 0;
  }

  /* ---------------- run ---------------- */
  function run() {
    if (!state.seedValid) { toast("enter a valid seed first"); return; }
    $("runBtn").disabled = true; $("runLabel").textContent = "Running…";
    $("progWrap").hidden = false; $("runLog").hidden = false;
    if (state.connected) { runBackend(); } else { runDemo(); }
  }

  function runBackend() {
    $("runLog").textContent = "contacting backend…"; $("progBar").style.width = "35%";
    var payload = {
      seed: state.seedSmiles, target: state.target,
      settings: {
        n_candidates: parseInt($("nCand").value) || 48,
        rounds: parseInt($("nRounds").value) || 3,
        mutation_strength: parseInt($("mStrength").value) || 2,
        generator: $("genSel").value,
        predictor: $("predSel").value || "auto"
      }
    };
    api.generate(payload).then(function (j) {
      ingest(j.candidates || []);
      $("progBar").style.width = "100%";
      $("runLog").textContent = "backend returned " + state.candidates.length + " candidates" +
        (j.method ? " · " + j.method : "") + (j.note ? "\n" + j.note : "");
      finishRun();
    }).catch(function (e) {
      $("runLog").textContent = "backend error: " + e.message + " — falling back to demo";
      state.connected = false; setStatus("down");
      runDemo();
    });
  }

  function runDemo() {
    var nCand = chem.clamp(parseInt($("nCand").value) || 48, 4, 500);
    var nRounds = chem.clamp(parseInt($("nRounds").value) || 3, 1, 8);
    var strength = chem.clamp(parseInt($("mStrength").value) || 2, 1, 5);
    var rng = chem.mulberry32(chem.hash32(state.seedSmiles) ^ 0x1234);
    var seen = {}; seen[state.seedSmiles] = true;
    state.candidates = []; state.byId = {};
    var idx = 0, log = [];
    function logline(s) { log.push(s); $("runLog").textContent = log.join("\n"); }

    var parents = [state.seedSmiles];
    for (var round = 1; round <= nRounds; round++) {
      logline("round " + round + ": " + parents.length + " parent(s)");
      var produced = 0, tries = 0;
      while (produced < nCand && tries < nCand * 8) {
        tries++;
        var child = chem.demoMutate(parents[Math.floor(rng() * parents.length)], strength, rng);
        if (!child || seen[child]) continue;
        seen[child] = true;
        var est = chem.toyGap(child);
        var c = {
          id: "r" + round + "-c" + String(idx++).padStart(3, "0"), smiles: child,
          parent_smiles: parents[0], round: round, generator: "demo graph-edit",
          status: "ok", gap: est.gap, uncertainty: est.uncertainty, method: est.method, xyz: null
        };
        state.candidates.push(c); state.byId[c.id] = c; produced++;
      }
      var ranked = state.candidates.slice().sort(function (a, b) { return distance(a) - distance(b); });
      parents = ranked.slice(0, Math.max(2, Math.round(nCand * 0.1))).map(function (c) { return c.smiles; });
      if (parents.indexOf(state.seedSmiles) < 0) parents.push(state.seedSmiles);
      $("progBar").style.width = Math.round(round / nRounds * 100) + "%";
    }
    logline("done · " + state.candidates.length + " candidates (demo estimator)");
    finishRun();
  }

  function ingest(list) {
    state.candidates = []; state.byId = {};
    list.forEach(function (c) { state.candidates.push(c); state.byId[c.id] = c; });
  }

  function finishRun() {
    setTimeout(function () { $("progWrap").hidden = true; }, 600);
    $("runBtn").disabled = false; $("runLabel").textContent = "Generate & screen";
    render();
  }

  /* ---------------- rendering ---------------- */
  function render() { renderDistribution(); renderCards(); renderCount(); }

  function renderCount() {
    var ok = state.candidates.filter(function (c) { return c.status === "ok"; });
    var hits = ok.filter(inTarget).length;
    $("exCount").textContent = state.candidates.length
      ? (state.candidates.length + " candidates · " + hits + " in target") : "no candidates yet";
  }

  function renderDistribution() {
    var d = $("dist");
    d.querySelectorAll(".pt,.window,.seedmark").forEach(function (n) { n.remove(); });
    var W = function (v) { return chem.clamp(v / 10, 0, 1) * 100; };
    var win = document.createElement("div"); win.className = "window";
    win.style.left = W(state.target.min) + "%"; win.style.width = (W(state.target.max) - W(state.target.min)) + "%";
    d.appendChild(win);
    if (state.seedGap != null) {
      var sm = document.createElement("div"); sm.className = "seedmark"; sm.style.left = W(state.seedGap) + "%"; d.appendChild(sm);
    }
    state.candidates.filter(function (c) { return c.status === "ok" && c.gap != null; }).forEach(function (c) {
      var p = document.createElement("div"); p.className = "pt";
      p.style.left = W(c.gap) + "%"; p.style.top = (18 + (chem.hash32(c.id) % 64) / 64 * 34) + "%";
      p.style.background = inTarget(c) ? "var(--target)" : "var(--accent)";
      p.title = c.id + ": " + fmt(c.gap) + " eV"; d.appendChild(p);
    });
  }

  function filtered() {
    var arr = state.candidates.slice();
    if (state.filter === "hits") arr = arr.filter(inTarget);
    else if (state.filter === "fail") arr = arr.filter(function (c) { return c.status !== "ok"; });
    var s = state.sort;
    arr.sort(function (a, b) {
      if (s === "asc") return (a.gap == null ? 1e9 : a.gap) - (b.gap == null ? 1e9 : b.gap);
      if (s === "desc") return (b.gap == null ? -1e9 : b.gap) - (a.gap == null ? -1e9 : a.gap);
      if (s === "round") return a.round - b.round || distance(a) - distance(b);
      return distance(a) - distance(b);
    });
    return arr;
  }

  function renderCards() {
    var arr = filtered(), wrap = $("cards"), empty = $("emptyState");
    if (!state.candidates.length) { empty.hidden = false; wrap.hidden = true; return; }
    empty.hidden = true; wrap.hidden = false; wrap.innerHTML = "";
    if (!arr.length) { wrap.innerHTML = '<div class="empty" style="grid-column:1/-1">No candidates match this filter.</div>'; return; }
    var frag = document.createDocumentFragment();
    arr.forEach(function (c) {
      var card = document.createElement("button");
      card.className = "card" + (inTarget(c) ? " hit" : "");
      var badge = c.status !== "ok" ? '<span class="badge fail">fail</span>'
        : inTarget(c) ? '<span class="badge in">in</span>' : '<span class="badge out">out</span>';
      var gapHtml = c.status !== "ok" ? '<span style="color:var(--bad);font-size:13px">failed</span>'
        : '<span class="gap">' + fmt(c.gap) + '<span class="u">eV</span></span>';
      card.innerHTML = badge + '<div class="depict">' + (chem.depictSVG(c.smiles, 150, 96) || '<span class="note">no depiction</span>') +
        '</div><div class="cid">' + c.id + '</div>' + gapHtml;
      card.addEventListener("click", function () { openDetail(c.id); });
      frag.appendChild(card);
    });
    wrap.appendChild(frag);
  }

  /* ---------------- detail overlay ---------------- */
  function openDetail(id) {
    var c = state.byId[id]; if (!c) return;
    $("dTitle").textContent = c.id;
    var badge = $("dBadge");
    if (c.status !== "ok") { badge.className = "chip bad"; badge.textContent = "failed"; }
    else if (inTarget(c)) { badge.className = "chip in"; badge.textContent = "in target"; }
    else { badge.className = "chip"; badge.textContent = "out of target"; }

    var dd = distance(c);
    var rows = tr("Predicted gap", c.status === "ok" ? fmt(c.gap) + " eV" : "—")
      + tr("HOMO", c.homo != null ? fmt(c.homo) + " eV" : "—")
      + tr("LUMO", c.lumo != null ? fmt(c.lumo) + " eV" : "—")
      + tr("Uncertainty (±)", c.uncertainty != null ? fmt(c.uncertainty) + " eV" : "—")
      + tr("Distance to window", c.status === "ok" ? (dd === 0 ? "0 (inside)" : fmt(dd) + " eV") : "—")
      + tr("Method", c.method || "—") + tr("Round", String(c.round)) + tr("Generator", c.generator)
      + (c.error ? tr("Error", c.error) : "");
    $("sheetBody").innerHTML =
      '<div class="detail-depict" id="dDepict"></div>' +
      '<div id="detail3d"><div class="v3d-empty">rendering…</div></div>' +
      '<div class="row wrap"><button class="btn sm" id="dCopySmiles">Copy SMILES</button>' +
      '<button class="btn sm" id="dCopyXyz">Copy .xyz</button>' +
      '<button class="btn sm" id="dDlXyz">Download .xyz</button>' +
      '<button class="btn sm primary" id="dSeed">Use as seed</button></div>' +
      '<div class="kv"><span class="k">Canonical SMILES</span><span class="v" id="dSmiles"></span></div>' +
      '<div class="kv"><span class="k">Parent</span><span class="v">' + esc(c.parent_smiles) + '</span></div>' +
      '<table class="proptable">' + rows + '</table>' +
      (c.method && /toy|demo/.test(c.method) ? '<p class="note">Demo placeholder — not a real prediction.</p>' : '');
    $("dDepict").innerHTML = chem.depictSVG(c.smiles, 420, 170) || '<span class="note">no depiction</span>';
    $("dSmiles").textContent = c.smiles;
    $("overlay").classList.add("open");

    var xyz = c.xyz || chem.toXYZ(c.smiles);
    viewer.render("detail3d", xyz);
    $("dCopySmiles").onclick = function () { copy(c.smiles, "SMILES copied"); };
    $("dCopyXyz").onclick = function () { xyz ? copy(xyz, ".xyz copied") : toast("no geometry"); };
    $("dDlXyz").onclick = function () { xyz ? saveFile(c.id, xyz) : toast("no geometry"); };
    $("dSeed").onclick = function () { $("smilesIn").value = c.smiles; setSeed(c.smiles, "input"); selectTab("smiles"); closeDetail(); toast("seed updated"); };
  }
  function tr(k, v) { return "<tr><td>" + esc(k) + "</td><td>" + esc(v) + "</td></tr>"; }
  function closeDetail() { $("overlay").classList.remove("open"); }

  /* ---------------- clipboard / download ---------------- */
  function copy(text, msg) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast(msg || "copied"); }, function () { fallbackCopy(text, msg); });
    } else { fallbackCopy(text, msg); }
  }
  function fallbackCopy(text, msg) {
    var ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = 0;
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast(msg || "copied"); } catch (e) { toast("copy blocked"); }
    document.body.removeChild(ta);
  }
  function saveFile(baseName, text) {
    if (window.claude && window.claude.use) {       // artifact runtime: downloads are mediated
      Promise.resolve(window.claude.use("downloads")).then(function (dl) {
        if (!dl) { blobSave(baseName, text); return; }
        dl.save({ filename: baseName + ".txt", data: text }).then(
          function () { toast("saved " + baseName + ".xyz (as .txt)"); },
          function (err) { if (!(err && err.code === "declined")) copy(text, "download unavailable — copied"); }
        );
      }, function () { blobSave(baseName, text); });
      return;
    }
    blobSave(baseName, text);
  }
  function blobSave(baseName, text) {
    try {
      var url = URL.createObjectURL(new Blob([text], { type: "chemical/x-xyz" }));
      var a = document.createElement("a"); a.href = url; a.download = baseName + ".xyz";
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(url); document.body.removeChild(a); }, 200);
      toast("downloaded " + baseName + ".xyz");
    } catch (e) { copy(text, "download blocked — copied"); }
  }

  /* ---------------- theme ---------------- */
  function initTheme() {
    var saved = config.getTheme();
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    $("themeBtn").addEventListener("click", function () {
      var cur = document.documentElement.getAttribute("data-theme");
      var isDark = cur ? cur === "dark" : window.matchMedia("(prefers-color-scheme:dark)").matches;
      var next = isDark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next); config.setTheme(next);
      if (state._seedViewer) { try { state._seedViewer.render(); } catch (e) {} }
    });
  }

  /* ---------------- events / boot ---------------- */
  function bind() {
    $("tabDraw").addEventListener("click", function () { selectTab("draw"); });
    $("tabSmiles").addEventListener("click", function () { selectTab("smiles"); });
    var si = $("smilesIn"), deb;
    si.addEventListener("input", function () { clearTimeout(deb); deb = setTimeout(function () { setSeed(si.value, "input"); }, 220); });
    document.querySelectorAll("[data-ex]").forEach(function (b) {
      b.addEventListener("click", function () { si.value = b.getAttribute("data-ex"); setSeed(si.value, "input"); selectTab("smiles"); });
    });
    $("copySeed").addEventListener("click", function () { state.seedValid ? copy(state.seedSmiles, "SMILES copied") : toast("no valid seed"); });
    $("dlXyz").addEventListener("click", function () { var x = state.seedXyz || chem.toXYZ(state.seedSmiles); x ? saveFile("seed", x) : toast("no geometry"); });
    $("copyXyz").addEventListener("click", function () { var x = state.seedXyz || chem.toXYZ(state.seedSmiles); x ? copy(x, ".xyz copied") : toast("no geometry"); });
    $("spinBtn").addEventListener("click", function () {
      var v = state._seedViewer; if (!v) return; v._spin = !v._spin;
      try { v.spin(v._spin ? "y" : false); } catch (e) {} this.classList.toggle("primary", v._spin);
    });
    ["rMin", "rMax"].forEach(function (id) { $(id).addEventListener("input", function () { syncRange("slider"); }); });
    ["minIn", "maxIn"].forEach(function (id) { $(id).addEventListener("change", function () { syncRange("num"); }); });
    document.querySelectorAll(".filters button").forEach(function (b) {
      b.addEventListener("click", function () {
        document.querySelectorAll(".filters button").forEach(function (x) { x.setAttribute("aria-selected", false); });
        b.setAttribute("aria-selected", true); state.filter = b.getAttribute("data-filter"); renderCards();
      });
    });
    $("sortSel").addEventListener("change", function () { state.sort = this.value; renderCards(); });
    $("runBtn").addEventListener("click", run);
    $("closeSheet").addEventListener("click", closeDetail);
    $("overlay").addEventListener("click", function (e) { if (e.target === $("overlay")) closeDetail(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDetail(); });

    // API base URL controls
    var apiInput = $("apiInput");
    apiInput.value = config.getApiBase();
    apiInput.placeholder = config.defaultApiBase() || "(same origin)";
    function applyApi() {
      config.setApiBase(apiInput.value);
      connect().then(function () { if (state.seedValid) { setSeed(state.seedSmiles, "input"); } });
    }
    $("apiReconnect").addEventListener("click", applyApi);
    apiInput.addEventListener("keydown", function (e) { if (e.key === "Enter") applyApi(); });
  }

  function boot() {
    if (!chem.hasOCL()) {
      showBanner("error", "Chemistry engine (OpenChemLib) could not load from a local copy or any CDN. " +
        "The structure tools need it — check the network, or vendor it into <code>frontend/lib/</code>.");
    }
    initTheme(); bind(); initEditor(); syncRange("num");
    setSeed($("smilesIn").value, "input");
    connect();
  }

  // Libraries (OpenChemLib, 3Dmol) are loaded by the resilient loader in index.html, which
  // fires "molc-libs-ready". Boot after both the DOM and the libraries are ready.
  function start() { if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot(); }
  if (window.__molcLibs) start(); else window.addEventListener("molc-libs-ready", start);
})();
