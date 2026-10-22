# Conversions between molecular representations:
# SMILES <-> RDKit Mol <-> SELFIES, canonicalisation, sanitisation checks.
# Shared chemistry helpers used by several tools.
import selfies
from rdkit import Chem, RDLogger

RDLogger.DisableLog("rdApp.*")  # invalid mutants are expected and dropped; keep the output quiet


def canonical_smiles(smiles: str) -> str | None:
    """Canonical, sanitised SMILES, or None if RDKit cannot parse it or it holds no atoms.

    The result is a fixed point: writing and re-reading it gives the same string back, which
    is what deduplicating molecules by string comparison relies on (R1.5).
    """
    mol = Chem.MolFromSmiles(smiles)
    # "" parses to an empty Mol rather than None, so an atom count is needed as well:
    # SELFIES made only of structure tokens, e.g. "[Branch1]", decodes to "".
    if mol is None or not mol.GetNumAtoms():
        return None
    out = Chem.MolToSmiles(mol)
    # One pass is not always a fixed point: for some fused ring systems RDKit writes an
    # aromatic form that re-reads as non-aromatic (e.g. a 4-membered ring on a benzene).
    # A second pass settles, so the same molecule cannot arrive under two spellings.
    again = Chem.MolFromSmiles(out)
    return Chem.MolToSmiles(again) if again is not None else out


def smiles_to_selfies(smiles: str) -> list[str] | None:
    """SELFIES tokens for a SMILES, or None if it cannot be converted."""
    try:
        return list(selfies.split_selfies(selfies.encoder(smiles)))
    except selfies.EncoderError:
        return None


def selfies_to_smiles(tokens: list[str]) -> str | None:
    """Canonical SMILES for SELFIES tokens, or None if the result is not a valid molecule."""
    try:
        return canonical_smiles(selfies.decoder("".join(tokens)))
    except selfies.DecoderError:
        return None


def heavy_atom_count(smiles: str) -> int:
    """Number of non-hydrogen atoms in a valid SMILES."""
    return Chem.MolFromSmiles(smiles).GetNumHeavyAtoms()


def ring_profile(smiles: str) -> tuple[int, bool]:
    """Number of rings, and whether any atom is aromatic.

    Used to check that a candidate kept its parent's ring system: random SELFIES edits
    open fused aromatics into chains, which destroys the conjugation that sets the
    electronic properties the run is searching for.
    """
    mol = Chem.MolFromSmiles(smiles)  # keep the Mol referenced: RingInfo does not own it
    return mol.GetRingInfo().NumRings(), any(a.GetIsAromatic() for a in mol.GetAtoms())


# An sp carbon with two double bonds: the centre of an allene, cumulene or ketene.
# The centre is pinned to carbon on purpose, so sulfones (O=S=O) and neutral nitro
# groups (N(=O)=O) are kept - both are common acceptor units in TADF emitters.
_CUMULATED = Chem.MolFromSmarts("[#6X2](=*)=*")


def _has_strained_fused_ring(rings: tuple[tuple[int, ...], ...], min_fused: int) -> bool:
    """True if a ring below min_fused shares a bond (two or more atoms) with another ring."""
    # Lone cyclopropyl and cyclobutyl groups are fine, so only fused ones are rejected.
    return any(len(r) < min_fused and any(len(set(r) & set(o)) >= 2 for o in rings if o is not r)
               for r in rings)


def is_implausible(smiles: str, max_ring: int = 8, min_fused_ring: int = 5) -> bool:
    """True for structures that random SELFIES edits produce often but chemists rarely want:
    radicals, rings larger than max_ring, small rings fused onto another ring, triple bonds
    inside rings, and cumulated double bonds."""
    mol = Chem.MolFromSmiles(smiles)
    # Radicals: SELFIES never adds H to a bracket atom, so a parent's [nH] token ([NH1]) left
    # with one bond after an edit decodes to an aminyl radical. Sanitisation accepts it, but
    # PREDICT takes closed-shell molecules only.
    if any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        return True
    rings = mol.GetRingInfo().AtomRings()  # mol must stay referenced: RingInfo does not own it
    if any(len(r) > max_ring for r in rings):
        return True
    if _has_strained_fused_ring(rings, min_fused_ring):
        return True
    if any(b.IsInRing() and b.GetBondType() == Chem.BondType.TRIPLE for b in mol.GetBonds()):
        return True
    return mol.HasSubstructMatch(_CUMULATED)
