# Seed molecules

Starting molecules for round 1, one CSV per use case. This folder is committed.

| File | Use case | Seeds |
| --- | --- | --- |
| `homo_lumo.csv` | 1: HOMO-LUMO gap in a target window | 10, selected from QM9 |
| *(none yet)* | 2: TADF, S1-T1 gap near zero | QM9 has no S1-T1 labels, so a different source is needed |

`homo_lumo.csv` columns: `smiles`, `mol_id` (the QM9 id, so the label can be traced back),
`qm9_dft_gap_ev`, `heavy_atoms`, `murcko_scaffold`, `source`.

**These seeds already have the target property** - that is the point of selecting from a
labelled dataset. `notebooks/qm9_eda.ipynb` is the selection: it filters QM9 and picks the
10, and re-running it rewrites this CSV.

Selection, in short: molecules whose QM9 DFT gap lies in the target window, minus
zwitterions, exocyclic-imine tautomers, alpha-diketones, three-membered rings, acyclic
molecules and anything `chem.convert.is_implausible` rejects; then two per 0.2 eV bin, each
a different Murcko scaffold, taking the most common scaffolds and the medoid molecule of
each. The `configs/*.yaml` seed lists are **not** updated automatically and must be kept in
step by hand.

## QM9 (`qm9.csv`, 28 MB, gitignored)

The pool that seeds are selected from. Not committed - re-fetch it with:

```sh
curl -L -o data/seeds/qm9.csv \
  https://deepchemdata.s3.us-west-1.amazonaws.com/datasets/qm9.csv
```

`molcurator seeds` downloads it there on first use, and suggests seeds from it for any QM9
property when you have no seed of your own:

```sh
molcurator seeds --property gap --min 3.0 --max 3.5 --n 5    # gap/homo/lumo in eV
molcurator seeds --property mu --min 5 --out my_seeds.csv     # dipole (D), one-sided
```

It applies the same filter and spread-across-the-window selection as the notebook
(`src/molcurator/chem/qm9.py`), one seed per equal-width bin of the window.

That URL is DeepChem's public MoleculeNet mirror. The dataset itself is Ramakrishnan, Dral,
Rupp & von Lilienfeld, *Scientific Data* **1**, 140022 (2014) - the GDB-9 subset, on
figshare. Cite the paper; the URL is only the access route. On download it had 133,885 rows
(the published QM9 size) and the documented columns, but **no checksum was verified**.

Columns used: `mol_id`, `smiles`, `gap`. **`gap` is in Hartree** - multiply by 27.211386 for
eV. QM9 gaps are B3LYP/6-31G(2df,p), *not* the B3LYP/def2-SVP of `configs/homo_lumo.yaml`,
so the two differ slightly.

Gap distribution (eV): median 6.79, with 181 molecules in the 3.0-3.5 eV target window, 833
in 3.5-4.0 and 9,009 in 4.0-5.0. The target window is in the lower tail, and roughly half of
it is zwitterions (`[NH3+]`, `[O-]`); after dropping those and anything `tools/generate.py`
cannot process, about 90 usable seed candidates remain.

| File | Use case | Target |
| --- | --- | --- |
| `homo_lumo.csv` | 1 | HOMO-LUMO gap in 3.0-3.5 eV |
| `tadf.csv` | 2 | S1-T1 gap near zero (inverted gaps count) |

The `seeds:` list in `configs/homo_lumo.yaml` and `configs/tadf.yaml` must match the
`smiles` column here. `RunConfig.seeds` takes SMILES inline, so the two can drift; a
`seeds_file` config option would remove the duplication.

## Size constraint

`MAX_HEAVY_ATOMS = 15` in `tools/generate.py`, and candidates must stay within 0.5-1.5x
their parent's heavy-atom count. Seeds are therefore 9-14 heavy atoms: large enough to carry
the right chemistry, small enough that GENERATE can still grow them.

This rules out real TADF emitters, which are 50+ heavy atoms (4CzIPN and similar). The use
case 2 seeds are small charge-transfer chromophores and INVEST cores instead - the closest
proxies that fit the cap.

## Provenance

These molecules were **proposed from general chemistry knowledge, not taken from a database
or a specific paper.** What has and has not been checked:

- **Verified by script:** every SMILES parses in RDKit, is a canonical fixed point,
  round-trips through SELFIES, passes `chem.convert.is_implausible`, and respects the
  heavy-atom cap.
- **Not verified:** the property claims in the `rationale` column. No gap has been computed
  or looked up. Heptazine's inverted singlet-triplet gap is a well-known computational
  result; 3-aminophthalimide's delayed fluorescence is the least certain claim here.

Replace any of these with literature or database molecules (e.g. QM9, which ships DFT
HOMO-LUMO gaps) when a better-grounded set is available.

## A caveat on use case 1

B3LYP/def2-SVP HOMO-LUMO gaps for aromatics this small mostly land **above** 3.5 eV
(benzene ~6.5 eV, naphthalene ~4.8 eV). These seeds bracket the 3.0-3.5 eV window from both
sides, but if early runs return almost no hits, widen the window before concluding that
GENERATE is at fault.
