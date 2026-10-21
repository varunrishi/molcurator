# Using the chemistry tools in the MolCurator agent

The shared PREDICT/VALIDATE contracts remain unchanged. `molcurator_property_validation.tools.chemistry.run_chemistry_round` now provides a configured, callable chemistry stage: predict -> calibrated selection -> reference validation -> prepared CuratedEntry records. It can be called from a future graph node; it does not implement the full LangGraph agent, generator, or persistent CURATE.

## Setup and supported config

Use the isolated subproject environment described in [README.md](../README.md), with Python 3.11+ and its dependencies and exported `XTB_BIN`/`ORCA_BIN` executable paths. Adapters read process environment variables rather than loading `.env`. Run real calculations on an allocated compute node. See [the cluster guide](../CLUSTER.md).

Load `configs/homo_lumo_calibrated.yaml` for the opt-in configuration: HOMO–LUMO gap in eV, B3LYP/def2-SVP, an exploratory 0.75 eV calibrated band, and a 20-slot QM budget. Existing use-case configs and shared defaults are unchanged. The stage respects `config.screening.margin`; using the original 0.2 eV config does not silently widen it. This is a ranking/exploration band, never a hard rejection threshold.

The stage supports connected neutral closed-shell molecules and frozen GFN2-xTB -> ORCA B3LYP/def2-SVP gap calibration. It rejects other targets, units and reference methods before chemistry. TADF, PBE0-calibrated ranking and PySCF are not supplied by this stage.

## Call from a node or Python workflow

```python
from pathlib import Path
from molcurator.config import load_config
from molcurator.schemas import Candidate
from molcurator_property_validation.tools.chemistry import run_chemistry_round

config = load_config("configs/homo_lumo_calibrated.yaml")
candidates = [Candidate(id="r1-c001", smiles="CCO", parent_smiles="CCO",
                        round=1, generator="manual")]
result = run_chemistry_round(
    candidates, config, Path("data/runs/my-run"),
    qm_calls_used=0, exploration_slots=1,
)
# result['predictions']: original ordered Prediction objects, failures included
# result['ranking']: calibrated metadata; Prediction.value remains raw xTB
# result['qm_results']: ordered QMResult objects for the chosen batch
# result['curated_entries']: reference-target hits ready for a future CURATE
# result['qm_calls_charged']: conservative reserved QM slots, including failures
# result['stage_path']: persisted evidence for this round
# result['geometry_reports']: FF metadata, including sampled-set Boltzmann weights
```

The default rule prioritizes calibrated distance and reserves up to `exploration_slots` candidates outside the band, while keeping at least one priority slot. Sampling is deterministic from `config.rng_seed + round`. A one-slot batch has no separate exploration slot. All successful predictions remain eligible; none are discarded solely because their calibrated distance exceeds the margin. Zero remaining QM capacity runs prediction but performs no validation.

Candidates must have unique IDs and belong to a single configured round. The stage refuses to overwrite an existing round directory: it cannot silently repeat calculations on resume. Give distinct runs distinct run directories.

## Let the agent choose the QM batch

Pass a callback to receive ranking records and remaining capacity *after PREDICT*, without repeating prediction:

```python
# Called inside the same chemistry-stage invocation:
def choose_qm(ranking, remaining):
    # In the real graph, build the compact LLM view and validate its decision here.
    # This example is only the deterministic closest-first fallback.
    usable = [r for r in ranking if r['status'] == 'ok' and r['xyz_path']]
    return [r['candidate_id'] for r in usable[:remaining]]

# result = run_chemistry_round(candidates, config, run_dir,
#     qm_calls_used=state_qm_calls, select_qm=choose_qm)
```

Returned IDs must be unique successful predictions with geometries. Unknown, duplicate or failed IDs raise before QM dispatch. Oversized valid batches are trimmed in the requested order and the original size is recorded. Supplying a callback replaces the automatic exploration fallback, so the agent's policy must retain its intended exploration allocation. `selected_ids=[...]` is also accepted for a prechosen batch; do not combine it with a callback.

The existing graph specification includes a raw-xTB hard screen. Integrating this calibrated stage requires replacing that screen, not inserting ranking after it: otherwise candidates can be lost before calibration. This branch provides the stage and preserves current contracts; the graph maintainer must approve and implement its routing/selection policy. Do not call PREDICT/VALIDATE again around this all-in-one stage.

## Budgets, errors and state

Before calling, pass the run's cumulative `qm_calls_used`. The stage enforces `max_qm_calls` for this reservation and rejects candidate rounds beyond `max_rounds`. It writes selected IDs and `qm_calls_charged` *before* calling VALIDATE. Treat that value as a conservative debit, not a count of successful calculations. An input rejected by the underlying validator may launch no external process but still consume a reservation.

After a successful return, accumulate the debit in run state. If the stage raises after reservation, read `stage.json` and preserve its debit and failures before retrying. Per-calculation `attempt.json` describes only the latest invocation; neither file is a cross-run ledger. The graph owns cumulative state, concurrency control, checkpoints, cache reuse, whole-run wall-time enforcement, and stopping when dataset size is reached. This synchronous stage does not implement LangGraph interrupts or resume; human approval belongs in the selector callback or an independently managed staged graph.

Whole-tool exceptions or ID/order contract violations persist failed stage evidence and re-raise for the graph's error route. Per-molecule tool failures remain normal records. No hidden QM retries are performed. The stage checks returned reference method labels and finite successful values.

## Curating and reporting

The stage accepts only successful reference values within `config.target` bounds. It joins Candidate/Prediction/QMResult by ID and constructs shared CuratedEntry records with:

- original candidate SMILES and xTB geometry;
- `properties={'xtb': raw_prediction, 'dft:B3LYP/def2-SVP': actual_reference}`;
- parent/generator/round/seed provenance and a stage evidence path.

Calibrated estimates remain in ranking metadata, not under the reference-method property key. The root `curate()` still raises `NotImplementedError`; the caller must implement/use persistent idempotent storage before a complete agent run can save these entries as its dataset. Existing research CSV exports are separate utilities.

The immutable round directory is `run_dir/chemistry/round-N/`. It contains `stage.json`, a config snapshot, candidates, predictions, ranking/selection, failures, reserved QM debit, reference results, prepared entries and FF geometry report metadata. Actual geometries and raw logs are under its `xyz/` directory:

- `<id>.xyz`: optimized geometry returned in Prediction.
- `calculations/<id>/xtb/geometry_report.json` and `.md`: force field, selected energy, unique sampled minima, FF Boltzmann weight at 298.15 K.
- `calculations/<id>/xtb/xtb.out`: raw optimization/property output.
- `calculations/<id>/orca/gap.inp`, `orca.out`, `attempt.json`: reference input/output and latest attempt.

Have the agent summary use `geometry_reports` and link the stage evidence. The weight is conditional on sampled FF minima, not an experimental or QM ensemble population. ORCA performs a ground-state single point at the xTB geometry; this stage does not calculate fluorescence or S1–T1 gaps.

## Offline agent development

`ChemistryTools` supports dependency injection, so the team can test nodes without binaries:

```python
from tests.agent.fakes import FakeTools
from molcurator_property_validation.tools.chemistry import ChemistryTools
fake = FakeTools()
tool_bindings = ChemistryTools(predict=fake.predict, validate=fake.validate)
# result = run_chemistry_round(candidates, config, run_dir,
#     qm_calls_used=0, tools=tool_bindings)
```

Tests cover the config, fake/real bindings, budget exhaustion, callback trimming/validation, failed QM debits, per-molecule errors, order-contract checks, reference-target acceptance, and overwrite prevention. Fake outputs are test fixtures; never use them as scientific data.
