"""Structural audit of generated candidates against a seed molecule.

Checks validity, canonicalisation, seed identity (with and without stereo),
intra-batch duplicates, and Tanimoto similarity to the seed.
No Pydantic models are needed here: inputs and outputs are plain dicts.
"""
from rdkit import Chem
from rdkit.Chem import DataStructs, rdFingerprintGenerator

_FPGEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def _canonical(mol: Chem.Mol, isomeric: bool) -> str:
    return Chem.MolToSmiles(mol, isomericSmiles=isomeric)


def _fp(mol: Chem.Mol):
    return _FPGEN.GetFingerprint(mol)


_INVALID_RESULT = {
    "valid": False,
    "canonical_smiles": None,
    "same_as_seed_exact": False,
    "same_as_seed_ignoring_stereo": False,
    "duplicate_of": None,
    "tanimoto_to_seed": None,
}


def _is_invalid_input(smi) -> bool:
    """True when smi is not a non-empty, non-whitespace string."""
    return not isinstance(smi, str) or not smi.strip()


def audit_candidates(
    seed_smiles: str,
    candidate_smiles: dict[str, str],  # {id: smiles}
) -> dict:
    """Audit each candidate against the seed; return per-candidate results and a summary.

    Returns a dict with keys:
      "candidates": {id: {valid, canonical_smiles, same_as_seed_exact,
                          same_as_seed_ignoring_stereo, duplicate_of, tanimoto_to_seed}}
      "summary":    {n_invalid, n_seed_identical, n_duplicate, n_unique_new, n_total}

    Summary categories always partition all candidates exactly:
      n_total == n_invalid + n_seed_identical + n_duplicate + n_unique_new
    A seed-identical candidate is never also counted as a duplicate.

    n_seed_identical counts candidates whose stereo-free canonical SMILES equals
    the seed's (same_as_seed_ignoring_stereo), not same_as_seed_exact.

    A candidate is invalid if its value is not a str, is empty or whitespace,
    RDKit cannot parse it, or the parsed molecule has zero atoms. Bad candidates
    never raise; only a bad seed_smiles raises ValueError.

    Raises ValueError if seed_smiles is not a str, is empty or whitespace,
    does not parse, or parses to a molecule with zero atoms.
    """
    if _is_invalid_input(seed_smiles):
        raise ValueError(f"seed_smiles must be a non-empty, non-whitespace string: {seed_smiles!r}")
    seed_mol = Chem.MolFromSmiles(seed_smiles)
    if seed_mol is None or seed_mol.GetNumAtoms() == 0:
        raise ValueError(f"seed_smiles does not parse or has zero atoms: {seed_smiles!r}")

    seed_canon_iso = _canonical(seed_mol, isomeric=True)
    seed_canon_noiso = _canonical(seed_mol, isomeric=False)
    seed_fp = _fp(seed_mol)

    seen_noiso: dict[str, str] = {}  # canonical non-isomeric SMILES -> first id
    results: dict[str, dict] = {}

    for cid, smi in candidate_smiles.items():
        if _is_invalid_input(smi):
            results[cid] = dict(_INVALID_RESULT)
            continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None or mol.GetNumAtoms() == 0:
            results[cid] = dict(_INVALID_RESULT)
            continue

        canon_iso = _canonical(mol, isomeric=True)
        canon_noiso = _canonical(mol, isomeric=False)
        tanimoto = DataStructs.TanimotoSimilarity(seed_fp, _fp(mol))
        is_seed = canon_noiso == seed_canon_noiso
        # Only register in seen_noiso (and flag duplicate_of) when not seed-identical,
        # so that seed-identical candidates don't mark each other as duplicates.
        duplicate_of = None if is_seed else seen_noiso.get(canon_noiso)

        results[cid] = {
            "valid": True,
            "canonical_smiles": canon_iso,
            "same_as_seed_exact": (canon_iso == seed_canon_iso),
            "same_as_seed_ignoring_stereo": is_seed,
            "duplicate_of": duplicate_of,
            "tanimoto_to_seed": tanimoto,
        }
        if not is_seed and duplicate_of is None:
            seen_noiso[canon_noiso] = cid

    n_invalid = sum(1 for r in results.values() if not r["valid"])
    # seed-identical (ignoring stereo) takes priority over duplicate in the partition
    n_seed_identical = sum(
        1 for r in results.values()
        if r["valid"] and r["same_as_seed_ignoring_stereo"]
    )
    n_duplicate = sum(
        1 for r in results.values()
        if r["valid"] and not r["same_as_seed_ignoring_stereo"] and r["duplicate_of"] is not None
    )
    n_unique_new = sum(
        1 for r in results.values()
        if r["valid"] and not r["same_as_seed_ignoring_stereo"] and r["duplicate_of"] is None
    )

    return {
        "candidates": results,
        "summary": {
            "n_invalid": n_invalid,
            "n_seed_identical": n_seed_identical,
            "n_duplicate": n_duplicate,
            "n_unique_new": n_unique_new,
            "n_total": len(results),
        },
    }
