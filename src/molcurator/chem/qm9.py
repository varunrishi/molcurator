# Seed suggestions from QM9: molecules whose QM9 label lies in a property window.
# The filter and the selection are the ones notebooks/qm9_eda.ipynb used for homo_lumo.csv,
# generalised from the HOMO-LUMO gap to any QM9 property.
import urllib.request
from pathlib import Path

import pandas as pd
from rdkit import Chem, DataStructs, RDLogger
from rdkit.Chem import rdFingerprintGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold

from molcurator.chem.convert import canonical_smiles, is_implausible

RDLogger.DisableLog("rdApp.*")

QM9_PATH = Path("data/seeds/qm9.csv")  # gitignored; see data/seeds/README.md
QM9_URL = "https://deepchemdata.s3.us-west-1.amazonaws.com/datasets/qm9.csv"  # DeepChem mirror
HARTREE_EV = 27.211386

# Selectable columns: unit shown to the user, and the factor from the CSV's unit to it.
# Orbital energies are stored in Hartree and converted to eV, since that is how targets
# are written in configs/. The *_atom columns are left out: their units are not documented
# by the mirror.
PROPERTIES = {
    "gap": ("eV", HARTREE_EV), "homo": ("eV", HARTREE_EV), "lumo": ("eV", HARTREE_EV),
    "mu": ("D", 1.0), "alpha": ("bohr^3", 1.0), "r2": ("bohr^2", 1.0), "cv": ("cal/mol K", 1.0),
    "zpve": ("Ha", 1.0), "u0": ("Ha", 1.0), "u298": ("Ha", 1.0), "h298": ("Ha", 1.0),
    "g298": ("Ha", 1.0), "A": ("GHz", 1.0), "B": ("GHz", 1.0), "C": ("GHz", 1.0),
}

# Structures that make poor seeds (qm9_eda.ipynb, "Chemical filter"). Exocyclic imines are
# QM9's tautomer of an amino heterocycle; rewriting them would invalidate the label, so they
# are dropped rather than corrected.
_EXO_IMINE = Chem.MolFromSmarts("[#6;R]=[NX2;!R]")
_ALPHA_DIONE = Chem.MolFromSmarts("[CX3](=O)[CX3]=O")
_FPGEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def load_qm9(path: Path = QM9_PATH, download: bool = True) -> pd.DataFrame:
    """The QM9 table, fetching it from the DeepChem mirror on first use if download is set."""
    if not path.exists():
        if not download:
            raise FileNotFoundError(f"{path} not found; download it with: curl -L -o {path} {QM9_URL}")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(QM9_URL, tmp)  # 28 MB; renamed only once complete
        tmp.rename(path)
    return pd.read_csv(path)


def rejection(mol: Chem.Mol) -> str | None:
    """Why a QM9 molecule is a poor seed, or None if it is fine."""
    if any(a.GetFormalCharge() for a in mol.GetAtoms()):
        return "charged"  # zwitterions: net charge 0, so test every atom, not the sum
    if mol.GetRingInfo().NumRings() == 0:
        return "acyclic"  # chains, not chromophores
    if any(len(r) == 3 for r in mol.GetRingInfo().AtomRings()):
        return "3-ring"
    if mol.HasSubstructMatch(_EXO_IMINE):
        return "exocyclic imine"
    if mol.HasSubstructMatch(_ALPHA_DIONE):
        return "alpha-dione"
    if is_implausible(Chem.MolToSmiles(mol)):
        return "implausible"  # GENERATE rejects these as candidates, so seeds must pass too
    return None


def _medoid(fps: list) -> int:
    """Index of the most central fingerprint: highest mean Tanimoto similarity to the rest."""
    means = [sum(DataStructs.BulkTanimotoSimilarity(f, fps)) for f in fps]
    return means.index(max(means))


def suggest_seeds(qm9: pd.DataFrame, prop: str, lo: float | None = None, hi: float | None = None,
                  n: int = 5) -> tuple[pd.DataFrame, dict[str, int]]:
    """Up to n seeds whose QM9 `prop` lies in [lo, hi], plus counts of what was filtered out.

    Seeds are spread across the window (one per equal-width bin), each has a different Murcko
    scaffold, and each is the medoid of its scaffold in its bin, with common scaffolds taken
    first: representative chemistry rather than the outliers a MaxMin pick would surface.
    Bins with nothing left are made up from the rest of the window. Deterministic.
    """
    if prop not in PROPERTIES:
        raise ValueError(f"unknown property {prop!r}; choose from {', '.join(PROPERTIES)}")
    if lo is None and hi is None:
        raise ValueError("give a lower bound, an upper bound, or both")
    if n < 1:
        raise ValueError("n must be at least 1")
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(f"lower bound {lo} is above upper bound {hi}")
    unit, factor = PROPERTIES[prop]
    value = qm9[prop] * factor
    lo = value.min() if lo is None else lo
    hi = value.max() if hi is None else hi

    window = qm9.assign(value=value)[value.between(lo, hi)]  # cheap filter before parsing
    counts = {"in window": len(window)}
    rows = []
    for r in window.itertuples():
        mol = Chem.MolFromSmiles(r.smiles)
        reason = "unparsable" if mol is None else rejection(mol)
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
            continue
        rows.append(dict(smiles=canonical_smiles(r.smiles), mol_id=r.mol_id, value=r.value,
                         heavy_atoms=mol.GetNumHeavyAtoms(),
                         murcko_scaffold=MurckoScaffold.MurckoScaffoldSmiles(mol=mol),
                         fp=_FPGEN.GetFingerprint(mol)))
    pool = pd.DataFrame(rows, columns=["smiles", "mol_id", "value", "heavy_atoms", "murcko_scaffold", "fp"])
    counts["usable"] = len(pool)

    freq = pool["murcko_scaffold"].value_counts()
    width = (hi - lo) / n
    bins = [pool[pool["value"].between(lo + k * width, lo + (k + 1) * width,
                                       inclusive="both" if k == n - 1 else "left")] for k in range(n)]
    picked, used = [], set()

    def take(group: pd.DataFrame) -> bool:
        """Add the medoid of the most common unused scaffold in group; False if none is left."""
        free = [s for s in group["murcko_scaffold"].unique() if s not in used]
        if not free:
            return False
        scaf = max(free, key=lambda s: (freq[s], s))  # ties broken by name, for repeatability
        members = group[group["murcko_scaffold"] == scaf]
        picked.append(members.index[_medoid(list(members["fp"]))])
        used.add(scaf)
        return True

    for b in bins:
        take(b)
    while len(picked) < n and take(pool):  # empty bins: fill from anywhere in the window
        pass

    seeds = pool.loc[picked].sort_values("value").drop(columns="fp").reset_index(drop=True)
    seeds = seeds.rename(columns={"value": f"qm9_{prop}"})
    seeds.insert(3, "unit", unit)
    seeds["source"] = "QM9"
    return seeds, counts
