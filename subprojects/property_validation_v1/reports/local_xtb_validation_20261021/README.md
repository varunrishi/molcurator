# Local xTB validation and pre-validation gate

21 October 2026. Tool branch: `tools/property-batch-reports-slurm`. Main is unchanged. No new PR was created for these experiments; updates to this existing branch appear in PR 15.

## Policy update: single-geometry fallback

After the original tests below, an empty conformer ensemble was changed to reuse an available geometry or attempt a single ETKDG embedding with random coordinates. This geometry is MMFF94 optimized before electronic work. A SMILES-only input does not contain original 3D coordinates. If both ensemble and single embedding fail, the molecule still fails safely. The original 336-molecule numerical results below remain historical evidence; they are not a new real-xTB test of the fallback. See `pytest_single_geometry_fallback.txt` for the updated full-suite result. Tests explicitly exercise successful single embedding, existing-geometry reuse and failure of both paths. A weight of 1 describes the single sampled minimum only.

## Original preparation-gate verification

A molecule with no embedded conformers, no converged MMFF94 minima, or no valid exported XYZ returns a failed prediction with its original ID. It cannot launch xTB; passing that failed prediction to VALIDATE cannot launch ORCA. Other molecules in the batch continue. Charges, radicals, disconnected structures and unavailable MMFF94 parameters are reported separately. Stale published XYZ is removed before a retry.

See [usage and output documentation](../../docs/BATCH_REPORTS_AND_SLURM.md#pre-validation-stop-the-failed-molecule-before-electronic-work) and [pre-validation tests](../../tests/test_prevalidation.py).

## Verification

| Check | Result |
| --- | --- |
| Full repository and subproject suite | **142 passed**, 31.49 s |
| Real xTB baseline | **336/336 successful**, IDs preserved |
| Replay through the new preparation gate | **336/336 passed**, identical IDs/status/gap values |
| Electronic launches during gate replay | **0**, with **336 cache hits** |
| Fresh deterministic repeat | 24/24 identical gap values |
| Controlled empty conformers / embedding exception / no converged minima | Failed before electronic launch |
| Controlled empty/malformed/nonfinite XYZ / export exception / write failure | Failed before electronic launch |
| Mixed failed then valid molecule | Failed molecule retained; valid molecule processed |
| Real xTB timeout, unavailable executable, corrupt-cache recovery | Exercised; details in analysis tables |
| ORCA / live SLURM | Not executed locally |

The final command, with local dependencies installed, was:

```bash
python -m pytest -q tests subprojects/property_validation_v1/tests
```

[pytest.txt](pytest.txt) records the result. [post_prevalidation_checks.json](post_prevalidation_checks.json) records the full replay, negative-control reasons and implementation hashes. The mixed negative-control batch exits 1 intentionally because it includes failed molecules; this is not a test failure.

## Scientific analysis

[Read the detailed report](analysis_report.md), inspect [CSV tables](tables/), [plots](plots/), [statistics](statistics.json), and [resolved experiment configurations](configs/).

Fourteen experiments completed in 473.3 s before the final gate replay. The 336-molecule baseline used ETKDGv3, 30 conformers, seed 42, converged MMFF94 minima and a GFN2-xTB single point on the lowest-energy selected geometry. An explicit plotting request generated the nine analysis figures. Ordinary CLI runs keep visualizations off by default (`--plots` enables them).

Against historical labels, Pearson r was 0.927 for 60 B3LYP/def2-SVP entries and 0.793 for 276 PBE0/def2-SVP entries. Mean absolute differences were 2.558 and 2.935 eV respectively. These compare different calculation protocols; they are not experimental accuracy estimates. The PBE0 convergence statuses are unknown. No ORCA was run, and no correction or ML model was fitted. Conformer seed changes shifted individual gaps by up to 0.415 eV in the tested subset.

The curated input contains neutral closed-shell structures. It does not reproduce the colleague's 42 suspected radicals and 8 embedding failures without those exact SMILES. Empty-conformer and XYZ failures were explicitly injected in unit tests; the negative-control batch also checks actual RDKit charge/radical detection.

## Provenance and reuse

[provenance.json](provenance.json) identifies the input, Python/RDKit versions, xTB executable hash and source hashes for the initial experiments. Those experiments preceded the preparation-record addition; the subsequent full replay verifies the added gate without changing numerical results. Both phases are retained separately. Configurations contain no installation-specific paths. Binaries, temporary calculation logs and workstation environments are excluded from Git.

For a new dataset, install the tool and xTB as documented, then:

```bash
molcurator-properties run generated.csv --out new-results
molcurator-properties run generated.csv --out new-results --resume
molcurator-properties report new-results --plots
```

Input CSV requires `id,smiles`. Use a new output directory for the first run. Inspect `summary.csv`, failures and preparation records before choosing successful candidates for ORCA. Full restart cache checks validate stored calculation evidence; a preparation failure never counts as an expensive calculation.
