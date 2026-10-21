"""Portable trained fingerprint-ridge predictor; JSON artifacts contain no executable code.

No pretrained model is bundled. A model's declared reference method is metadata,
not evidence of transfer accuracy; validate on independent molecules before use.
"""
import json
import math
from pathlib import Path

import numpy as np
from rdkit import Chem, rdBase
from rdkit.Chem import rdFingerprintGenerator

from .properties import UNITS


def fingerprint(smiles: str, radius: int, size: int):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or not mol.GetNumAtoms() or len(Chem.GetMolFrags(mol)) != 1:
        raise ValueError("one valid connected molecule required")
    if Chem.GetFormalCharge(mol) or any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        raise ValueError("neutral closed-shell molecules required")
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=radius, fpSize=size)
    return generator.GetFingerprintAsNumPy(mol).astype(float)


class FingerprintModel:
    """One molecular descriptor-to-properties model with explicit target units/method."""

    def __init__(self, artifact: dict):
        if artifact.get("format") != "molcurator-fingerprint-ridge-v1":
            raise ValueError("unsupported ML model format")
        self.artifact = artifact
        self.radius, self.size = artifact["radius"], artifact["size"]
        if not isinstance(self.radius, int) or not 1 <= self.radius <= 4:
            raise ValueError("invalid fingerprint radius")
        if not isinstance(self.size, int) or not 32 <= self.size <= 4096:
            raise ValueError("invalid fingerprint size")
        if not artifact.get("reference_method") or not artifact.get("targets"):
            raise ValueError("ML artifact needs target definitions and reference method")
        for name, target in artifact["targets"].items():
            if name not in UNITS or target["units"] != UNITS[name]:
                raise ValueError("unsupported property or inconsistent model units")
            coefficients = target["coefficients"]
            if len(coefficients) != self.size or not all(math.isfinite(float(v)) for v in
                                                       [*coefficients, target["intercept"]]):
                raise ValueError("invalid ML coefficients")

    @classmethod
    def load(cls, path: str | Path):
        return cls(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    def predict(self, smiles: str) -> dict[str, float]:
        x = fingerprint(smiles, self.radius, self.size)
        values = {name: float(x @ np.asarray(target["coefficients"]) + target["intercept"])
                  for name, target in self.artifact["targets"].items()}
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError("nonfinite ML prediction")
        return values

    def save(self, path: str | Path):
        path = Path(path)
        with path.open("x") as output:
            json.dump(self.artifact, output, indent=2, allow_nan=False)


def train_fingerprint_model(smiles: list[str], labels: dict[str, list[float]], *,
                            reference_method: str, alpha: float = 1.0,
                            radius: int = 2, size: int = 256) -> FingerprintModel:
    """Fit on supplied labels only. No automated validation or uncertainty is claimed."""
    if len(smiles) < 2 or not labels or not reference_method:
        raise ValueError("at least two labelled molecules and a reference method required")
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("positive finite ridge penalty required")
    if not isinstance(radius, int) or not 1 <= radius <= 4 or not isinstance(size, int) or not 32 <= size <= 4096:
        raise ValueError("unsupported fingerprint settings")
    canonical = [Chem.MolToSmiles(Chem.MolFromSmiles(s)) if Chem.MolFromSmiles(s) else None for s in smiles]
    if None in canonical or len(set(canonical)) != len(smiles):
        raise ValueError("training molecules must be valid and canonically unique")
    x = np.stack([fingerprint(s, radius, size) for s in smiles])
    mean = x.mean(axis=0)
    centered = x - mean
    artifact = dict(format="molcurator-fingerprint-ridge-v1", radius=radius, size=size,
                    reference_method=reference_method, alpha=alpha, n_train=len(smiles),
                    rdkit_version=rdBase.rdkitVersion, numpy_version=np.__version__,
                    training_smiles=canonical, targets={}, uncertainty="not_available")
    for name, values in labels.items():
        y = np.asarray(values, dtype=float)
        if name not in UNITS or y.shape != (len(smiles),) or not np.isfinite(y).all():
            raise ValueError("labels must be finite supported properties, one per molecule")
        if name in ("homo_lumo_gap", "dipole") and (y < 0).any():
            raise ValueError("gap and dipole magnitude labels must be nonnegative")
        coefficients = centered.T @ np.linalg.solve(centered @ centered.T + alpha * np.eye(len(smiles)), y - y.mean())
        intercept = float(y.mean() - mean @ coefficients)
        artifact["targets"][name] = dict(units=UNITS[name], coefficients=coefficients.tolist(),
                                        intercept=intercept)
    return FingerprintModel(artifact)
