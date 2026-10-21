# Calibrated screening — contributor handoff

Shared branch: `codex/calibrated-screening-v1` in `varunrishi/molcurator`.

This is an isolated continuation of `codex/property-validation-v1` at `fee3c67`. It adds the calibrated-screening research update (`207ec40`) and handoff documentation. The existing property-validation branch and main are not modified by publishing this branch. Shared history is intentional: the new branch contains the adapters it depends on, rather than a second competing copy.

## Description and scope

The HOMO–LUMO adapters now have supporting calibration evidence and a separate ranking utility. Raw `Prediction.value` stays GFN2-xTB; `QMResult.value` stays the configured reference calculation. `src/molcurator/screening/gap.py` applies frozen corrections without changing either shared model. Optional py3Dmol previews read the returned XYZ files. Property export and report scripts preserve method labels, selection probabilities, failures, and FF geometry metadata.

The 60 committed B3LYP validation rows reproduce sample MAEs of 2.231 eV (raw), 0.396 eV (constant), and 0.364 eV (linear). Their inverse-probability weights sum to the 568 successfully screened molecules. One confirmed target hit is present. This is a separate research evaluation, not an agent run within the default QM budget. The eight-molecule initial holdout favored the constant correction, so the linear correction is provisional rather than universally best.

## Pull this branch separately

On the cluster or another development machine:

```bash
 git clone --branch codex/calibrated-screening-v1 --single-branch \
   https://github.com/varunrishi/molcurator.git molcurator-calibrated-screening
 cd molcurator-calibrated-screening
 uv sync --locked
 uv run pytest -q tests subprojects/property_validation_v1/tests
```

For subsequent updates in this checkout use `git pull --ff-only`. A separate folder keeps historical calculation outputs and other active branches independent. Dependencies include pandas, matplotlib and py3Dmol; full-project installation also includes PySCF and the agent/ML dependencies. For execution details and external binary configuration, see [the cluster guide](../subprojects/property_validation_v1/CLUSTER.md). That guide's original clone command names the earlier branch; use the new branch command above for this update.

## Run the utilities

From this checkout, after a successful adapter smoke run has written `results.json`:

```bash
uv run python scripts/rank_calibrated_predictions.py \
  --input /path/to/run/results.json --output /path/to/run/ranked.csv \
  --model linear --min 3.0 --max 3.5 --margin 0.75

uv run python scripts/export_molecule_viewers.py \
  --input /path/to/run/results.json --out /path/to/run/viewers --max-viewers 30
```

Replace `/path/to/run` with a real run directory. For automatic viewer export after PREDICT, set `MOLCURATOR_VIEWERS=1`; it is off by default. HTML viewers can be copied to a desktop browser and may need internet access for their JavaScript. Visualization performs no QM calculations.

The checked-in scientific report is [REPORT.md](../research/property_validation_results/report/REPORT.md). Its generator is `scripts/build_property_report.py`, which requires the original cluster directory layout, including `target_validation/screen/validation_results.csv` and `calibrated_ranking.csv`. The repository includes validated CSV exports and figures, but not every original cluster artifact. See [property export instructions](CALIBRATION_AND_PROPERTY_EXPORT.md) and [the scientific update](PROPERTY_VALIDATION_UPDATE.md).

## Integration boundaries for the agent maintainer

1. The tools and shared schemas keep their existing signatures. No changes to `config.py`, YAML screening defaults, or the graph are introduced here. The optional viewer hook is the only added call in `predict()`.
2. Call `ranked_predictions(predictions, target)` after successful prediction, before choosing a QM batch. Failures remain represented and sort last; IDs and raw values remain intact.
3. Match the frozen calibration to `dft:B3LYP/def2-SVP`. The ranking API records the calibration method but does not enforce a comparison with the run's `QMSettings`; the orchestrator must check that match. Do not apply these coefficients to PBE0, S1, or TADF.
4. The returned `selected` flag describes an exploratory band, not a validated rejection bound. Preserve an exploration allocation outside it; no automatic hard filter is enabled by this branch.
5. Keep QM budgets and cumulative attempt accounting in the orchestrator. The 24 calibration and 60 validation calculations are research campaigns, not new default batch sizes.
6. Agree on policy before changing the fixed raw-xTB screening step: if the agent rejects candidates before calibrated ranking, the new utility cannot recover them. No graph changes are included here.

## Review and validation

At publication, all 42 offline tests passed in a lightweight Python 3.11 environment. They cover the tool adapters, calibrated ranking, property export, and viewer behavior. The 60-row CSV metrics were independently recomputed; raw cluster QC logs were not re-executed or audited during this review. Full `uv sync` previously failed on this Windows machine because PySCF required missing native build tools; cluster installation must be checked separately.

Review this branch relative to `codex/property-validation-v1` at `fee3c67` to see the new research/ranking work. If merging the whole tool contribution into main later, review its combined diff against main and use a normal reviewed merge. Nothing has been merged into main by publishing this branch.
