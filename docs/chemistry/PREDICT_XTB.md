# xTB prediction tool

Branch `tools/predict-xtb` implements the first supported target, `homo_lumo_gap` in eV, using the exact shared `predict(candidates, target, xyz_dir)` signature. The generator merged into main can pass its Candidate list directly. The return is one shared Prediction per input, with preserved IDs/order and explicit failures.

```python
from molcurator.tools.predict import predict
# predictions = predict(candidates, config.target, run_dir / "xyz")
```

Set `XTB_BIN` to an executable or place `xtb` on PATH. Set `MOLCURATOR_QC_TIMEOUT_S` to override 600 seconds per process. Run chemistry on an allocated compute node. The tool embeds 30 ETKDG conformers, minimizes with MMFF94/UFF, deduplicates heavy-atom RMSD at 0.25 angstrom, selects the lowest converged FF minimum and runs one GFN2-xTB optimization. The FF Boltzmann report uses 298.15 K over sampled unique minima.

Successful results write `xyz_dir/<id>.xyz`. Raw output and FF JSON/Markdown reports are under `xyz_dir/calculations/<id>/xtb/`. Unsupported targets, charged/open-shell/disconnected chemistry, optimization failures and missing properties are failed records. No visualization, calibration, graph policy or automatic ORCA call is added. Main tools remain untouched; the agent maintainer explicitly injects this function.

This PR is the small gap-adapter foundation. The richer property API and other backends are separate review pieces. Tests use real RDKit sampling and simulated xTB; actual executable compatibility still requires cluster verification.
