/* form.js — the "New run" panel: preset, target window, seed, search settings, QM, budget.
 * It builds a run config (the same shape as configs/*.yaml), asks the server to check it
 * (POST /api/config/validate) as the user edits, and starts the run (POST /api/runs). */
(function () {
  "use strict";
  const { $, esc, toast, debounce } = MOL.ui;
  const api = MOL.api, chem = MOL.chem, viewer = MOL.viewer;

  const state = {
    connected: false,
    system: null,          // GET /api/system: tools + capabilities
    presets: [],           // GET /api/presets
    base: null,            // config of the chosen preset; fields the form does not show are kept from it
    decisions: "rules",
    seed: { smiles: "", canonical: null, problems: [], checking: false },
    check: null,           // last validation result
    onStarted: null        // callback(run_id) set by app.js
  };

  // ------------------------------------------------------------------ config <-> form
  function num(id) {
    const v = $(id).value.trim();
    return v === "" ? null : Number(v);
  }

  function buildConfig() {
    const cfg = JSON.parse(JSON.stringify(state.base || {}));
    // No units: the server uses the property's own unit (molcurator.chem.backends.check_target).
    cfg.target = { name: $("targetSel").value, min: num("minIn"), max: num("maxIn") };
    cfg.seeds = [state.seed.canonical || $("smilesIn").value.trim()];
    cfg.screening = { margin: num("marginIn") };
    cfg.generation = cfg.generation || {};
    cfg.generation.defaults = Object.assign({}, cfg.generation.defaults, {
      generator: "stoned_selfies", n_candidates: num("nCand"), mutation_strength: num("mStrength") });
    cfg.predict = predictFor(cfg);
    cfg.train = Object.assign({}, cfg.train, { min_examples: num("minEx") });
    cfg.qm = { enabled: $("qmOn").checked, backend: $("qmBackend").value,
               functional: $("qmFunctional").value.trim(), basis: $("qmBasis").value.trim() };
    const minutes = num("maxMinutes");
    cfg.budget = { max_rounds: num("maxRounds"), max_qm_calls: num("maxQm"),
                   target_dataset_size: num("targetSize"), max_wall_time: minutes == null ? null : minutes * 60 };
    cfg.decisions = state.decisions;
    cfg.rng_seed = num("rngSeed");
    return cfg;
  }

  // PREDICT settings for the config being built. The preset's predict section (e.g. the xTB-to-DFT
  // gap correction in configs/homo_lumo.yaml) is kept while its target is chosen; for another
  // target, the preset shipped for that target is used, else the default PREDICT level.
  function predictFor(cfg) {
    const target = $("targetSel").value;
    let predict = state.base && state.base.target && state.base.target.name === target ? state.base.predict : null;
    if (!predict) {
      const preset = state.presets.find((p) => p.config.target.name === target);
      predict = preset ? preset.config.predict : { correction: null };
    }
    const method = $("predictMethod").value.trim();
    const out = Object.assign({}, predict, { n_xtb: num("nXtb"), method: method || null });
    if (method !== ((predict && predict.method) || "")) out.basis = null;   // a basis belongs to its method
    return out;
  }

  function targetInfo(name) {
    const caps = state.system && state.system.capabilities;
    return caps ? caps.targets.find((t) => t.name === (name || $("targetSel").value)) || null : null;
  }

  // Label for PREDICT values, e.g. "GFN2-xTB (corrected)" or "B97-3c", from the config being built.
  function predictLabel(cfg) {
    const info = targetInfo(cfg && cfg.target.name);
    const p = (cfg && cfg.predict) || {};
    const method = p.method || (info ? info.predict_method : "PREDICT");
    return method + (p.correction ? " (corrected to DFT-like)" : "");
  }

  // Slider ranges for common targets (in their units); others get number fields only.
  const SLIDER = { homo_lumo_gap: [0, 10], s1_t1_gap: [-1, 2], s0_t1_gap: [0, 6], s1_energy: [0, 8], t1_energy: [0, 8],
    ionization_potential: [4, 14], electron_affinity: [-4, 4], dipole_moment: [0, 15] };

  function updateTargetUnits() {
    const info = targetInfo();
    $("unitLabel").textContent = info ? (info.units || "no unit") : "";
    const range = SLIDER[$("targetSel").value];
    $("rangeWidget").hidden = !range;
    if (range) {
      ["rMin", "rMax"].forEach((id) => { $(id).min = range[0]; $(id).max = range[1]; $(id).step = (range[1] - range[0]) / 200; });
    }
    $("predictMethod").placeholder = info ? "default: " + info.predict_method : "default";
  }

  function applyConfig(cfg, qmDefault) {
    state.base = JSON.parse(JSON.stringify(cfg));
    const set = (id, v) => { $(id).value = v == null ? "" : v; };
    if ([...$("targetSel").options].some((o) => o.value === cfg.target.name)) $("targetSel").value = cfg.target.name;
    $("predictMethod").value = (cfg.predict && cfg.predict.method) || "";
    updateTargetUnits();
    set("minIn", cfg.target.min); set("maxIn", cfg.target.max);
    set("marginIn", cfg.screening.margin);
    const gen = cfg.generation;
    set("nCand", gen.defaults.n_candidates); $("nCand").max = gen.max_candidates;
    set("mStrength", gen.defaults.mutation_strength); $("mStrength").max = gen.max_mutation_strength;
    set("nXtb", cfg.predict.n_xtb); set("minEx", cfg.train.min_examples); set("rngSeed", cfg.rng_seed);
    // QM validation is on by default (when the server has ORCA); a loaded config keeps its own choice.
    $("qmOn").checked = qmDefault ? orcaAvailable() || !state.connected : !!cfg.qm.enabled;
    set("qmFunctional", cfg.qm.functional); set("qmBasis", cfg.qm.basis);
    if ([...$("qmBackend").options].some((o) => o.value === cfg.qm.backend)) $("qmBackend").value = cfg.qm.backend;
    set("maxRounds", cfg.budget.max_rounds); set("maxQm", cfg.budget.max_qm_calls);
    set("targetSize", cfg.budget.target_dataset_size);
    set("maxMinutes", cfg.budget.max_wall_time == null ? "" : Math.round(cfg.budget.max_wall_time / 60));
    setDecisions(cfg.decisions === "llm" && llmAvailable() ? "llm" : "rules");
    $("smilesIn").value = (cfg.seeds || [])[0] || "";
    syncRangeFromInputs();
    updateQmFields();
    onSeedInput();
  }

  // ------------------------------------------------------------------ server state
  function llmAvailable() {
    return !!(state.system && state.system.tools.anthropic_key.set);
  }
  function orcaAvailable() {
    return !!(state.system && state.system.tools.orca.found);
  }

  function setConnected(connected, system, presets) {
    state.connected = connected;
    state.system = system || null;
    if (connected) {
      fillOptions(system.capabilities);
      state.presets = presets || [];
      $("presetSel").innerHTML = state.presets.map((p) =>
        `<option value="${esc(p.name)}">${esc(p.name)}${p.supported ? "" : " (not supported yet)"}</option>`).join("");
      state.presets.forEach((p, i) => { $("presetSel").options[i].disabled = !p.supported; });
      const first = state.presets.find((p) => p.supported);
      if (first && !state.base) { $("presetSel").value = first.name; applyConfig(first.config, true); }
    }
    renderReadiness();
    updateQmFields();
    validateSoon();
  }

  function fillOptions(caps) {
    $("targetSel").innerHTML = caps.targets.map((t) =>
      `<option value="${esc(t.name)}" ${t.supported ? "" : "disabled"} title="${esc(t.reason || "")}">` +
      `${esc(t.label)}${t.supported ? "" : " — not supported yet"}</option>`).join("");
    $("qmBackend").innerHTML = caps.qm_backends.map((b) =>
      `<option value="${esc(b.name)}" ${b.supported ? "" : "disabled"}>${esc(b.label)}${b.supported ? "" : " (not built)"}</option>`).join("");
    const llm = document.querySelector('[data-decisions="llm"]');
    llm.disabled = !llmAvailable();
    llm.title = llmAvailable() ? "Claude Haiku 4.5 decides; rules take over if it fails" : "Needs ANTHROPIC_API_KEY on the server";
  }

  function renderReadiness() {
    const box = $("readiness");
    if (!state.connected) {
      box.innerHTML = '<span class="chip bad">Not connected to a server</span>';
      return;
    }
    const t = state.system.tools;
    const chip = (ok, label, title) => `<span class="chip ${ok ? "good" : "bad"}" title="${esc(title)}">${ok ? "✓" : "✕"} ${label}</span>`;
    box.innerHTML =
      chip(t.xtb.found, "xTB" + (t.xtb.via === "orca" ? " (via ORCA)" : ""), t.xtb.note) +
      chip(t.orca.found, "ORCA", t.orca.path || "ORCA not found: QM validation and ORCA-only targets unavailable") +
      chip(t.anthropic_key.set, "LLM key", t.anthropic_key.set ? "ANTHROPIC_API_KEY is set" : "No ANTHROPIC_API_KEY: rules only") +
      '<span class="note" style="margin-left:4px">Found ≠ tested: a program can be present but still fail to run.</span>';
  }

  // ------------------------------------------------------------------ target window
  function syncRangeFromInputs() {
    const lo = num("minIn"), hi = num("maxIn");
    $("rMin").value = lo == null ? $("rMin").min : lo;
    $("rMax").value = hi == null ? $("rMax").max : hi;
    drawRangeFill();
  }
  function syncInputsFromRange() {
    let lo = Number($("rMin").value), hi = Number($("rMax").value);
    if (lo > hi) [lo, hi] = [hi, lo];
    $("minIn").value = lo.toFixed(2); $("maxIn").value = hi.toFixed(2);
    drawRangeFill();
    validateSoon();
  }
  function drawRangeFill() {
    const a = Number($("rMin").min), b = Number($("rMin").max), span = (b - a) || 1;
    const pos = (v) => (Math.max(a, Math.min(b, Number(v))) - a) / span * 100;
    const lo = pos($("rMin").value), hi = pos($("rMax").value);
    $("rangeFill").style.left = Math.min(lo, hi) + "%";
    $("rangeFill").style.width = Math.abs(hi - lo) + "%";
    const level = state.connected ? predictLabel(buildConfig()) : "PREDICT";
    $("levelNote").textContent = $("qmOn").checked
      ? `A molecule is curated only when its QM value is inside this window. PREDICT (${level}) only screens.`
      : `QM is off: molecules are curated on their PREDICT value (${level}) or ML estimate inside this window.`;
  }

  // ------------------------------------------------------------------ seed
  let editor = null, syncingEditor = false;

  const onSeedInput = debounce(checkSeed, 350);

  async function checkSeed() {
    const text = $("smilesIn").value.trim();
    state.seed = { smiles: text, canonical: null, problems: [], checking: true };
    const box = $("seedCheck");
    if (!text) {
      box.innerHTML = '<span class="err">Enter a seed molecule.</span>';
      $("seedDepict").innerHTML = ""; viewer.clear("viewer3d", "3D preview appears here");
      state.seed.checking = false; validateSoon(); return;
    }
    const quick = chem.hasOCL() ? chem.parse(text) : { ok: true };   // libraries still loading: let the server check
    $("seedDepict").innerHTML = quick.ok ? chem.depictSVG(text, 220, 130) : "";
    if (editor && !syncingEditor && quick.ok && $("paneSmiles").hidden === false) {
      try { syncingEditor = true; editor.setSmiles(text); } catch (e) { /* ignore */ } finally { syncingEditor = false; }
    }
    if (!state.connected) {
      box.innerHTML = quick.ok ? '<span class="note">Connect to a server to check this seed with RDKit.</span>'
        : `<span class="err">✕ ${esc(quick.error)}</span>`;
      state.seed.checking = false; validateSoon(); return;
    }
    box.innerHTML = '<span class="note">Checking with RDKit…</span>';
    try {
      const r = await api.inspect(text);
      if ($("smilesIn").value.trim() !== text) return; // the user typed on; a newer check is coming
      state.seed = { smiles: text, canonical: r.valid ? r.canonical : null, problems: r.problems, checking: false };
      if (!r.valid) {
        box.innerHTML = `<span class="err">✕ ${esc(r.problems.join(" "))}</span>`;
        viewer.clear("viewer3d", "No structure");
      } else {
        box.innerHTML = `<span class="ok">✓ ${esc(r.formula)}</span> <span class="note">${r.heavy_atoms} heavy atoms · canonical</span> <code class="mono">${esc(r.canonical)}</code>` +
          r.problems.map((p) => `<div class="warn-line">⚠ ${esc(p)}</div>`).join("");
        viewer.render("viewer3d", r.xyz);
      }
    } catch (e) {
      state.seed.checking = false;
      box.innerHTML = `<span class="err">Could not check the seed: ${esc(e.message)}</span>`;
    }
    validateSoon();
  }

  // Created the first time the Draw tab opens: the editor needs a visible element to size itself.
  function initEditor() {
    if (editor) return;
    try {
      editor = chem.createEditor("editor", function () {
        if (syncingEditor) return;
        try { $("smilesIn").value = editor.getSmiles(); onSeedInput(); } catch (e) { /* half-drawn structure */ }
      });
    } catch (e) {
      editor = null;
      console.warn("structure editor:", e);
    }
    if (!editor) $("editorFallback").style.display = "flex";
  }

  // The vendored editor keeps the size it had when created, so rebuild it when the window resizes.
  const rebuildEditor = debounce(function () {
    if (!editor || $("paneDraw").hidden) return;
    const smiles = editor.getSmiles();
    const el = $("editor");
    el.innerHTML = "";
    editor = null;
    initEditor();
    if (editor && smiles) {
      try { syncingEditor = true; editor.setSmiles(smiles); } catch (e) { /* ignore */ } finally { syncingEditor = false; }
    }
  }, 300);

  function selectSeedTab(which) {
    const draw = which === "draw";
    $("tabDraw").setAttribute("aria-selected", draw);
    $("tabSmiles").setAttribute("aria-selected", !draw);
    $("paneDraw").hidden = !draw; $("paneSmiles").hidden = draw;
    if (draw) initEditor();
    if (draw && editor && chem.parse($("smilesIn").value).ok) {
      try { syncingEditor = true; editor.setSmiles($("smilesIn").value); } catch (e) { /* ignore */ } finally { syncingEditor = false; }
    }
  }

  // ------------------------------------------------------------------ QM and decisions
  function updateQmFields() {
    const available = orcaAvailable();
    $("qmOn").disabled = state.connected && !available && !$("qmOn").checked;
    const on = $("qmOn").checked;
    $("qmFields").classList.toggle("disabled", !on);
    ["qmBackend", "qmFunctional", "qmBasis", "maxQm"].forEach((id) => { $(id).disabled = !on; });
    $("qmNote").textContent = !state.connected ? ""
      : !available ? "ORCA was not found on the server, so QM validation is unavailable. Runs curate on PREDICT/ML values."
      : on ? "QM runs one DFT calculation per selected molecule, on the geometry PREDICT used. It is the slow step."
      : "Off: no QM calculations. Turn on to confirm hits at the DFT level.";
    drawRangeFill();
  }

  function setDecisions(value) {
    state.decisions = value;
    document.querySelectorAll("[data-decisions]").forEach((b) =>
      b.setAttribute("aria-checked", b.getAttribute("data-decisions") === value));
  }

  // ------------------------------------------------------------------ checks and start
  const validateSoon = debounce(validateNow, 450);

  async function validateNow() {
    const box = $("checks");
    if (!state.connected) {
      box.innerHTML = '<div class="problem">Not connected to a server. Click the connection status at the top to connect.</div>';
      $("startBtn").disabled = true; return;
    }
    if (!state.base) return;
    try {
      const r = await api.validate(buildConfig());
      state.check = r;
      const seedNotes = state.seed.problems.length && state.seed.canonical
        ? ["Seed: " + state.seed.problems.join(" ") + " Its children will likely fail in PREDICT."] : [];
      const preset = state.presets.find((p) => p.name === $("presetSel").value);
      const presetNotes = preset && preset.config.seeds[0] === buildConfig().seeds[0] ? preset.notes : [];
      box.innerHTML =
        r.problems.map((p) => `<div class="problem">✕ ${esc(p)}</div>`).join("") +
        seedNotes.concat(presetNotes, r.warnings).map((w) => `<div class="warning">⚠ ${esc(w)}</div>`).join("");
      $("startBtn").disabled = !r.valid || !state.seed.canonical;
    } catch (e) {
      box.innerHTML = `<div class="problem">✕ ${esc(e.message)}</div>`;
      $("startBtn").disabled = true;
    }
  }

  async function start() {
    const btn = $("startBtn");
    btn.disabled = true;
    try {
      const r = await api.start(buildConfig(), $("runName").value.trim() || null);
      toast("Run " + r.run_id + " started");
      $("runName").value = "";
      if (state.onStarted) state.onStarted(r.run_id);
    } catch (e) {
      $("checks").innerHTML = `<div class="problem">✕ ${esc(e.message)}</div>` +
        (e.problems || []).map((p) => `<div class="problem">✕ ${esc(p)}</div>`).join("");
    } finally {
      validateSoon();
    }
  }

  // ------------------------------------------------------------------ wiring
  function bind() {
    $("presetSel").addEventListener("change", () => {
      const p = state.presets.find((x) => x.name === $("presetSel").value);
      if (p) applyConfig(p.config, true);
    });
    $("targetSel").addEventListener("change", () => { updateTargetUnits(); syncRangeFromInputs(); });
    $("predictMethod").addEventListener("input", () => { drawRangeFill(); validateSoon(); });
    ["rMin", "rMax"].forEach((id) => $(id).addEventListener("input", syncInputsFromRange));
    ["minIn", "maxIn"].forEach((id) => $(id).addEventListener("input", () => { syncRangeFromInputs(); validateSoon(); }));
    ["targetSel", "marginIn", "nCand", "mStrength", "nXtb", "minEx", "rngSeed", "qmBackend", "qmFunctional",
     "qmBasis", "maxRounds", "maxQm", "targetSize", "maxMinutes"].forEach((id) => $(id).addEventListener("input", validateSoon));
    $("qmOn").addEventListener("change", () => { updateQmFields(); validateSoon(); });
    document.querySelectorAll("[data-decisions]").forEach((b) =>
      b.addEventListener("click", () => { if (!b.disabled) { setDecisions(b.getAttribute("data-decisions")); validateSoon(); } }));
    $("smilesIn").addEventListener("input", onSeedInput);
    document.querySelectorAll("[data-ex]").forEach((b) => b.addEventListener("click", () => {
      $("smilesIn").value = b.getAttribute("data-ex"); selectSeedTab("smiles"); checkSeed();
    }));
    $("tabDraw").addEventListener("click", () => selectSeedTab("draw"));
    $("tabSmiles").addEventListener("click", () => selectSeedTab("smiles"));
    $("startBtn").addEventListener("click", start);
    window.addEventListener("resize", rebuildEditor);
  }

  MOL.form = {
    init: function (onStarted) { state.onStarted = onStarted; bind(); renderReadiness(); validateNow(); },
    setConnected: setConnected,
    recheckSeed: checkSeed,
    load: function (config) { applyConfig(config, false); validateSoon(); },   // e.g. a proposal from the agent view
    librariesReady: function () {           // redraw what needed OpenChemLib / 3Dmol
      $("editorFallback").style.display = "";
      if (!$("paneDraw").hidden) initEditor();
      checkSeed();
    },
    useSeed: function (smiles) { $("smilesIn").value = smiles; selectSeedTab("smiles"); checkSeed();
      document.getElementById("formPanel").scrollIntoView({ behavior: "smooth" }); }
  };
})();
