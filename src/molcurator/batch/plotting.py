"""Optional headless plots for batch reports; imported only when plots are requested."""


def require_plotting() -> None:
    try:
        import matplotlib  # noqa: F401
    except ImportError as exc:
        raise ImportError("Plots require matplotlib: run uv sync --extra reports, or use --no-plots") from exc


def render_plots(root, rows, records, value_label: str) -> None:
    require_plotting()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    stages = ("predict", "qm")
    with plt.rc_context({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False}):
        plots = root / "plots"
        plots.mkdir(exist_ok=True)

        fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
        plotted = False
        for key, label, color in (("predict_value", "PREDICT", "#1e7084"), ("qm_value", "QM (ORCA)", "#cf793a")):
            points = [(i, row[key]) for i, row in enumerate(rows) if row[key] is not None]
            if points:
                ax.scatter([i for i, _ in points], [v for _, v in points], label=label, color=color)
                plotted = True
        if plotted:
            ax.legend()
        else:
            ax.text(.5, .5, "No successful values", ha="center", transform=ax.transAxes)
        if len(rows) <= 20:
            ax.set_xticks(range(len(rows)), [r["candidate_id"] for r in rows], rotation=30, ha="right")
        ax.set(xlabel="Candidate in input order", ylabel=value_label, title="Current batch results")
        fig.savefig(str(plots / "values.png"), dpi=180)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
        good = [sum(row[f"{s}_status"] == "ok" for row in rows) for s in stages]
        failed = [sum(row[f"{s}_status"] == "failed" for row in rows) for s in stages]
        missing = [len(rows) - a - b for a, b in zip(good, failed, strict=True)]
        ax.bar([0, 1], good, label="Successful", color="#1e7084")
        ax.bar([0, 1], failed, bottom=good, label="Failed", color="#c96352")
        ax.bar([0, 1], missing, bottom=[a + b for a, b in zip(good, failed, strict=True)],
               label="Not calculated or pending", color="#b9c7ca")
        ax.set_xticks([0, 1], ["PREDICT", "QM"])
        ax.set_xlim(-.6, 1.6)
        ax.set(ylabel="Candidates", title="Current result coverage")
        ax.legend(fontsize=8)
        fig.savefig(str(plots / "status.png"), dpi=180)
        plt.close(fig)

        fig, axes = plt.subplots(1, 2, figsize=(9, 4), layout="constrained")
        backends = ("xtb", "orca")
        launched = [r for r in records if r.get("backend")]
        axes[0].bar(backends, [sum(r["backend"] == b for r in launched) for b in backends], color="#1e7084")
        axes[0].set(ylabel="Count", title="Calculations recorded")
        axes[1].bar(backends, [sum(r.get("runtime_s", 0) for r in launched if r["backend"] == b) for b in backends],
                    color="#1e7084")
        axes[1].set(ylabel="Seconds", title="Recorded runtime")
        fig.savefig(str(plots / "execution.png"), dpi=180)
        plt.close(fig)

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
        fig.savefig(str(plots / "conformers.png"), dpi=180)
        plt.close(fig)
