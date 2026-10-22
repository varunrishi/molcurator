/* assistant.js — the agent view: set up a run by describing it in plain language.
 *
 * Each message goes to POST /api/assistant/plan. Claude, on the server, fills in a small form
 * from the message; the server merges it into a run config and checks it exactly like the
 * dashboard does. This view shows that proposal (target, seed drawing, budgets, problems and
 * warnings). Nothing runs until the user presses Start run. Follow-up messages refine the
 * current proposal. Once started, the run's progress is shown here and in the dashboard.
 *
 * The view exists only when the server has Claude (system.assistant.available); app.js hides
 * it, and its switch button, otherwise. */
(function () {
  "use strict";
  const { $, esc, fmt, duration, toast } = MOL.ui;
  const api = MOL.api, chem = MOL.chem, config = MOL.config;

  const STATUS_TEXT = { starting: "Starting", running: "Running", stopping: "Stopping", finished: "Finished",
                        failed: "Failed", interrupted: "Stopped", unknown: "Not tracked" };
  const STOP_REASON = { target_dataset_size: "the dataset reached its target size", max_rounds: "all rounds were used",
                        max_qm_calls: "all QM calls were used", max_wall_time: "the time budget ran out",
                        llm: "the LLM decided to stop", error: "a step failed" };
  const NODE_LABEL = { plan_round: "planning", generate: "generating", predict: "running PREDICT", train: "training ML",
                       ml_predict: "ML estimates", screen: "screening", select_qm_batch: "picking the QM batch",
                       validate: "running QM", curate: "curating", close_round: "closing the round",
                       continue_or_stop: "deciding whether to continue", write_summary: "writing the summary" };

  const state = { current: null, busy: false, watch: null };

  // ------------------------------------------------------------------ thread
  function add(role, html) {
    $("agentWelcome").hidden = true;
    const el = document.createElement("div");
    el.className = "msg " + role.split(" ").map((r) => "msg-" + r).join(" ");
    el.innerHTML = html;
    $("agentThread").appendChild(el);
    el.scrollIntoView({ behavior: "smooth", block: "end" });
    return el;
  }

  async function send(text) {
    text = text.trim();
    if (!text || state.busy) return;
    state.busy = true;
    $("agentSend").disabled = true;
    add("user", esc(text).replace(/\n/g, "<br>"));
    const thinking = add("agent", '<span class="typing"><i></i><i></i><i></i></span>');
    try {
      const plan = await api.assistantPlan(text, state.current);
      thinking.innerHTML = renderPlan(plan);
      if (plan.understood && plan.config) state.current = plan.config;   // follow-ups refine this proposal
      bindPlan(thinking, plan);
    } catch (e) {
      thinking.classList.add("msg-error");
      thinking.textContent = e.message;
    } finally {
      state.busy = false;
      $("agentSend").disabled = false;
      $("agentInput").focus();
    }
  }

  // ------------------------------------------------------------------ the proposal card
  function renderPlan(plan) {
    let html = `<p>${esc(plan.reply)}</p>`;
    if (!plan.understood || !plan.config) return html;
    const c = plan.config, t = c.target || {}, b = c.budget || {}, g = (c.generation || {}).defaults || {};
    const seed = plan.seed;
    const seedHtml = seed && seed.valid
      ? `<div class="plan-seed"><div class="plan-depict">${chem.depictSVG(seed.canonical, 180, 110) || ""}</div>` +
        `<div><code class="mono">${esc(seed.canonical)}</code><div class="note">${esc(seed.formula)} · ${seed.heavy_atoms} heavy atoms</div></div></div>`
      : '<span class="missing">not given yet</span>';
    const windowText = t.min == null && t.max == null ? '<span class="missing">not given yet</span>'
      : `${t.min ?? "…"} – ${t.max ?? "…"} ${esc(t.units || "")}`;
    const row = (k, v) => `<div class="plan-row"><span class="k">${k}</span><span class="v">${v}</span></div>`;
    html += `<div class="plan">` +
      `<div class="plan-head"><b>Proposed run</b><span class="chip ${plan.ready ? "good" : "bad"}">${plan.ready ? "ready to start" : "needs input"}</span></div>` +
      row("Property", esc(plan.target ? plan.target.label : t.name)) +
      row("Target window", windowText) +
      row("Seed", seedHtml) +
      row("Search", `${g.n_candidates} candidates per round · mutation strength ${g.mutation_strength}`) +
      row("Budget", `${b.max_rounds} rounds · stop at ${b.target_dataset_size} molecules · ${Math.round((b.max_wall_time || 0) / 60)} min`) +
      (plan.predict_level ? row("PREDICT", esc(plan.predict_level.label)) : "") +
      row("QM validation", c.qm && c.qm.enabled ? `on (${esc(c.qm.functional)}/${esc(c.qm.basis)})` : "off: hits are PREDICT/ML estimates") +
      row("Decisions", c.decisions === "llm" ? "LLM" : "rules") +
      (plan.defaults_used && plan.defaults_used.length
        ? `<p class="note">Defaults used for: ${esc(plan.defaults_used.join(", "))}. Ask to change any of them.</p>` : "") +
      (plan.problems || []).map((p) => `<div class="problem">✕ ${esc(p)}</div>`).join("") +
      `<div class="plan-actions">` +
      `<button class="btn primary" data-act="start" ${plan.ready ? "" : "disabled"}>Start run</button>` +
      `<button class="btn" data-act="edit">Edit in dashboard</button></div>` +
      `<p class="note">Interpreted by ${esc(plan.model || "Claude")}. Check the seed drawing before starting.</p></div>`;
    return html;
  }

  function bindPlan(el, plan) {
    const start = el.querySelector('[data-act="start"]');
    const edit = el.querySelector('[data-act="edit"]');
    if (start) start.addEventListener("click", () => startRun(plan, start));
    if (edit) edit.addEventListener("click", () => {
      MOL.form.load(plan.config);
      MOL.app.setView("dashboard");
      toast("Proposal loaded into the New run form");
    });
  }

  async function startRun(plan, button) {
    button.disabled = true;
    try {
      const r = await api.start(plan.config, null);
      state.current = null;   // the next message starts a new proposal
      state.lastRunId = r.run_id;
      const el = add("agent", `<p>Started run <code class="mono">${esc(r.run_id)}</code>.</p>` +
        `<div class="live" data-run="${esc(r.run_id)}"><span class="chip status-starting">Starting</span> <span class="live-text"></span></div>` +
        `<div class="plan-actions"><button class="btn sm" data-act="open">Watch in dashboard</button></div>`);
      el.querySelector('[data-act="open"]').addEventListener("click", () => openInDashboard(r.run_id));
      MOL.monitor.refreshList();
      watch(r.run_id, el);
    } catch (e) {
      button.disabled = false;
      add("agent error", esc(e.message) + (e.problems || []).map((p) => "<br>✕ " + esc(p)).join(""));
    }
  }

  function openInDashboard(runId) {
    if (state.lastRunId === runId) state.lastRunId = null;
    MOL.app.setView("dashboard");
    MOL.monitor.refreshList(runId);
  }

  // ------------------------------------------------------------------ following the started run
  // One request per refresh (GET /api/runs/<id>), paused while the tab is hidden.
  function watch(runId, el) {
    if (state.watch) clearTimeout(state.watch.timer);
    state.watch = { runId: runId, el: el, timer: null };
    const tick = async () => {
      if (!state.watch || state.watch.runId !== runId) return;
      if (!document.hidden) {
        try {
          const o = await api.run(runId);
          showProgress(el, o);
          if (!["starting", "running", "stopping"].includes(o.status)) { finished(el, o); return; }
        } catch (e) { /* shown again on the next refresh */ }
      }
      state.watch.timer = setTimeout(tick, config.pollSeconds() * 1000);
    };
    tick();
  }

  function showProgress(el, o) {
    const chip = el.querySelector(".live .chip");
    chip.className = "chip status-" + o.status;
    chip.textContent = STATUS_TEXT[o.status] || o.status;
    const b = o.budget || {};
    const parts = [];
    if (o.current && o.current.round) parts.push(`round ${o.current.round} of ${b.max_rounds ?? "?"}`);
    if (o.current && o.current.node) parts.push(NODE_LABEL[o.current.node] || o.current.node);
    if (b.dataset_size != null) parts.push(`${b.dataset_size} curated`);
    if (o.running_seconds) parts.push(duration(o.running_seconds));
    el.querySelector(".live-text").textContent = parts.join(" · ");
  }

  async function finished(el, o) {
    let text = o.status === "finished"
      ? `Finished: ${STOP_REASON[o.stop_reason] || o.stop_reason}. ${o.budget.dataset_size} molecules curated`
      : o.status === "failed" ? `The run failed: ${o.error || "see the Log tab in the dashboard"}`
      : "The run stopped before finishing; it can be resumed from the dashboard";
    if (o.status === "finished") {
      try {   // say how far the curated values can be trusted
        const mols = await api.molecules(o.run_id);
        const curated = mols.filter((m) => m.curated);
        const qm = curated.filter((m) => m.validated).length;
        const level = (l) => (l === "qm" ? "QM" : l === "ml" ? "ML" : (o.predict_level ? o.predict_level.method : "PREDICT"));
        const levels = ["qm", "xtb", "ml"].map((l) => [l, curated.filter((m) => m.best_level === l).length]).filter((x) => x[1]);
        text += levels.length ? ` (${levels.map(([l, n]) => `${n} by ${level(l)}`).join(", ")})` : "";
        if (!qm && curated.length) text += ". None is QM-validated: treat them as candidates";
        const best = curated.filter((m) => m.best_value != null).slice(0, 6);
        if (best.length) {
          text += ".";
          const cards = best.map((m) => `<div class="mini-card">${chem.depictSVG(m.smiles, 120, 80) || ""}` +
            `<span>${fmt(m.best_value)} ${esc((o.target && o.target.units) || "")} <span class="lvbadge ${m.best_level}">${esc(level(m.best_level))}</span></span></div>`).join("");
          add("agent", `<p>${esc(text)}</p><div class="mini-cards">${cards}</div>` +
            `<div class="plan-actions"><button class="btn sm" data-act="open">Open the results</button></div>`)
            .querySelector('[data-act="open"]').addEventListener("click", () => openInDashboard(o.run_id));
          return;
        }
      } catch (e) { /* the summary below is still correct */ }
    }
    add("agent", `<p>${esc(text)}.</p><div class="plan-actions"><button class="btn sm" data-act="open">Open in dashboard</button></div>`)
      .querySelector('[data-act="open"]').addEventListener("click", () => openInDashboard(o.run_id));
  }

  // ------------------------------------------------------------------ wiring
  function init() {
    $("agentForm").addEventListener("submit", (e) => { e.preventDefault(); const v = $("agentInput").value; $("agentInput").value = ""; send(v); });
    $("agentInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("agentForm").requestSubmit(); }
    });
    document.querySelectorAll("#agentExamples .example").forEach((b) =>
      b.addEventListener("click", () => { $("agentInput").value = b.textContent.trim(); $("agentInput").focus(); }));
  }

  MOL.assistant = {
    init: init,
    // The run started here that the dashboard has not shown yet (returned once, then forgotten).
    takeStartedRun: () => { const id = state.lastRunId || null; state.lastRunId = null; return id; },
    setModel: (model) => { $("agentModel").textContent = model ? "Claude (" + model + ")" : "Claude"; }
  };
})();
