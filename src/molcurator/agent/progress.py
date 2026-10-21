"""Live progress in the terminal, built from trace events, so progress and trace never disagree (R8.3)."""
from collections import Counter
from datetime import datetime

from rich.markup import escape


def progress_text(event: dict) -> str:
    """One rich-markup line for a trace event: node, status, counts or decision reason, and duration."""
    if event["node"] == "run_start":
        return f"[bold]Run {event['run_id']}[/] started"
    seconds = (datetime.fromisoformat(event["ended_at"]) - datetime.fromisoformat(event["started_at"])).total_seconds()
    head = f"r{event['round']} [bold]{event['node']}[/]"
    if event["status"] == "failed":
        return f"{head} [red]failed: {escape(event['error'])}[/]"  # escaped: errors may contain [ ]
    if event["status"] == "skipped":
        return f"{head} [dim]skipped: {event['reason']}[/]"
    out = event["outputs"]
    if "round_stats" in out:
        s = out["round_stats"]
        detail = f"generated {s['generated']} · xTB {s['xtb_runs']} · ML {s['ml_predicted']} · screened in {s['screened_in']} · hits {s['hits']}"
    elif "model" in out:  # TRAIN: how much it learned from, and how well it beats guessing the mean
        m = out["model"]["metrics"]
        detail = f"trained on {out['model']['n_examples']}"
        if "test_mae" in m and "baseline_mae" in m:
            detail += f" · test MAE {m['test_mae']:.2f} (mean baseline {m['baseline_mae']:.2f})"
    elif "results" in out:
        detail = " · ".join(f"{k} {n}" for k, n in Counter(r[1] for r in out["results"]).items())
    else:
        detail = escape((event.get("llm") or {}).get("decision", {}).get("reason") or out.get("stop_reason") or "")
    return f"{head} {detail} [dim]({seconds:.1f} s)[/]"
