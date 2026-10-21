# Using the chemistry tools in the MolCurator agent

This branch implements the `v0.1-contract` PREDICT/VALIDATE signatures and a separate calibrated-ranking utility. Agent graph/CLI integration remains to be implemented. The example below is a usable chemistry-stage helper, not a replacement orchestrator.

## Environment

Install the checkout's dependencies (`uv sync --locked` on the cluster), export `XTB_BIN` and `ORCA_BIN` as executable paths, and load any cluster-required runtime modules. The adapters read process environment variables; they do not load `.env` themselves. `MOLCURATOR_QC_TIMEOUT_S` defaults to 600 seconds per external process. Execute real chemistry on an allocated compute node.

The smoke runner also supports an existing Python 3.11+ environment containing RDKit and Pydantic v2. See [CLUSTER.md](../subprojects/property_validation_v1/CLUSTER.md). Optional viewers are off by default and require py3Dmol/browser JavaScript when enabled.

## Callable chemistry stage

Pass unique, filesystem-safe Candidate IDs and canonical SMILES from the generator. This example allocates one exploration slot outside the provisional band when there are at least two available QM slots and an outside-band molecule. Selection uses a seeded random draw; all other slots are filled by calibrated distance. The team should review this illustrative policy before adopting it in the graph.

```python
import random
from pathlib import Path

from molcurator.schemas import Candidate, PropertyTarget, QMSettings, Status
from molcurator.screening import GapCalibration, ranked_predictions
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate


def chemistry_step(candidates, target, qm, xyz_dir, remaining_qm_calls, seed=0):
    if remaining_qm_calls < 0:
        raise ValueError("remaining QM budget cannot be negative")
    calibration = GapCalibration()
    method = f"dft:{qm.functional}/{qm.basis}"
    if qm.backend != "orca" or method != calibration.qm_method:
        raise ValueError("this calibration requires ORCA B3LYP/def2-SVP")

    predictions = predict(candidates, target, xyz_dir)
    ranking = ranked_predictions(predictions, target, calibration, margin_ev=0.75)
    by_id = {p.candidate_id: p for p in predictions}
    eligible = [r for r in ranking if r["status"] == "ok"
                and by_id[r["candidate_id"]].xyz_path is not None]
    slots = min(remaining_qm_calls, len(eligible))
    outside = [r for r in eligible if not r["selected"]]
    exploration = random.Random(seed).sample(outside, 1) if slots >= 2 and outside else []
    exploration_ids = {r["candidate_id"] for r in exploration}
    prioritized = [r for r in eligible if r["candidate_id"] not in exploration_ids]
    chosen = prioritized[:slots - len(exploration)] + exploration
    batch = [by_id[r["candidate_id"]] for r in chosen]
    qm_results = validate(batch, target, qm)
    hits = [r for r in qm_results if r.status is Status.ok
            and (target.min is None or r.value >= target.min)
            and (target.max is None or r.value <= target.max)]
    return {
        "predictions": predictions, "ranking": ranking,
        "qm_batch_ids": [p.candidate_id for p in batch],
        "qm_slots_reserved": len(batch), "qm_results": qm_results, "hits": hits,
    }


# Call on a compute node; creates real xTB/ORCA calculations.
# candidates = [Candidate(id="r1-c001", smiles="CCO", parent_smiles="CCO",
#                         round=1, generator="manual")]
# result = chemistry_step(
#     candidates, PropertyTarget(name="homo_lumo_gap", min=3.0, max=3.5),
#     QMSettings(backend="orca", functional="B3LYP", basis="def2-SVP"),
#     Path("data/runs/example/xyz"), remaining_qm_calls=2, seed=0)
```

A budget of zero launches no QM calls (the example still performs xTB prediction). With one QM slot the example prioritizes rather than reserving exploration; the agent should schedule exploration across rounds or use a larger batch. `selected=False` is not a rejection: those molecules remain eligible for the ranking fallback and exploration.

## Responsibilities of the graph

- Inject/call the plain tool functions at the PREDICT and VALIDATE nodes. They need no LLM wrapper to run. Future Toolset wiring can bind these same signatures.
- Replace the proposed raw-xTB hard screening filter when using calibrated selection. Do not discard raw gaps outside the DFT target window before ranking. Keep original prediction values and failures in state.
- Validate the run's property, units and QM method before execution. Calibrated ranking supports `homo_lumo_gap` in eV and its frozen B3LYP method only; it does not itself compare `QMSettings`.
- Enforce round/wall-time/QM budgets and reserve capacity before dispatch. The helper's `qm_slots_reserved` is a conservative batch reservation, not an audited count of successful or actually launched calculations. Debit failed attempts too. Never increment a budget using only successful results.
- Reconcile each calculation's `attempt.json` with the reservation. The file describes the latest validation invocation; it is not a cumulative ledger. Persist attempt records in the run trace/state, especially across retries and resume.
- The tools return one result per input in input order, with original candidate IDs. Failed predictions must remain in the run record, but do not need to be sent to VALIDATE. Invalid input to VALIDATE also returns a failed QMResult.
- Record selection reasons, calibration name/method, random seed, batch IDs and any trimmed batch. Choosing a fresh output directory per run avoids confusing artifacts from unrelated runs.

## Creating entries for CURATE

Accept target hits using successful reference `QMResult.value`, never the calibrated prediction. Join Candidate, Prediction and QMResult by candidate ID to construct each shared CuratedEntry:

- `id` and `smiles`: the original candidate identity.
- `xyz_path`: the successful xTB Prediction geometry.
- `properties`: `{"xtb": prediction.value, qm_result.method: qm_result.value}` for the current single target. Store calibrated estimates under explicit metadata, not the reference-method key.
- `provenance`: seed/parent, generator, round, and references to method settings and geometry reports (the current schema accepts string values).

The root `curate()` function still raises `NotImplementedError`. A real agent must implement persistent idempotent storage before calling it. Existing CSV export utilities provide research exports; they do not silently supply that missing tool. The current property map also needs an agreed extension before mixing several property types into one entry.

## Result artifacts and reporting

Under the supplied `xyz_dir`:

- `<id>.xyz`: optimized geometry returned to the graph.
- `calculations/<id>/xtb/geometry_report.json` and `.md`: FF method/energy, selected conformer, sampled-set Boltzmann weight at 298.15 K.
- `calculations/<id>/xtb/xtb.out`: raw optimization/property output.
- `calculations/<id>/orca/gap.inp`, `orca.out`, `attempt.json`: configured QM input, output and latest attempt status.

Have the agent summary link these artifacts and include the selected FF weight and its sampled-model qualification. Summary integration is not automatic yet. The adapter returns only the requested gap; full orbital/dipole exports can be generated from logs by the dedicated scripts.

Supported chemistry remains connected neutral closed-shell molecules. ORCA calculations are ground-state single points at xTB geometries; TADF, PySCF fallback, multi-conformer aggregation, automatic retries and cache reuse are not implemented by these adapters.
