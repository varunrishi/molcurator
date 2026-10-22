/* monitor.js — the "Runs" panel: pick a run, follow it live, and explore its results.
 *
 * Following a run costs one request per refresh: GET /api/runs/<id>?events_since=<n> returns
 * the status plus only the trace events that are new since the last refresh. The molecule list
 * (GET /molecules) is fetched again only after a step that changed molecules, at most every
 * few seconds, and polling pauses while the browser tab is hidden. */
(function () {
  "use strict";
  const { $, esc, fmt, duration, clock, toast, copy, saveBlob } = MOL.ui;
  const api = MOL.api, chem = MOL.chem, viewer = MOL.viewer, config = MOL.config;

  const ACTIVE = ["starting", "running", "stopping"];
  const MOLECULE_STEPS = ["generate", "predict", "ml_predict", "screen", "select_qm_batch", "validate", "curate"];
  const CARD_PAGE = 120; // cards drawn at once; "Show more" adds the next page

  const NODE_LABEL = {
    plan_round: "Plan round", generate: "Generate", predict: "Predict", train: "Train ML", ml_predict: "ML estimate",
    screen: "Screen", select_qm_batch: "Pick QM batch", validate: "QM", curate: "Curate",
    close_round: "Close round", continue_or_stop: "Continue?", write_summary: "Summary", run_start: "Start"
  };
  const SKIP_REASON = {
    below_min_examples: "not enough PREDICT values yet to train the model",
    no_candidates_left: "every candidate already has a PREDICT value",
    empty_qm_batch: "no candidates were selected for QM"
  };
  const STOP_REASON = {
    target_dataset_size: "the dataset reached its target size", max_rounds: "all rounds were used",
    max_qm_calls: "all QM calls were used", max_wall_time: "the time budget ran out",
    llm: "the LLM decided to stop", error: "a step failed"
  };
  const STATUS_TEXT = {
    starting: "Starting", running: "Running", stopping: "Stopping", finished: "Finished",
    failed: "Failed", interrupted: "Stopped", unknown: "Not tracked"
  };

  const state = {
    runId: null, overview: null, events: [], cursor: 0,
    molecules: [], moleculesAt: 0, moleculesStale: true,
    filter: "all", sort: "dist", shown: CARD_PAGE, tab: "molecules",
    timer: null, loading: false, summaryLoadedFor: null
  };

  // ------------------------------------------------------------------ run list
  async function refreshList(selectId) {
    let runs = [];
    try { runs = await api.runs(); } catch (e) { $("runSel").innerHTML = `<option value="">${esc(e.message)}</option>`; return; }
    const options = runs.map((r) => {
      const t = r.target ? `${r.target.min ?? "…"}–${r.target.max ?? "…"} ${r.target.units || ""}` : "";
      return `<option value="${esc(r.run_id)}">${esc(r.run_id)} · ${esc(STATUS_TEXT[r.status] || r.status)} · ${esc(t)} · ${r.dataset_size} curated</option>`;
    });
    if (selectId && !runs.some((r) => r.run_id === selectId)) { // just started: its folder may not exist yet
      options.unshift(`<option value="${esc(selectId)}">${esc(selectId)} · Starting</option>`);
      runs.unshift({ run_id: selectId });
    }
    $("runSel").innerHTML = '<option value="">' + (runs.length ? "Choose a run…" : "No runs yet") + "</option>" + options.join("");
    const want = selectId || state.runId;
    if (want && runs.some((r) => r.run_id === want)) $("runSel").value = want;
    if (selectId) {
      select(selectId);
      $("runPanel").scrollIntoView({ behavior: "smooth", block: "start" }); // show the new run, also on phones
    }
  }

  function select(runId) {
    clearTimeout(state.timer);
    Object.assign(state, { runId: runId || null, overview: null, events: [], cursor: 0, molecules: [],
                           moleculesStale: true, shown: CARD_PAGE, summaryLoadedFor: null });
    $("runEmpty").hidden = !!runId;
    $("runView").hidden = !runId;
    $("evalOut").innerHTML = ""; $("logText").textContent = ""; $("summaryText").textContent = "";
    if (runId) {
      if ($("runSel").value !== runId) $("runSel").value = runId;
      load();
    }
  }

  // ------------------------------------------------------------------ polling
  async function load() {
    const runId = state.runId;
    if (!runId || state.loading) return;
    state.loading = true;
    try {
      const o = await api.run(runId, state.cursor);
      if (runId !== state.runId) return; // the user switched runs meanwhile
      const wasActive = state.overview && ACTIVE.includes(state.overview.status);
      const statusChanged = state.overview && state.overview.status !== o.status;
      state.overview = o;
      if (o.events && o.events.length) {
        state.events = state.events.concat(o.events);
        if (o.events.some((e) => MOLECULE_STEPS.includes(e.node))) state.moleculesStale = true;
      }
      state.cursor = o.events_next != null ? o.events_next : state.cursor;
      render();
      const active = ACTIVE.includes(o.status);
      if (statusChanged) refreshList(); // keep the run list's status labels current
      if (wasActive && !active) { state.moleculesStale = true; toast("Run " + runId + ": " + STATUS_TEXT[o.status]); }
      await maybeLoadMolecules(!active);
      if (state.tab === "summary") loadSummary();
      if (active) schedule();
    } catch (e) {
      $("runBanner").hidden = false;
      $("runBanner").className = "banner error";
      $("runBanner").textContent = "Could not refresh this run: " + e.message;
      schedule(); // try again later
    } finally {
      state.loading = false;
    }
  }

  function schedule() {
    clearTimeout(state.timer);
    state.timer = setTimeout(function tick() {
      if (document.hidden) { state.timer = setTimeout(tick, 2000); return; } // no requests while hidden
      load();
    }, config.pollSeconds() * 1000);
  }

  async function maybeLoadMolecules(force) {
    const tooSoon = Date.now() - state.moleculesAt < 8000;
    if (!state.moleculesStale || (tooSoon && !force)) return;
    if (state.overview && state.overview.status === "starting") return;
    try {
      state.molecules = await api.molecules(state.runId);
      state.moleculesAt = Date.now();
      state.moleculesStale = false;
      renderMolecules();
    } catch (e) { /* the overview shows connection problems */ }
  }

  // ------------------------------------------------------------------ rendering: header
  function render() {
    const o = state.overview;
    if (!o) return;
    $("runId").textContent = o.run_id;
    const chip = $("runStatus");
    chip.textContent = STATUS_TEXT[o.status] || o.status;
    chip.className = "chip status-" + o.status;

    const t = o.target;
    const parts = [];
    if (t) parts.push(`${esc(t.name)} ${t.min ?? "…"}–${t.max ?? "…"} ${esc(t.units || "")}`);
    if (o.decisions) parts.push(o.decisions === "llm" ? "LLM decisions" : "rule decisions");
    if (o.predict_level) parts.push("PREDICT " + esc(o.predict_level.label));
    parts.push(o.qm_enabled ? "QM on" : "QM off");
    $("legendPredict").textContent = levelLabel("xtb") === "xTB→DFT" ? "xTB → DFT-like" : levelLabel("xtb");
    if (o.started_at) parts.push("started " + clock(o.started_at));
    parts.push("running time " + duration(o.running_seconds));
    $("runMeta").innerHTML = parts.join(" · ");

    $("stopBtn").hidden = !["running", "starting"].includes(o.status);
    $("resumeBtn").hidden = !o.resumable;
    $("dlBtn").disabled = o.status === "starting";

    const banner = $("runBanner");
    let kind = null, text = "";
    if (o.status === "failed") { kind = "error"; text = "The run failed: " + (o.error || "see the Log tab."); }
    else if (o.status === "interrupted") { kind = "warn"; text = "The run was stopped before it finished. Finished steps are saved; press Resume to continue."; }
    else if (o.status === "unknown") { kind = "warn"; text = "This run was not started from this app, so its process is not tracked. It may still be running in a terminal."; }
    else if (o.status === "finished") { kind = "ok"; text = "Finished: " + (STOP_REASON[o.stop_reason] || o.stop_reason) + "."; }
    else if (o.status === "stopping") { kind = "warn"; text = "Stopping (up to about 10 s). The step in progress is interrupted and runs again if you resume."; }
    banner.hidden = !kind;
    if (kind) { banner.className = "banner " + kind; banner.textContent = text; }

    renderSteps(); renderMeters(); renderActivity(); renderRounds();
  }

  function renderSteps() {
    const o = state.overview;
    const nodes = (o.nodes || []).filter((n) => n !== "write_summary");
    const round = o.current && o.current.round;
    $("roundLabel").textContent = round ? "Round " + round : "";
    const thisRound = {};
    state.events.filter((e) => e.round === round).forEach((e) => { thisRound[e.node] = e.status; });
    const activeNode = o.current && o.current.node;
    $("steps").innerHTML = nodes.map((n) => {
      let cls = "pending", title = "not run yet this round";
      if (thisRound[n] === "ok") { cls = "done"; title = "done"; }
      else if (thisRound[n] === "skipped") { cls = "skipped"; title = "skipped"; }
      else if (thisRound[n] === "failed") { cls = "failed"; title = "failed"; }
      if (n === activeNode && ACTIVE.includes(o.status)) { cls = "active"; title = "running now"; }
      return `<span class="step ${cls}" title="${esc(NODE_LABEL[n] || n)}: ${title}">${esc(NODE_LABEL[n] || n)}</span>`;
    }).join('<span class="arrow">›</span>');
  }

  function meter(label, used, max, text) {
    const pct = max ? Math.min(100, (used / max) * 100) : 0;
    return `<div class="meter"><div class="meter-top"><span>${esc(label)}</span><b>${text}</b></div>` +
           `<div class="meter-bar"><i style="width:${pct}%"></i></div></div>`;
  }

  function renderMeters() {
    const b = state.overview.budget || {};
    const minutes = (s) => Math.round((s || 0) / 60);
    $("meters").innerHTML =
      meter("Rounds", b.rounds_done || 0, b.max_rounds, `${b.rounds_done ?? 0} / ${b.max_rounds ?? "—"}`) +
      meter("Curated", b.dataset_size || 0, b.target_dataset_size, `${b.dataset_size ?? 0} / ${b.target_dataset_size ?? "—"}`) +
      (state.overview.qm_enabled
        ? meter("QM calls", b.qm_calls_used || 0, b.max_qm_calls, `${b.qm_calls_used ?? 0} / ${b.max_qm_calls ?? "—"}`)
        : meter("QM calls", 0, 0, "QM off")) +
      meter("Time", b.running_seconds || 0, b.max_wall_time, `${duration(b.running_seconds)} / ${minutes(b.max_wall_time)} min`);
  }

  // ------------------------------------------------------------------ rendering: activity and rounds
  function describe(e) {
    const out = e.outputs || {};
    if (e.node === "run_start") return e.resumed ? "Run resumed from its last finished step" : "Run started";
    if (e.status === "failed") return "Failed: " + (e.error || "unknown error");
    if (e.status === "skipped") return "Skipped: " + (SKIP_REASON[e.reason] || e.reason);
    if (e.node === "plan_round" && out.round_plan) {
      const p = out.round_plan;
      return `${p.n_candidates} candidates · mutation strength ${p.mutation_strength} · ${p.parents.length} parent(s)`;
    }
    if (e.node === "train" && out.model) {
      const m = out.model.metrics || {};
      let s = `trained on ${out.model.n_examples} PREDICT values`;
      if (m.test_mae != null) s += ` · test MAE ${fmt(m.test_mae)} ${esc(units())}` + (m.baseline_mae != null ? ` (guessing the mean: ${fmt(m.baseline_mae)})` : "");
      return s;
    }
    if (e.node === "close_round" && out.round_stats) {
      const s = out.round_stats;
      return `${s.generated} generated · ${s.xtb_runs} predicted · ${s.ml_predicted} ML · ${s.screened_in} screened in · ${s.qm_calls} QM · ${s.hits} curated`;
    }
    if (e.node === "continue_or_stop") return out.stop_reason ? "Stop: " + (STOP_REASON[out.stop_reason] || out.stop_reason) : "Continue to round " + out.round;
    if (e.node === "write_summary") return "Summary written" + (out.stop_reason ? " · " + (STOP_REASON[out.stop_reason] || out.stop_reason) : "");
    if (e.result_counts) {
      const s = Object.entries(e.result_counts).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ");
      return e.node === "curate" && out.dataset_size != null ? `${s} · dataset ${out.dataset_size}` : s;
    }
    if (e.node === "curate") return "nothing new in the window";
    return "";
  }

  function decisionBadge(e) {
    const d = e.llm;
    if (!d) return "";
    const by = d.source === "llm" ? "LLM" : d.fallback && d.fallback !== "rules_mode" ? "rule (LLM " + d.fallback.replace("_", " ") + ")" : "rule";
    const reason = d.decision && d.decision.reason ? `<div class="reason">${esc(d.decision.reason)}</div>` : "";
    return `<span class="who ${d.source === "llm" ? "llm" : "rule"}">${esc(by)}</span>${reason}`;
  }

  function renderActivity() {
    const items = state.events.slice().reverse().map((e) => {
      const time = e.ended_at ? new Date(e.ended_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "";
      return `<li class="act ${e.status}"><span class="t mono">${esc(time)}</span>` +
             `<span class="r">${e.round ? "r" + e.round : ""}</span>` +
             `<span class="what"><b>${esc(NODE_LABEL[e.node] || e.node)}</b> ${esc(describe(e))}${decisionBadge(e)}</span></li>`;
    });
    if (state.overview && ACTIVE.includes(state.overview.status) && state.overview.current.node) {
      items.unshift(`<li class="act running"><span class="t mono">now</span><span class="r">${state.overview.current.round ? "r" + state.overview.current.round : ""}</span>` +
                    `<span class="what"><b>${esc(NODE_LABEL[state.overview.current.node] || state.overview.current.node)}</b> running…</span></li>`);
    }
    $("activity").innerHTML = items.join("") || '<li class="note">No steps finished yet.</li>';
  }

  function renderRounds() {
    const rows = state.overview.rounds || [];
    const cols = [["round", "Round"], ["generated", "Generated"], ["duplicates", "Repeats"], ["xtb_runs", "Predicted"],
                  ["ml_predicted", "ML"], ["unscored", "Unscored"], ["failed", "Failed"], ["screened_in", "Screened in"],
                  ["selected", "To QM"], ["qm_calls", "QM calls"], ["hits", "Curated"]];
    $("roundsTable").innerHTML = rows.length
      ? "<thead><tr>" + cols.map((c) => `<th>${c[1]}</th>`).join("") + "</tr></thead><tbody>" +
        rows.map((r) => "<tr>" + cols.map((c) => `<td>${esc(r[c[0]])}</td>`).join("") + "</tr>").join("") + "</tbody>"
      : '<tbody><tr><td class="note">No round finished yet.</td></tr></tbody>';
  }

  async function loadSummary() {
    const o = state.overview;
    if (!o || !o.files || !o.files["summary.md"]) {
      $("summaryText").textContent = o && ACTIVE.includes(o.status) ? "The summary is written when the run ends." : "No summary for this run.";
      return;
    }
    if (state.summaryLoadedFor === o.run_id) return;
    try {
      $("summaryText").textContent = await (await api.file(o.run_id, "summary.md")).text();
      state.summaryLoadedFor = o.run_id;
    } catch (e) { $("summaryText").textContent = "Could not load the summary: " + e.message; }
  }

  // ------------------------------------------------------------------ rendering: molecules
  const LEVEL_LABEL = { qm: "QM", xtb: "xTB", ml: "ML" };

  // The run's units and PREDICT level (GET /api/runs/<id>: target, predict_level). PREDICT values
  // sit in the "xtb" field whatever method ran, so their badge names the method.
  function units() {
    const t = state.overview && state.overview.target;
    return t ? t.units || "" : "";
  }
  function predictLevel() {
    return (state.overview && state.overview.predict_level) || { method: "PREDICT", label: "PREDICT", xtb: true, corrected: false };
  }
  function levelLabel(level) {
    if (level !== "xtb") return LEVEL_LABEL[level];
    const p = predictLevel();
    return p.xtb ? (p.corrected ? "xTB→DFT" : "xTB") : p.method;
  }

  function distanceToWindow(m) {
    const t = state.overview.target || {};
    if (m.best_value == null) return Infinity;
    if (t.min != null && m.best_value < t.min) return t.min - m.best_value;
    if (t.max != null && m.best_value > t.max) return m.best_value - t.max;
    return 0;
  }

  function filteredMolecules() {
    let list = state.molecules.slice();
    if (state.filter === "curated") list = list.filter((m) => m.curated);
    else if (state.filter === "qm") list = list.filter((m) => m.validated);
    else if (state.filter === "failed") list = list.filter((m) => m.status === "failed");
    const val = (m) => (m.best_value == null ? null : m.best_value);
    list.sort((a, b) => {
      if (state.sort === "asc") return (val(a) ?? Infinity) - (val(b) ?? Infinity);
      if (state.sort === "desc") return (val(b) ?? -Infinity) - (val(a) ?? -Infinity);
      if (state.sort === "id") return (a.round || 0) - (b.round || 0) || a.id.localeCompare(b.id);
      return distanceToWindow(a) - distanceToWindow(b);
    });
    return list;
  }

  function renderMolecules() {
    if (!state.overview) return;
    const all = state.molecules;
    const curated = all.filter((m) => m.curated).length;
    const validated = all.filter((m) => m.validated).length;
    const failed = all.filter((m) => m.status === "failed").length;
    $("molCount").textContent = all.length
      ? `${all.length} molecules · ${curated} curated${state.overview.qm_enabled ? ` (${validated} QM-validated)` : ""} · ${failed} failed`
      : "No molecules yet";
    renderDistribution();

    const list = filteredMolecules();
    const cards = $("cards");
    if (!all.length) { cards.innerHTML = '<div class="empty">Molecules appear here after the first Generate step.</div>'; return; }
    if (!list.length) { cards.innerHTML = '<div class="empty">No molecules match this filter.</div>'; return; }
    cards.innerHTML = list.slice(0, state.shown).map(cardHtml).join("") +
      (list.length > state.shown ? `<button class="btn more" id="moreCards">Show more (${list.length - state.shown} left)</button>` : "");
    cards.querySelectorAll("[data-mol]").forEach((el) => el.addEventListener("click", () => openDetail(el.getAttribute("data-mol"))));
    const more = $("moreCards");
    if (more) more.addEventListener("click", () => { state.shown += CARD_PAGE; renderMolecules(); });
  }

  function cardHtml(m) {
    let badge;
    if (m.status === "failed") badge = '<span class="badge fail">failed</span>';
    else if (m.curated) badge = `<span class="badge in">${m.validated ? "QM hit" : "curated"}</span>`;
    else if (m.in_window) badge = '<span class="badge near">in window</span>';
    else badge = "";
    const value = m.status === "failed"
      ? '<span class="failtext">failed</span>'
      : m.best_value == null ? '<span class="note">no value</span>'
      : `<span class="gap">${fmt(m.best_value)}<span class="u">${esc(units())}</span></span><span class="lvbadge ${m.best_level}">${esc(levelLabel(m.best_level))}</span>`;
    return `<button class="card${m.curated ? " hit" : ""}" data-mol="${esc(m.id)}">${badge}` +
      `<div class="depict">${chem.depictSVG(m.smiles, 150, 96) || '<span class="note">no drawing</span>'}</div>` +
      `<div class="cid">${esc(m.id)}</div><div class="valrow">${value}</div></button>`;
  }

  function renderDistribution() {
    const box = $("dist");
    const t = state.overview.target || {};
    const vals = state.molecules.filter((m) => m.best_value != null);
    const nums = vals.map((m) => m.best_value).concat([t.min, t.max].filter((x) => x != null));
    if (!nums.length) { box.innerHTML = '<div class="axis"><span>no values yet</span></div>'; return; }
    let lo = Math.min.apply(null, nums), hi = Math.max.apply(null, nums);
    const pad = Math.max(0.25, (hi - lo) * 0.05);
    lo = lo >= 0 ? Math.max(0, lo - pad) : lo - pad; // no negative axis for values that cannot be negative
    hi += pad;
    const x = (v) => ((v - lo) / (hi - lo)) * 100;
    const winLo = t.min != null ? x(t.min) : 0, winHi = t.max != null ? x(t.max) : 100;
    let html = `<div class="window" style="left:${winLo}%;width:${winHi - winLo}%"></div>`;
    vals.forEach((m, i) => {
      const y = 15 + ((i * 37) % 60); // spread points vertically so they do not hide each other
      html += `<div class="pt ${m.best_level}${m.curated ? " cur" : ""}" style="left:${x(m.best_value)}%;top:${y}%" title="${esc(m.id)}: ${fmt(m.best_value)} ${esc(units())} (${esc(levelLabel(m.best_level))})"></div>`;
    });
    html += `<div class="axis"><span>${fmt(lo, 1)}</span><span>${esc(t.units || "")}</span><span>${fmt(hi, 1)}</span></div>`;
    box.innerHTML = html;
  }

  // ------------------------------------------------------------------ molecule detail
  function openDetail(id) {
    const m = state.molecules.find((x) => x.id === id);
    if (!m) return;
    $("dTitle").textContent = m.id;
    const badge = $("dBadge");
    badge.className = "chip" + (m.status === "failed" ? " bad" : m.curated ? " in" : "");
    badge.textContent = m.status === "failed" ? "failed" : m.curated ? (m.validated ? "QM-validated hit" : "curated") : (m.status || "").replace(/_/g, " ");
    const row = (k, v) => `<tr><td>${esc(k)}</td><td>${v}</td></tr>`;
    const val = (v) => (v == null ? "—" : fmt(v, 3) + " " + esc(units()));
    const p = predictLevel();
    const win = state.overview.target || {};
    $("sheetBody").innerHTML =
      `<div class="detail-depict">${chem.depictSVG(m.smiles, 420, 170) || '<span class="note">no drawing</span>'}</div>` +
      '<div id="detail3d"><div class="v3d-empty">loading geometry…</div></div>' +
      '<div class="row wrap"><button class="btn sm" id="dCopy">Copy SMILES</button>' +
      '<button class="btn sm" id="dXyz">Download .xyz</button>' +
      '<button class="btn sm primary" id="dSeed">Use as seed</button></div>' +
      `<div class="kv"><span class="k">SMILES</span><span class="v">${esc(m.smiles || "—")}</span></div>` +
      '<table class="proptable">' +
      row("Best estimate", m.best_value == null ? "—" : `${val(m.best_value)} <span class="lvbadge ${m.best_level}">${esc(levelLabel(m.best_level))}</span>`) +
      row("Target window", `${win.min ?? "…"} – ${win.max ?? "…"} ${esc(units())}`) +
      row("In window", m.in_window == null ? "—" : m.in_window ? "yes" : "no") +
      row(`PREDICT (${esc(p.label)})`, val(m.xtb)) +
      (p.corrected && m.xtb_raw != null ? row("xTB before correction", val(m.xtb_raw) +
        (m.xtb_extrapolated ? ' <span class="note">outside the range the correction was fitted on: extrapolated</span>' : "")) : "") +
      row("ML estimate", val(m.ml)) +
      row("QM" + (m.qm_method ? " (" + esc(m.qm_method) + ")" : ""), val(m.qm)) +
      row("Curated", m.curated ? (m.validated ? "yes, QM-validated" : "yes, not QM-validated") : "no") +
      row("Round", esc(m.round ?? "—")) + row("Parent", `<span class="mono">${esc(m.parent || "—")}</span>`) +
      (m.error ? row("Error", esc(m.error)) : "") + "</table>" +
      (m.best_level === "ml" ? '<p class="note">Only an ML estimate: treat it as a candidate to check, not a result.</p>' : "") +
      (m.best_level === "xtb" ? `<p class="note">${esc(p.label)} value only: not confirmed by QM.</p>` : "");
    $("overlay").classList.add("open");

    let xyz = null;
    if (m.has_xyz) {
      api.xyz(state.runId, m.id).then((text) => { xyz = text; viewer.render("detail3d", text); })
        .catch(() => viewer.clear("detail3d", "Could not load the geometry"));
    } else {
      viewer.clear("detail3d", "No geometry: this molecule had no PREDICT calculation");
    }
    $("dCopy").onclick = () => copy(m.smiles, "SMILES copied");
    $("dXyz").onclick = () => (xyz ? saveBlob(new Blob([xyz], { type: "chemical/x-xyz" }), m.id + ".xyz") : toast("No geometry for this molecule"));
    $("dSeed").onclick = () => { MOL.form.useSeed(m.smiles); closeDetail(); toast("Seed updated"); };
  }
  function closeDetail() { $("overlay").classList.remove("open"); }

  // ------------------------------------------------------------------ evaluation and log
  async function runEvaluation() {
    const box = $("evalOut");
    box.innerHTML = '<p class="note">Evaluating…</p>';
    try {
      const r = await api.evaluation(state.runId);
      const statusChip = (s) => `<span class="chip eval-${esc(s)}">${esc(String(s).replace(/_/g, " "))}</span>`;
      const checks = Object.entries(r.checks || {}).map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, " "))}</td><td>${statusChip(v)}</td></tr>`).join("");
      const caps = Object.values(r.capabilities || {}).map((c) => `<li>${esc(c.label)}${c.reason ? ` <span class="note">— ${esc(c.reason)}</span>` : ""}</li>`).join("");
      const counts = Object.entries((r.summary || {}).finding_counts || {}).map(([k, v]) => `<li>${esc(k.replace(/_/g, " "))}: ${v}</li>`).join("");
      box.innerHTML = `<div class="row" style="margin:12px 0">Overall: ${statusChip(r.overall)}</div>` +
        `<table class="proptable">${checks}</table>` +
        (caps ? `<h4>What could be checked</h4><ul class="plain">${caps}</ul>` : "") +
        (counts ? `<h4>Findings</h4><ul class="plain">${counts}</ul>` : "");
    } catch (e) {
      box.innerHTML = `<p class="problem">✕ ${esc(e.message)}</p>`;
    }
  }

  async function loadLog() {
    try { $("logText").textContent = (await api.log(state.runId)) || "No output recorded (runs started outside this app have no log here)."; }
    catch (e) { $("logText").textContent = "Could not load the log: " + e.message; }
  }

  // ------------------------------------------------------------------ actions
  async function stopRun() {
    if (!confirm(`Stop run ${state.runId}?\n\nFinished steps are kept and you can resume it later.`)) return;
    try { await api.stop(state.runId); toast("Stopping…"); load(); }
    catch (e) { toast(e.message); }
  }

  async function resumeRun() {
    if (state.overview.status === "unknown" &&
        !confirm("This run was not started from this app. Make sure it is not still running in a terminal, then continue.")) return;
    try { await api.resume(state.runId); toast("Resuming " + state.runId); state.events = []; state.cursor = 0; load(); refreshList(); }
    catch (e) { toast(e.message); }
  }

  async function download(what) {
    $("dlMenu").hidden = true;
    toast("Preparing download…");
    try {
      const blob = what === "archive" ? await api.archive(state.runId) : await api.file(state.runId, what);
      saveBlob(blob, what === "archive" ? state.runId + ".zip" : state.runId + "-" + what);
    } catch (e) { toast(e.message); }
  }

  function selectTab(tab) {
    state.tab = tab;
    document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.getAttribute("data-tab") === tab));
    document.querySelectorAll(".tabpane").forEach((p) => { p.hidden = p.getAttribute("data-pane") !== tab; });
    if (tab === "summary") loadSummary();
    if (tab === "log") loadLog();
  }

  function bind() {
    $("runSel").addEventListener("change", () => select($("runSel").value));
    $("refreshRuns").addEventListener("click", () => refreshList());
    $("stopBtn").addEventListener("click", stopRun);
    $("resumeBtn").addEventListener("click", resumeRun);
    $("dlBtn").addEventListener("click", (e) => { e.stopPropagation(); $("dlMenu").hidden = !$("dlMenu").hidden; });
    document.addEventListener("click", () => { $("dlMenu").hidden = true; });
    document.querySelectorAll("[data-dl]").forEach((b) => b.addEventListener("click", () => download(b.getAttribute("data-dl"))));
    document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => selectTab(b.getAttribute("data-tab"))));
    document.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("[data-filter]").forEach((x) => x.setAttribute("aria-selected", x === b));
      state.filter = b.getAttribute("data-filter"); state.shown = CARD_PAGE; renderMolecules();
    }));
    $("sortSel").addEventListener("change", () => { state.sort = $("sortSel").value; renderMolecules(); });
    $("evalBtn").addEventListener("click", runEvaluation);
    $("logBtn").addEventListener("click", loadLog);
    $("closeSheet").addEventListener("click", closeDetail);
    $("overlay").addEventListener("click", (e) => { if (e.target === $("overlay")) closeDetail(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });
  }

  MOL.monitor = { init: bind, refreshList: refreshList, select: select, selected: () => state.runId,
                  librariesReady: () => { if (state.overview) renderMolecules(); } };
})();
