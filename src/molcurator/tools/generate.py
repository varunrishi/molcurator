# GENERATE: create new candidate molecules from a seed molecule.
#
# Backends:
#   - STONED SELFIES (default): random SELFIES mutations and interpolation around the seed
#   - Mol2Mol (REINVENT4, optional): pretrained model that samples similar molecules
# Output: list of Candidate (schemas.py), sanitised and deduplicated with RDKit.
from molcurator.schemas import Candidate, GenerationSettings


def generate(parents: list[str], settings: GenerationSettings, round: int, rng_seed: int) -> list[Candidate]:
    """Generate new candidate molecules from the parent SMILES (contract: Phase 2 plan, R2.2).

    Must return canonical SMILES, ids unique within the run (e.g. "r{round}-c{index:03d}"),
    and only RDKit-valid molecules; invalid ones are dropped before returning. The same
    inputs and rng_seed must give the same output.
    """
    raise NotImplementedError("generate() is built in Phase 1 (tools); use FakeToolset in tests")
