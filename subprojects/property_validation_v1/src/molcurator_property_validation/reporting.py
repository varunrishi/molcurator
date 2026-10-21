"""CSV summaries and scientific plots from actual batch results and attempt records."""
import csv
import json
from pathlib import Path

from .chem.summary import summarize
from .chem.tracking import atomic_json, native_path


def require_plotting():
    try:
        import matplotlib
    except ImportError as exc:
        raise ImportError("Plots require matplotlib: run uv sync --extra reports, or use --no-plots") from exc


def _rows(state, root, attempts):
    rows = []
    warnings = []
    for item in state["rows"]:
        candidate = item["candidate"]
        prediction = item.get("prediction") or {}
        qm = item.get("qm_result") or {}
        cid = candidate["id"]
        selected = [r for r in attempts if r.get("candidate_id") == cid]
        geometry = {}
        path = root / "xyz/calculations" / cid / "xtb/geometry_report.json"
        if path.is_file() and prediction.get("status") == "ok":
            try:
                geometry = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                warnings.append(f"Geometry report for {cid}: {exc}")
        rows.append(dict(candidate_id=cid, smiles=candidate["smiles"],
            parent_smiles=candidate["parent_smiles"], round=candidate["round"],
            generator=candidate["generator"], xtb_status=prediction.get("status", "pending"),
            xtb_gap_ev=prediction.get("value"), xtb_error=prediction.get("error"),
            xyz_path=prediction.get("xyz_path"),
            orca_status=qm.get("status", item["orca_selection"]),
            orca_gap_ev=qm.get("value"), orca_error=qm.get("error"), method=qm.get("method"),
            ff_energy_kcal_mol=geometry.get("selected_ff_energy_kcal_mol"),
            ff_boltzmann_weight=geometry.get("selected_ff_boltzmann_weight"),
            temperature_k=geometry.get("temperature_k"), n_unique_conformers=geometry.get("n_unique"),
            xtb_calls=sum(r.get("electronic_calls_attempted", 0) for r in selected if r.get("backend") == "xtb"),
            orca_calls=sum(r.get("electronic_calls_attempted", 0) for r in selected if r.get("backend") == "orca"),
            cache_hits=sum(bool(r.get("cache_hit")) for r in selected),
            runtime_s=sum(r.get("runtime_s", 0) for r in selected)))
    return rows, warnings


def _plots(root, rows, attempts):
    require_plotting()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with plt.rc_context({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}):
        plots = root / "plots"
        plots.mkdir(exist_ok=True)
        fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
        plotted = False
        for key, label, color in (("xtb_gap_ev", "GFN2-xTB", "#1e7084"),
                                   ("orca_gap_ev", "ORCA", "#cf793a")):
            points = [(i, row[key]) for i, row in enumerate(rows) if row[key] is not None]
            if points:
                ax.scatter([i for i, _ in points], [v for _, v in points], label=label, color=color)
                plotted = True
        if not plotted:
            ax.text(.5, .5, "No successful gap values", ha="center", transform=ax.transAxes)
        else:
            ax.legend()
        if len(rows) <= 20:
            ax.set_xticks(range(len(rows)), [r["candidate_id"] for r in rows], rotation=30, ha="right")
        ax.set(xlabel="Candidate in input order", ylabel="Orbital HOMO-LUMO gap / eV", title="Current batch results")
        fig.savefig(str(plots / "gaps.png"), dpi=180); plt.close(fig)

        fig, axes = plt.subplots(1, 2, figsize=(9, 4), layout="constrained")
        backends = ["xtb", "orca"]
        calls = [sum(r.get("electronic_calls_attempted", 0) for r in attempts if r.get("backend") == b) for b in backends]
        hits = [sum(bool(r.get("cache_hit")) for r in attempts if r.get("backend") == b) for b in backends]
        runtime = [sum(r.get("runtime_s", 0) for r in attempts if r.get("backend") == b) for b in backends]
        axes[0].bar([-.18, .82], calls, width=.35, label="Process launches", color="#1e7084")
        axes[0].bar([.18, 1.18], hits, width=.35, label="Cache reuse", color="#77b4a5")
        axes[0].set_xticks([0, 1], backends); axes[0].legend(fontsize=8)
        axes[0].set_xlim(-.6, 1.6)
        axes[0].set(ylabel="Count", title="Cumulative attempts and reuse")
        axes[1].bar(backends, runtime, color="#1e7084")
        axes[1].set_xlim(-.6, 1.6)
        axes[1].set(ylabel="Recorded process seconds", title="Cumulative electronic runtime")
        fig.savefig(str(plots / "execution.png"), dpi=180); plt.close(fig)

        fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
        good = [sum(row[key] == "ok" for row in rows) for key in ("xtb_status", "orca_status")]
        failed = [sum(row[key] == "failed" for row in rows) for key in ("xtb_status", "orca_status")]
        missing = [len(rows) - a - b for a, b in zip(good, failed)]
        ax.bar([0, 1], good, label="Successful", color="#1e7084")
        ax.bar([0, 1], failed, bottom=good, label="Failed", color="#c96352")
        ax.bar([0, 1], missing, bottom=[a+b for a, b in zip(good, failed)],
               label="Not calculated or pending", color="#b9c7ca")
        ax.set_xticks([0, 1], backends); ax.set_xlim(-.6, 1.6)
        ax.set(ylabel="Candidates", title="Current result coverage")
        ax.legend(fontsize=8)
        fig.savefig(str(plots / "status.png"), dpi=180); plt.close(fig)

        fig, axes = plt.subplots(1, 2, figsize=(9, 4), layout="constrained")
        for ax, key, title, ylabel in ((axes[0], "n_unique_conformers", "Unique sampled FF minima", "Count"),
                                      (axes[1], "ff_boltzmann_weight", "Selected FF population estimate", "Fraction")):
            points = [(i, row[key]) for i, row in enumerate(rows) if row[key] is not None]
            if points:
                ax.bar([i for i, _ in points], [v for _, v in points], color="#1e7084")
            else:
                ax.text(.5, .5, "No geometry reports", ha="center", transform=ax.transAxes)
            if len(rows) <= 20:
                ax.set_xticks(range(len(rows)), [r["candidate_id"] for r in rows], rotation=45, ha="right")
            ax.set(title=title, ylabel=ylabel, xlabel="Candidate in input order")
        axes[1].set_ylim(0, 1.05)
        fig.savefig(str(plots / "conformers.png"), dpi=180); plt.close(fig)


def generate_report(root, plots=True):
    root = native_path(root)
    if plots:
        require_plotting()
    state = json.loads((root / "results.json").read_text())
    if state.get("schema_version") != 1 or not isinstance(state.get("rows"), list):
        raise ValueError("not a supported property batch results file")
    summary = summarize(root / "xyz")
    rows, warnings = _rows(state, root, summary["records"])
    warnings.extend(f"Attempt record: {e['path']}: {e['error']}" for e in summary["record_errors"])
    with (root / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["candidate_id"])
        writer.writeheader(); writer.writerows(rows)
    atomic_json(root / "attempt_summary.json", summary)
    counts = dict(total=len(rows), xtb_ok=sum(r["xtb_status"] == "ok" for r in rows),
                  xtb_failed=sum(r["xtb_status"] == "failed" for r in rows),
                  orca_ok=sum(r["orca_status"] == "ok" for r in rows),
                  orca_failed=sum(r["orca_status"] == "failed" for r in rows))
    lines = ["# Molecular property batch report", "", f"Run status: {state['run_status']}",
             f"Invocation: {state['invocation_id']}", "", "## Current results", "",
             f"Candidates: {counts['total']}; xTB successful: {counts['xtb_ok']}; xTB failed: {counts['xtb_failed']}.",
             f"ORCA successful: {counts['orca_ok']}; ORCA failed: {counts['orca_failed']}.",
             "Missing or unrequested QM values are not zero-valued predictions.", "",
             "## Calculation history", "",
             f"Cumulative launched calls: xTB {summary['by_backend']['xtb']}, ORCA {summary['by_backend']['orca']}.",
             f"Cache hits: {summary['cache_hits']}; recorded process runtime: {summary['runtime_s']:.3f} s.",
             f"Running or interrupted events: {summary['running_or_interrupted']}.", "",
             "These counts include previous invocations retained in this run directory. Cache hits launch no calculation.",
             "ORCA selection limit applies per invocation, counts selected inputs including cache hits, and is not a cumulative compute budget.", "",
             "## Files", "", "- [Candidate results and configuration](results.json)",
             "- [CSV summary](summary.csv)", "- [Attempt history](attempt_summary.json)", "",
             "## Interpretation", "",
             "Values are raw orbital gaps in eV, not optical excitation energies or experimental accuracy estimates.",
             "The selected geometry is an MMFF94 minimum. Its Boltzmann population is conditional on the unique sampled force-field minima.",
             "No calibration or model accuracy estimate is fitted by this report.", ""]
    if state.get("qm"):
        lines += [f"ORCA method: {state['qm']['functional']}/{state['qm']['basis']}.", ""]
    if plots:
        _plots(root, rows, summary["records"])
        lines += ["## Figures", "", "![Current orbital gaps](plots/gaps.png)", "",
                  "![Current result coverage](plots/status.png)", "",
                  "![Cumulative execution history](plots/execution.png)", "",
                  "![Latest available geometry reports](plots/conformers.png)", ""]
    if warnings:
        lines += ["## Record warnings", ""] + ["- " + warning for warning in warnings]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return dict(counts=counts, warnings=warnings, summary=summary)
