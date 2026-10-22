"""Optional headless visualizations; imported only for an explicit plotting request."""

def require_plotting():
    try:
        import matplotlib
    except ImportError as exc:
        raise ImportError("Plots require matplotlib: run uv sync --extra reports, or use --no-plots") from exc



def render_plots(root, rows, attempts):
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
