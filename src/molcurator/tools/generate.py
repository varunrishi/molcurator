# GENERATE: create new candidate molecules from a seed molecule.
#
# Backends:
#   - STONED SELFIES (default): random SELFIES mutations and interpolation around the seed
#   - Mol2Mol (REINVENT4, optional): pretrained model that samples similar molecules
# Output: list of Candidate (schemas.py), sanitised and deduplicated with RDKit.
import random

from molcurator.chem import stoned
from molcurator.chem.convert import (
    canonical_smiles,
    heavy_atom_count,
    is_implausible,
    selfies_to_smiles,
    smiles_to_selfies,
)
from molcurator.schemas import Candidate, GenerationSettings

STONED = "stoned_selfies"
SIZE_RANGE = (0.5, 1.5)  # candidate heavy-atom count relative to its parent; drops fragments and runaway growth
MAX_HEAVY_ATOMS = 15  # absolute cap: keeps candidates cheap enough for xTB and QM validation
ATTEMPTS_PER_CANDIDATE = 30  # give up on a round that keeps producing repeats or invalid molecules


def generate(parents: list[str], settings: GenerationSettings, round: int, rng_seed: int) -> list[Candidate]:
    """Generate new candidate molecules from the parent SMILES (contract: Phase 2 plan, R2.2).

    Must return canonical SMILES, ids unique within the run (e.g. "r{round}-c{index:03d}"),
    and only RDKit-valid molecules; invalid ones are dropped before returning. The same
    inputs and rng_seed must give the same output.

    May return fewer than settings.n_candidates when the neighbourhood of the parents is
    exhausted. Parents themselves are never returned, and candidates much smaller or larger than
    their parent are dropped, as are candidates above MAX_HEAVY_ATOMS and strained motifs
    (see chem.convert.is_implausible).
    """
    if settings.generator != STONED:
        raise ValueError(f"unsupported generator {settings.generator!r}; only {STONED!r} is built")
    parent_tokens = {}
    for p in parents:
        tokens = smiles_to_selfies(p)
        canon = canonical_smiles(p)
        if tokens is None or canon is None:
            raise ValueError(f"parent is not a valid molecule: {p!r}")
        parent_tokens[canon] = tokens
    if not parent_tokens:
        raise ValueError("generate needs at least one parent")

    rng = random.Random(f"generate-{rng_seed}-{round}")  # same inputs -> same output
    # Edits draw on tokens from the parents plus the semantically robust SELFIES alphabet.
    alphabet = stoned.alphabet(*parent_tokens.values())
    parent_list = sorted(parent_tokens)  # sorted: dict order must not depend on input order

    seen = set(parent_list)
    out: list[Candidate] = []
    for _ in range(settings.n_candidates * ATTEMPTS_PER_CANDIDATE):
        if len(out) == settings.n_candidates:
            break
        parent = rng.choice(parent_list)
        tokens = parent_tokens[parent]
        if len(parent_list) > 1 and rng.random() < 0.3:
            tokens = stoned.crossover(tokens, parent_tokens[rng.choice(parent_list)], rng)
        smiles = selfies_to_smiles(stoned.mutate(tokens, alphabet, settings.mutation_strength, rng))
        if smiles is None or smiles in seen:
            continue
        low, high = (f * heavy_atom_count(parent) for f in SIZE_RANGE)
        high = min(high, MAX_HEAVY_ATOMS)
        if not low <= heavy_atom_count(smiles) <= high or is_implausible(smiles):
            continue
        seen.add(smiles)
        out.append(Candidate(id=f"r{round}-c{len(out):03d}", smiles=smiles, parent_smiles=parent,
                             round=round, generator=settings.generator))
    return out
