# Generated candidates

Output of GENERATE, not committed-by-hand data. Regenerate by running the tool on the seeds
in `data/seeds/`.

| File | What it is |
| --- | --- |
| `candidates_round1.csv` | 1000 candidates: 100 from each of the 10 seeds in `data/seeds/homo_lumo.csv` |

Columns: `id`, `smiles`, `parent_smiles`, `parent_mol_id` (the seed's QM9 id), `round`,
`generator`, `heavy_atoms`. Ids are prefixed `s01`-`s10` by seed, because `generate()`
numbers candidates per call and it was called once per seed to guarantee 100 each.

Settings: `GenerationSettings(n_candidates=100, mutation_strength=2)`, `round=1`,
`rng_seed=0`. Deterministic: the same seeds and code give byte-identical output.

**Requires the ring-preservation rule in `tools/generate.py`** (branch `tools/generate`).
Generated on `main` without it, the candidates differ sharply: 15% aromatic instead of 90%.

Of these 1000: 947 unique SMILES (a few are reachable from two different seeds), 90% contain
an aromatic ring, 92% would pass the chemical filter used to select the seeds themselves.
