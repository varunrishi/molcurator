# Tech Stack

## Agent layer

| Component | Choice | Role |
|-----------|--------|------|
| Orchestrator | [LangGraph](https://github.com/langchain-ai/langgraph) | Stateful agent graph; routes between tools and holds the loop state |
| Reasoning model | Qwen3 4B (small language model) | Plans the next step, picks tools, interprets results |

## Tools

| Tool | Libraries | Notes |
|------|-----------|-------|
| GENERATE | [RDKit](https://www.rdkit.org/), Mol2Mol via [REINVENT4](https://github.com/MolecularAI/REINVENT4), or [STONED SELFIES](https://github.com/the-matter-lab/stoned-selfies) | Seed-based generation of candidate SMILES; RDKit for sanitisation and deduplication |
| PREDICT | RDKit (3D embedding), xTB | SMILES → 3D geometry → xTB optimisation → property extraction (e.g. HOMO-LUMO gap) |
| TRAIN | [ChemProp](https://github.com/chemprop/chemprop) | Property model trained on the growing dataset; uncertainty estimates (e.g. ensembles) drive the selection for validation |
| VALIDATE | [PySCF](https://pyscf.org/) or [ORCA](https://www.faccts.de/orca/) | Higher-accuracy QM (DFT / TD-DFT for S1 and T1 energies) |
| CURATE | Python data layer (e.g. pandas, CSV/JSON + XYZ files) | Stores SMILES, structure and properties for each level of theory |
| EVALUATE | Custom pipeline over LangGraph traces | Scores agent trajectories and tool-call correctness |

## Language and environment

- Python 3.10+
- Conda / mamba environment recommended (RDKit, xTB and PySCF are easiest to install from conda-forge)
- ORCA is optional and installed separately (needs a licence)

## Data model (curated entry)

- `smiles`: canonical SMILES
- `structure`: optimised 3D geometry (XYZ)
- `properties`: per-method values, e.g. `{ "chemprop": ..., "xtb": ..., "dft": ... }`, with the uncertainty where available
- `provenance`: seed molecule, generator and agent step that produced it

## References

- REINVENT4 / Mol2Mol: https://github.com/MolecularAI/REINVENT4
- STONED SELFIES: https://github.com/the-matter-lab/stoned-selfies
- ChemProp: https://github.com/chemprop/chemprop
