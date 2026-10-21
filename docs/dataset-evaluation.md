# Standalone dataset evaluation

The evaluator reads saved records and produces a JSON report plus a CSV with one
row per input molecule. It does not call xTB, ORCA, ML models, an LLM, or the agent.
It never changes the input dataset. Output files must be new and their parent
directories must already exist. Exit 0 means evaluation completed, not that the
dataset passed every quality check; invalid arguments/files exit 2.

## Usage

From the repository root in a Python environment with RDKit and Pydantic 2:

```bash
python scripts/evaluate_dataset.py \
  subprojects/property_validation_v1/molcurator_properties_for_collaborators.csv \
  --format csv --min 3 --max 3.5 --qm-method dft:B3LYP/def2-SVP \
  --json-out evaluation.json --csv-out evaluation-molecules.csv
```

Add repeatable `--seed 'SMILES'` options only when the actual input seeds are
known. Configuration seeds in this repository are placeholders; seeds are never
inferred from a candidate's similarity or parent. Missing seeds yield null overlap
metrics. The evaluator accepts `--property` and `--units` but only supports
`homo_lumo_gap` / `eV`; other combinations retain structural results and mark QM
assessment unsupported. Bounds are inclusive and may be one-sided.

For curated records, supply serialized QMResult evidence separately:

```bash
python scripts/evaluate_dataset.py dataset.jsonl --format jsonl \
  --qm-results qm-results.jsonl --seed 'CCO' \
  --min 3 --max 3.5 --qm-method dft:B3LYP/def2-SVP \
  --json-out evaluation.json --csv-out evaluation-molecules.csv
```

Optional `--artifact-root RUN_DIRECTORY` checks whether recorded XYZ paths exist
(relative to that directory, or absolute as recorded). It does not validate XYZ
contents or establish that geometry belongs to the SMILES. Without an artifact
root, existence is unknown. No paths from `source_csv` are followed.

## Input profiles

`csv` explicitly means the collaborator exchange format, not arbitrary CSV.
Required columns: `dataset,candidate_id,smiles,qm_method,status,orca_gap_ev`.
Other columns are preserved in the source dataset but are not copied wholesale
into reports. Identity is `(dataset,candidate_id)`. Blanks are missing, never zero.
Only the selected method is assessed; B3LYP and PBE0 labels are not pooled.
`status=ok` is reported success only: the evaluator does not independently verify
raw calculation logs. Exported `true_hit` and calibration fields are not trusted
as target evidence. Historical blank status remains unassessable.

`jsonl` means one CuratedEntry-shaped object per nonblank line:

```json
{"id":"a","smiles":"CCO","xyz_path":null,"properties":{"dft:B3LYP/def2-SVP":3.25},"validated":true,"provenance":{"seed":"C","parent":"CC","generator":"stoned_selfies","round":"1"}}
```

The optional QM sidecar also contains one object per line:

```json
{"candidate_id":"a","status":"ok","value":3.25,"error":null,"method":"dft:B3LYP/def2-SVP"}
```

The input target supplies property/units semantics because CuratedEntry and
QMResult do not encode them. Do not mix different target properties in these
files. JSONL QM assessment requires a matching successful result, a true validated
flag and an identical finite value under the selected method in `properties`.
ML-only records remain valid input; they are not QM-confirmed. A validated flag
alone is insufficient. Multiple matching sidecar results are ambiguous, including
repeated identical results; select an authoritative result before export rather
than letting the evaluator choose a favorable attempt. Orphan sidecar IDs are
reported. CSV cannot be joined to this ID-only sidecar.

Malformed file syntax is a fatal input error with location information. Missing or
invalid molecular and evidence fields remain report rows with reasons. Duplicate
IDs never overwrite rows: ambiguous identities are excluded from QM assessment.

## Interpretation

- Structural validity uses the existing molecular audit utility's RDKit parse and
  sanitization checks. It does not establish synthesizability, conformer quality,
  or compatibility with the predictor's neutral closed-shell restrictions.
- Exact uniqueness retains stereochemistry; stereo-free uniqueness collapses it.
  Both count all valid molecules, including seeds. Duplicate references use
  1-based input row numbers. This avoids the audit summary's seed-first partition
  suppressing repeated seed molecules. No tautomer/salt normalization or scaffold
  novelty claim is made. Structural counts cover the whole input, across cohorts.
- Seed overlap compares every supplied seed, exact and ignoring stereo. Maximum
  Morgan Tanimoto is descriptive similarity, not a novelty guarantee.
- Provenance checks field completeness, not authenticity. CSV expects dataset,
  candidate ID, QM/reference method and source CSV. JSONL expects seed (or the
  orchestrator's `seeds` alias), parent,
  generator and round strings. Geometry-path/policy availability is separate;
  ML-only records do not require geometry. Missing provenance does not silently
  turn an otherwise assessable QM number into a failed numerical target check.
- QM outcomes are `meets_target`, `outside_target`, or `not_assessable`. Reasons
  distinguish missing evidence, failed/unknown status, wrong method, invalid
  molecules, conflicts, and unsupported semantics. Nonfinite or negative gaps
  cannot qualify. Raw logs are never claimed as verified.
- Validity = valid rows / total rows. QM coverage = assessable rows / total rows.
  QM hit rate = qualifying rows / assessable rows. Every rate includes its
  numerator/denominator; zero denominators yield null. Unique qualifying counts
  prevent repeated molecules from inflating the apparent benchmark size.

JSON includes report version, source byte hashes, parameters, RDKit version,
summary and per-row findings. Hashes refer to actual local bytes; Windows CRLF
conversion may differ from metadata hashes of committed LF content. CSV contains
the same row findings; list fields are JSON strings and null scalar fields are
blank. Reports contain no timestamp, so identical inputs/parameters are deterministic.

## Tests and scope

```bash
python -m pytest tests/test_dataset_evaluation.py tests/test_evaluate_dataset_cli.py -q
```

Only RDKit, Pydantic 2 and pytest are needed for these tests. Use the existing
project environment or a separate virtual environment with those dependencies;
no full ML/agent installation or external chemistry executable is needed.

Production CURATE persistence is still unfinished. JSONL follows the shared model
and fake curator convention, not a promise about a future writer. Agent traces,
budget compliance, model accuracy/calibration and screening recall are outside
this evaluator. Reliable recall requires reference labels for rejected candidates.
Sampling weights and population inference are not implemented. Raw-log and
geometry-content verification may be added separately once artifacts are supplied.
