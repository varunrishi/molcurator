"""CSV summaries and scientific plots from actual batch results and attempt records."""
import json

from .chem.summary import summarize
from .fileio import atomic_json, native_path
from .report_tables import build_rows, write_csv


def require_plotting():
    from .plotting import require_plotting as check
    check()



def generate_report(root, plots=False):
    root = native_path(root)
    if plots:
        require_plotting()
    state = json.loads((root / "results.json").read_text())
    if state.get("schema_version") != 1 or not isinstance(state.get("rows"), list):
        raise ValueError("not a supported property batch results file")
    summary = summarize(root / "xyz")
    rows, warnings = build_rows(state, root, summary["records"])
    warnings.extend(f"Attempt record: {e['path']}: {e['error']}" for e in summary["record_errors"])
    write_csv(root, rows)
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
        from .plotting import render_plots
        render_plots(root, rows, summary["records"])
        lines += ["## Figures", "", "![Current orbital gaps](plots/gaps.png)", "",
                  "![Current result coverage](plots/status.png)", "",
                  "![Cumulative execution history](plots/execution.png)", "",
                  "![Latest available geometry reports](plots/conformers.png)", ""]
    if warnings:
        lines += ["## Record warnings", ""] + ["- " + warning for warning in warnings]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return dict(counts=counts, warnings=warnings, summary=summary)
