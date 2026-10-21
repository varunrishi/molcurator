import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"/"molcurator"))
from rdkit import Chem
from design import canonical, acceptable

def test_canonical():
    assert canonical("OCC") == canonical("CCO")

def test_reject_fragments():
    assert not acceptable(Chem.MolFromSmiles("C.C"))

def test_accept_small_neutral():
    assert acceptable(Chem.MolFromSmiles("CCO"))
