# Tests for tools/generate.py: valid, unique, sanitised SMILES from a seed.
import pytest
from rdkit import Chem

from molcurator.chem import stoned
from molcurator.chem.convert import canonical_smiles, is_implausible, ring_profile, selfies_to_smiles
from molcurator.schemas import GenerationSettings
from molcurator.tools.generate import MAX_HEAVY_ATOMS, generate

SEED = "c1ccc2c(c1)[nH]c1ccccc12"  # carbazole, 13 heavy atoms: fits under MAX_HEAVY_ATOMS
OTHER = "c1ccccc1O"  # phenol: a second parent, so crossover is exercised
OVERSIZED = "N#Cc1ccc(-n2c3ccccc3c3ccccc32)cc1"  # 21 heavy atoms, i.e. above the cap
NH_SEED = "Nc1cc2nnoc2[nH]1"  # QM9 seed whose [nH] token gave aminyl radicals in round 1


def test_valid_unique_canonical_and_not_the_parent():
    out = generate([SEED], GenerationSettings(n_candidates=50), round=2, rng_seed=0)
    smiles = [c.smiles for c in out]
    assert len(out) == 50
    assert len(set(smiles)) == 50 and len({c.id for c in out}) == 50
    assert Chem.MolToSmiles(Chem.MolFromSmiles(SEED)) not in smiles
    for c in out:
        assert Chem.MolToSmiles(Chem.MolFromSmiles(c.smiles)) == c.smiles
        assert c.id.startswith("r2-c") and c.round == 2 and c.generator == "stoned_selfies"


def test_same_inputs_same_output_and_seed_matters():
    s = GenerationSettings(n_candidates=20)
    assert generate([SEED], s, 1, 7) == generate([SEED], s, 1, 7)
    assert generate([SEED], s, 1, 7) != generate([SEED], s, 1, 8)


def test_several_parents_are_all_used():
    out = generate([SEED, OTHER], GenerationSettings(n_candidates=60), 1, 0)
    assert {c.parent_smiles for c in out} == {Chem.MolToSmiles(Chem.MolFromSmiles(p)) for p in (SEED, OTHER)}


def test_invalid_parent_and_unknown_generator_raise():
    with pytest.raises(ValueError):
        generate(["not-a-smiles"], GenerationSettings(), 1, 0)
    with pytest.raises(ValueError):
        generate([SEED], GenerationSettings(generator="mol2mol"), 1, 0)


def test_candidates_keep_the_parents_conjugation():
    # Random SELFIES edits readily open a fused aromatic into a chain, which destroys the
    # conjugation the target electronic property depends on. Such candidates are dropped.
    for c in generate([SEED], GenerationSettings(n_candidates=50, mutation_strength=3), 1, 0):
        rings, aromatic = ring_profile(c.smiles)
        assert rings >= 1 and aromatic


def test_an_aliphatic_parent_is_not_required_to_be_aromatic():
    # The rule follows the parent: an aliphatic ring parent only has to keep a ring.
    out = generate(["O=C1CCCCC1"], GenerationSettings(n_candidates=20), 1, 0)
    assert len(out) == 20
    assert all(ring_profile(c.smiles)[0] >= 1 for c in out)
    assert not all(ring_profile(c.smiles)[1] for c in out)  # aromaticity is not forced


def test_candidates_stay_close_in_size_to_the_parent():
    n = Chem.MolFromSmiles(SEED).GetNumHeavyAtoms()
    for c in generate([SEED], GenerationSettings(n_candidates=50, mutation_strength=4), 1, 0):
        assert 0.5 * n <= Chem.MolFromSmiles(c.smiles).GetNumHeavyAtoms() <= 1.5 * n


def test_candidates_are_under_the_absolute_heavy_atom_cap():
    # This parent is itself above the cap, so every candidate has to shrink to meet it.
    assert Chem.MolFromSmiles(OVERSIZED).GetNumHeavyAtoms() > MAX_HEAVY_ATOMS
    out = generate([OVERSIZED], GenerationSettings(n_candidates=50), 1, 0)
    assert len(out) == 50  # the cap must not starve the round
    for c in out:
        assert Chem.MolFromSmiles(c.smiles).GetNumHeavyAtoms() <= MAX_HEAVY_ATOMS


def test_alphabet_is_restricted_but_keeps_the_parents_own_tokens():
    pool = set(stoned.alphabet(["[C]", "[P+1]"]))
    assert "[N]" in pool and "[=Branch1]" in pool  # allowed element, structure token
    assert "[B]" not in pool and "[N+1]" not in pool and "[I]" not in pool
    assert "[P+1]" in pool  # the parent's own token is always allowed


def test_no_strained_motifs_in_output():
    out = generate([SEED], GenerationSettings(n_candidates=80, mutation_strength=4), 1, 0)
    assert not any(is_implausible(c.smiles) for c in out)


@pytest.mark.parametrize("smiles", [
    "C1#CCCCCC1",       # triple bond inside a ring
    "C1CCCCCCCCC1",     # ring above max_ring
    "C=C=C", "CC=C=C=CC", "C=C=O",  # allene, cumulene, ketene
    "c1ccc2c(c1)CC2",   # benzocyclobutene: a 4-membered ring fused onto a benzene
    "[NH]c1nnno1", "N#Cc1nnoc1[NH]",  # aminyl radicals from a stranded [nH] token
    "C1=[SH]C1c1cccs1", "C1=S(c2cccs2)C1", "C=C[SH]1CC=C(c2cccs2)C1",  # hypervalent S from SELFIES edits;
    "C1=CSS(c2cccs2)=C1",  # xTB gave these near-zero gaps, which looked like hits in a real run
])
def test_strained_motifs_are_rejected(smiles):
    assert is_implausible(smiles)


@pytest.mark.parametrize("smiles", [
    "c1ccccc1C#N",                        # nitrile: a triple bond outside a ring is fine
    "O=S(=O)(c1ccccc1)c1ccccc1",          # sulfone: two double bonds on S, a common acceptor
    "CS(C)=O", "NS(=O)(=O)c1ccccc1",      # sulfoxide, sulfonamide: S(IV)/S(VI) only through =O
    "c1csc(-c2cccs2)c1", "CSSC", "S=C(N)N",  # bithiophene, disulfide, thiourea: ordinary two-bonded S
    "c1ccccc1N(=O)=O",                    # neutral nitro: likewise not cumulated carbon
    "C1CC1c1ccccc1",                      # lone cyclopropyl: strained only when fused
    "c1ccc2c(c1)CCC2",                    # indane: a fused 5-ring is common and fine
    SEED,
])
def test_real_motifs_are_kept(smiles):
    assert not is_implausible(smiles)


def test_canonical_smiles_is_a_fixed_point():
    # RDKit writes some fused ring systems in an aromatic form that re-reads as non-aromatic;
    # without a second pass the same molecule could be stored under two spellings (R1.5).
    assert canonical_smiles("C1=CC2c3ccc(c2c3)NC1") == canonical_smiles(canonical_smiles("C1=CC2c3ccc(c2c3)NC1"))
    out = generate([OVERSIZED], GenerationSettings(n_candidates=100), 1, 0)
    assert all(canonical_smiles(c.smiles) == c.smiles for c in out)


def test_empty_smiles_is_not_a_molecule():
    # "" parses to an empty Mol rather than None; structure-only SELFIES decode to "".
    assert canonical_smiles("") is None
    assert selfies_to_smiles(["[Branch1]"]) is None


def test_parents_nh_token_does_not_give_radicals():
    out = generate([NH_SEED], GenerationSettings(n_candidates=100), 1, 0)
    assert len(out) == 100
    assert not any(a.GetNumRadicalElectrons() for c in out for a in Chem.MolFromSmiles(c.smiles).GetAtoms())
