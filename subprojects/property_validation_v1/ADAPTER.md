# HOMO–LUMO adapter: first iteration

The root `molcurator.tools.predict.predict` and `molcurator.tools.validate.validate` implement the `v0.1-contract` signatures without changing the shared models. The historical scripts in this subproject remain unchanged. The adapter adapts their geometry and parsing approach into importable package helpers, with no runtime import from the archived scripts.

## Geometry and reported weight

PREDICT embeds 30 conformers using ETKDGv3 (seed 42), minimizes them with MMFF94 or UFF when MMFF parameters are unavailable, and discards nonconverged or nonfinite FF results. It sorts by FF energy and deduplicates using symmetry-aware heavy-atom RMSD at 0.25 Å. There is no energy-window truncation. It chooses the lowest-energy minimum, performs one GFN2-xTB optimization, and passes that optimized geometry to VALIDATE. There is no post-xTB reranking or conformer aggregation.

The selected minimum's reported weight is `1 / sum(exp(-(E_j-E_min)/(R*T)))` across unique converged FF minima, using kcal/mol energies and T = 298.15 K. It is labelled **FF-based Boltzmann weight within the sampled conformer set**, not an experimental population or an xTB/QM ensemble. The JSON report records the unique energies, count, force field, temperature, seed, and selected conformer; a Markdown report includes the weight for inspection. These are per-molecule artifacts, not yet incorporated into the agent's final summary.

## Calling the adapters

In an installed root environment with RDKit and external binaries available:

```python
from pathlib import Path
from molcurator.schemas import Candidate, PropertyTarget, QMSettings, Status
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate

target = PropertyTarget(name="homo_lumo_gap", min=3.0, max=3.5, units="eV")
candidates = [Candidate(id="r1-c001", smiles="CCO", parent_smiles="CCO",
                        round=1, generator="manual")]
predictions = predict(candidates, target, Path("data/runs/example/xyz"))
selected = [p for p in predictions if p.status is Status.ok]
results = validate(selected, target, QMSettings(backend="orca", functional="B3LYP", basis="def2-SVP"))
```

Set `XTB_BIN` and `ORCA_BIN` to executable paths, or put `xtb` and `orca` on PATH. The adapters read process environment variables; they do not load `.env` themselves. `MOLCURATOR_QC_TIMEOUT_S` sets each external process timeout (600 seconds by default). Each process uses one thread. ORCA input uses the supplied functional and basis, `TightSCF`, a neutral singlet, and 2000 MB maxcore; it performs a ground-state single point, not TDDFT or geometry optimization. The ORCA backend is called through its executable; no OPI dependency is required in this iteration.

## Artifacts and failure handling

- `xyz/<candidate_id>.xyz`: successful xTB geometry for the shared Prediction contract.
- `xyz/calculations/<id>/xtb/`: initial geometry, optimized geometry, raw output, `geometry_report.json`, and `geometry_report.md`.
- `xyz/calculations/<id>/orca/`: copied geometry, generated input, raw output, and `attempt.json`.

Both tools preserve input IDs and order and return one result per input, including errors. Invalid or unsupported inputs are failed results. Candidate IDs must contain only letters, digits, underscores, or hyphens. xTB must terminate normally with converged optimization, a gap in eV, and a valid optimized XYZ with unchanged element order. ORCA must exit successfully, confirm SCF convergence and normal termination, and provide a complete final closed-shell orbital table. The gap comes from that table's LUMO minus HOMO in eV, not an optical excitation.

One validation invocation makes at most one ORCA attempt per selected molecule, with no retries. `attempt.json` records `qm_calls_attempted=1` even when that attempt fails. Rejected inputs make no ORCA call. The file describes the latest invocation, not lifetime accounting; the orchestrator owns cumulative budget accounting. Extra conformers never generate hidden QM calls.

## Supported scope and checks

Only connected neutral closed-shell molecules, `homo_lumo_gap` in eV, and the ORCA validation backend are supported. TADF, PySCF, charged/open-shell systems, multiple-conformer aggregation, automatic retries, and cluster scheduling remain out of scope. The generator, curator, and orchestrator are separate work, so this is not a claim that the complete CLI agent runs yet.

Run `python -m pytest -q tests subprojects/property_validation_v1/tests` from the repository root. Adapter tests use real RDKit force-field sampling and simulated xTB/ORCA output/process failures. Actual binary output compatibility and chemistry must still be checked on a configured machine with xTB and ORCA; offline tests do not establish scientific accuracy.
