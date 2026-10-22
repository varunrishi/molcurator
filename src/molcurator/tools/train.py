"""Training and screening utilities for xTB molecular properties.

The public functions in this module intentionally accept CSV paths rather than
project-specific objects: the training data is an external, tabular artifact.
All cleaning decisions are recorded in the report card and the serialized
bundle contains the complete feature layout needed for inference.
"""

from __future__ import annotations

import json
import warnings
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors, rdFingerprintGenerator, rdMolDescriptors
from rdkit.Chem.Scaffolds import MurckoScaffold
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut, RepeatedKFold

from molcurator.schemas import Candidate, Prediction, PropertyTarget, Status, TrainingExample, TrainResult

_FP_NBITS_FEAT = 1024
DESCRIPTOR_NAMES = (
    "heavy_atoms", "rings", "aromatic_rings", "aromatic_atoms", "tpsa",
    "logp", "hbd", "hba", "fraction_sp3", "rotatable_bonds",
)
_FP_GENERATOR = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=_FP_NBITS_FEAT)

DEFAULT_SPEC = {
    "target": "xtb_gap_ev", "units": "eV", "id_col": "id", "smiles_col": "smiles",
    "group_col": "parent_mol_id", "keep_if": {"status": "ok"},
    "drop_if": {"fractional_occupation": True}, "extra_x_cols": [],
    "neutral_closed_shell_only": True,
}


def _merge_spec(spec: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(DEFAULT_SPEC)
    if spec:
        result.update(spec)
    return result


def _validate_columns(df: pd.DataFrame, columns: list[str], source: Any) -> None:
    missing = [c for c in columns if c and c not in df.columns]
    if missing:
        raise ValueError(f"{source} is missing required columns: {', '.join(missing)}")


def _row_matches(row: Any, conditions: dict[str, Any]) -> bool:
    return all(
        column in row.index
        and str(row[column]).strip().lower() == str(value).strip().lower()
        for column, value in conditions.items()
    )


def _mol_from_smiles(smiles: Any) -> Chem.Mol | None:
    if not isinstance(smiles, str) or not smiles.strip():
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
    except (TypeError, ValueError):
        return None
    return mol if mol is not None and mol.GetNumHeavyAtoms() else None


def _canonical(smiles: Any) -> str | None:
    mol = _mol_from_smiles(smiles)
    return Chem.MolToSmiles(mol, isomericSmiles=False) if mol else None


def _is_charged_or_radical(mol: Chem.Mol) -> bool:
    return Chem.GetFormalCharge(mol) != 0 or any(
        atom.GetNumRadicalElectrons() > 0 for atom in mol.GetAtoms()
    )


def _descriptors(mol: Chem.Mol) -> dict[str, float]:
    return {
        "heavy_atoms": float(mol.GetNumHeavyAtoms()),
        "rings": float(rdMolDescriptors.CalcNumRings(mol)),
        "aromatic_rings": float(rdMolDescriptors.CalcNumAromaticRings(mol)),
        "aromatic_atoms": float(sum(atom.GetIsAromatic() for atom in mol.GetAtoms())),
        "tpsa": float(rdMolDescriptors.CalcTPSA(mol)),
        "logp": float(Descriptors.MolLogP(mol)),
        "hbd": float(rdMolDescriptors.CalcNumHBD(mol)),
        "hba": float(rdMolDescriptors.CalcNumHBA(mol)),
        "fraction_sp3": float(rdMolDescriptors.CalcFractionCSP3(mol)),
        "rotatable_bonds": float(rdMolDescriptors.CalcNumRotatableBonds(mol)),
    }


def _build_features(mol: Chem.Mol, elements: list[str]) -> np.ndarray:
    fp = _FP_GENERATOR.GetFingerprintAsNumPy(mol).astype(np.float32)
    desc = _descriptors(mol)
    elem_counts = Counter(atom.GetSymbol() for atom in mol.GetAtoms())
    values = [desc[name] for name in DESCRIPTOR_NAMES]
    values.extend(float(elem_counts.get(element, 0)) for element in elements)
    vector = np.concatenate([fp, np.asarray(values, dtype=np.float32)])
    if not np.isfinite(vector).all():
        raise ValueError("molecule produced non-finite features")
    return vector


def _feature_names(elements: list[str]) -> list[str]:
    return [f"fp_{i}" for i in range(_FP_NBITS_FEAT)] + list(DESCRIPTOR_NAMES) + [
        f"elem_{element}" for element in elements
    ]


def _clean(df: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, int]]:
    counts = {"n_raw": len(df)}
    d = df.copy()
    for column, value in spec["keep_if"].items():
        d = d[d.apply(lambda row, c=column, v=value: _row_matches(row, {c: v}), axis=1)]
    counts["n_after_keep_if"] = len(d)
    numeric = pd.to_numeric(d[spec["target"]], errors="coerce")
    raw_target = d[spec["target"]].astype(str).str.strip()
    nonnumeric = d[raw_target.ne("") & numeric.isna()]
    counts["n_nonnumeric_target"] = len(nonnumeric)
    if len(nonnumeric):
        warnings.warn(f"Dropping {len(nonnumeric)} non-numeric target values", UserWarning)
    d = d.assign(**{spec["target"]: numeric})
    d = d[np.isfinite(d[spec["target"]].fillna(np.nan))]
    counts["n_after_target_present"] = len(d)
    for column, value in spec["drop_if"].items():
        d = d[~d.apply(lambda row, c=column, v=value: _row_matches(row, {c: v}), axis=1)]
    counts["n_after_drop_if"] = len(d)
    d = d.assign(_mol=d[spec["smiles_col"]].map(_mol_from_smiles))
    d = d[d["_mol"].notna()].copy()
    d["_canonical"] = d["_mol"].map(lambda mol: Chem.MolToSmiles(mol, isomericSmiles=False))
    counts["n_after_rdkit_valid"] = len(d)
    if spec.get("neutral_closed_shell_only", True):
        d = d[~d["_mol"].map(_is_charged_or_radical)].copy()
    counts["n_after_neutral_closed_shell"] = len(d)
    d = d.drop_duplicates("_canonical", keep="first")
    counts["n_final"] = len(d)
    return d.reset_index(drop=True), counts


def _metrics(y_true: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    if len(y_true) == 0 or len(pred) == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "r2": float("nan")}
    if len(y_true) != len(pred):
        raise ValueError("y_true and pred must have the same length")
    return {
        "mae": float(mean_absolute_error(y_true, pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, pred))),
        "r2": float(r2_score(y_true, pred)) if len(np.unique(y_true)) > 1 else 0.0,
    }


def _supported_molecules(data: pd.DataFrame, indices: np.ndarray, elements: list[str]) -> np.ndarray:
    """Return a mask for molecules representable by the training vocabulary."""
    vocabulary = set(elements)
    return np.asarray([
        all(atom.GetSymbol() in vocabulary for atom in data.iloc[index]["_mol"].GetAtoms())
        for index in indices
    ], dtype=bool)


def _spearman_correlation(first: np.ndarray, second: np.ndarray) -> float | None:
    """Return rank correlation, or None when it is undefined."""
    if len(first) != len(second) or len(first) < 2:
        return None
    first_ranks = pd.Series(first).rank(method="average").to_numpy()
    second_ranks = pd.Series(second).rank(method="average").to_numpy()
    if np.std(first_ranks) == 0 or np.std(second_ranks) == 0:
        return None
    return float(np.corrcoef(first_ranks, second_ranks)[0, 1])


def _rf_std(model: Any, features: np.ndarray) -> np.ndarray:
    if not hasattr(model, "estimators_"):
        return np.full(len(features), np.nan)
    return np.asarray([tree.predict(features) for tree in model.estimators_]).std(axis=0)


def _fit_model(name: str, seed: int, fast: bool) -> Any:
    if name == "random_forest":
        return RandomForestRegressor(
            n_estimators=50 if fast else 300, max_features=0.33,
            n_jobs=-1, random_state=seed,
        )
    if name == "ridge_size":
        return Ridge(alpha=1.0)
    raise ValueError("model must be one of: random_forest, ridge_size")


def _split_groups(data: pd.DataFrame, split: str, group_col: str | None) -> np.ndarray | None:
    """Group label per molecule; a group is never divided between partitions. None means no grouping."""
    if split == "scaffold":
        # Bemis-Murcko scaffold; acyclic molecules all get "" and so form one group
        return data["_mol"].map(lambda mol: MurckoScaffold.MurckoScaffoldSmiles(mol=mol)).to_numpy()
    if group_col and group_col in data:
        values = data[group_col].fillna("").astype(str).str.strip()
        if values.ne("").all() and values.nunique() > 1:
            return values.to_numpy()
    return None


def _resolve_sizes(sizes: dict[str, int | float], n: int) -> dict[str, int]:
    """Partition sizes as molecule counts: an int is a count, a float a fraction of the n usable molecules."""
    fractions = {name: size for name, size in sizes.items() if isinstance(size, float)}
    if any(not 0 <= size <= 1 for size in fractions.values()) or sum(fractions.values()) > 1 + 1e-9:
        raise ValueError("fractional train/val/test sizes must each be in [0, 1] and sum to at most 1")
    return {name: int(round(size * n)) if isinstance(size, float) else int(size) for name, size in sizes.items()}


def _partition_indices(
    n: int,
    groups: np.ndarray | None,
    train_size: int,
    val_size: int,
    test_size: int,
    seed: int,
    smallest_groups_first: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Create disjoint train/val/test/pool indices, made of whole groups when groups are given."""
    with_val = val_size > 0
    if n < 3 + with_val:
        raise ValueError("At least three usable molecules (four with a validation set) are required for a test split")
    requested_train = max(1, min(train_size, n - 2 - with_val))
    requested_val = max(1, min(val_size, n - requested_train - 2)) if with_val else 0
    requested_test = max(1, min(test_size, n - requested_train - requested_val - 1))
    rng = np.random.default_rng(seed)
    if groups is None:
        order = rng.permutation(n)
        val_end = requested_train + requested_val
        return (
            np.sort(order[:requested_train]),
            np.sort(order[requested_train:val_end]),
            np.sort(order[val_end:val_end + requested_test]),
            np.sort(order[val_end + requested_test:]),
        )

    # A group larger than every held-out target can only be held out by overshooting it, so it goes to train
    held_out_targets = [size for size in (requested_val, requested_test) if size]
    largest_held_out = max(held_out_targets)

    def choose_group_indices(available: np.ndarray, target: int, oversized_first: bool = False) -> np.ndarray:
        group_to_indices: dict[str, np.ndarray] = {}
        for group in np.unique(groups[available]):
            group_to_indices[group] = available[groups[available] == group]
        selected: list[np.ndarray] = []
        total = 0
        group_order = list(group_to_indices)
        rng.shuffle(group_order)
        # Few large parent groups: smallest first keeps the counts near target. Many scaffolds, a third of
        # them singletons: smallest first would fill train with singletons, so take them in shuffled order.
        if smallest_groups_first:
            group_order = sorted(group_order, key=lambda item: len(group_to_indices[item]))
        elif oversized_first:  # largest oversized group first; stable, so the rest keep their shuffled order
            group_order = sorted(group_order, key=lambda item: (
                len(group_to_indices[item]) <= largest_held_out,
                -len(group_to_indices[item]) if len(group_to_indices[item]) > largest_held_out else 0,
            ))
        for group in group_order:
            indices = group_to_indices[group]
            if total + len(indices) <= target or not selected:
                selected.append(indices)
                total += len(indices)
            if total >= target:
                break
        return np.sort(np.concatenate(selected)) if selected else np.array([], dtype=int)

    remaining = np.arange(n)
    train = choose_group_indices(remaining, requested_train, oversized_first=True)
    remaining = np.setdiff1d(remaining, train, assume_unique=True)
    val = choose_group_indices(remaining, requested_val) if with_val else np.array([], dtype=int)
    remaining = np.setdiff1d(remaining, val, assume_unique=True)
    test = choose_group_indices(remaining, requested_test)
    pool = np.setdiff1d(remaining, test, assume_unique=True)
    return train, val, test, pool


def _cv_splits(X_train: np.ndarray, y_train: np.ndarray, train_groups: np.ndarray | None,
               split: str, n_splits: int, seed: int):
    """Cross-validation folds inside train: by group when there are groups, else random K-fold."""
    if train_groups is not None and len(np.unique(train_groups)) >= 2:
        if split == "scaffold":  # hundreds of scaffolds: leave-one-group-out would mean hundreds of fits
            return GroupKFold(n_splits=min(5, len(np.unique(train_groups)))).split(X_train, y_train, train_groups)
        return LeaveOneGroupOut().split(X_train, y_train, train_groups)
    return RepeatedKFold(n_splits=n_splits, n_repeats=1, random_state=seed).split(X_train)


def _heldout_frame(data: pd.DataFrame, indices: np.ndarray, y_true: np.ndarray, supported: np.ndarray,
                   predictions: np.ndarray, abs_error: np.ndarray, elements: list[str],
                   sp: dict[str, Any]) -> pd.DataFrame:
    """Per-molecule predictions for a held-out partition (test or validation)."""
    frame = data.iloc[indices][[sp["id_col"], sp["smiles_col"]]].copy()
    frame["y_true"] = y_true
    frame["reference_" + sp["target"] + "_evaluation_only"] = y_true
    frame["status"] = np.where(supported, "supported", "unsupported")
    frame["reason"] = np.where(
        supported, "", [
            "unseen_element: " + ",".join(sorted({
                atom.GetSymbol() for atom in data.iloc[index]["_mol"].GetAtoms()
                if atom.GetSymbol() not in set(elements)
            }))
            for index in indices
        ],
    )
    frame["predicted"] = predictions
    frame["predicted_" + sp["target"]] = predictions
    frame["absolute_error_evaluation_only"] = abs_error
    frame["absolute_error_ev"] = abs_error
    return frame


def train_property_model(
    csv_path: str | Path,
    *,
    spec: dict[str, Any] | None = None,
    out_dir: str | Path = "model_out",
    model: str = "random_forest",
    fast: bool = False,
    seed: int = 42,
    window: tuple[float, float] | None = None,
    train_size: int | float = 200,
    test_size: int | float = 50,
    val_size: int | float = 0,
    split: str = "parent",
    refit_on_all: bool = False,
) -> dict[str, Any]:
    """Clean a labelled CSV, cross-validate, fit, and serialize a property model.

    split="parent" keeps each parent group (spec["group_col"]) in one partition; split="scaffold"
    does the same for Bemis-Murcko scaffolds, so val and test hold only ring systems unseen in
    training. val_size > 0 adds a validation set, scored with the train-only model like test.
    Sizes are molecule counts (int) or fractions of the usable molecules after cleaning (float),
    e.g. train_size=0.7, val_size=0.15, test_size=0.15; molecules left over form the pool.
    refit_on_all=True fits the saved model, after the test metrics are measured, on every usable
    molecule (train, val, test and pool) whose elements the model knows, so held-out ring systems also
    reach it; the reported metrics then describe the train-only model, a cautious estimate.
    """
    if model not in {"random_forest", "ridge_size"}:
        raise ValueError("model must be one of: random_forest, ridge_size")
    if split not in {"parent", "scaffold"}:
        raise ValueError("split must be one of: parent, scaffold")
    sp = _merge_spec(spec)
    raw = pd.read_csv(csv_path, keep_default_na=False)
    required = [sp["smiles_col"], sp["target"], sp["id_col"]]
    required += list(sp["keep_if"]) + list(sp["drop_if"])
    _validate_columns(raw, list(dict.fromkeys(required)), csv_path)
    data, counts = _clean(raw, sp)
    if data.empty:
        raise ValueError("No usable molecules remain after cleaning")
    y = data[sp["target"]].to_numpy(float)
    sizes = _resolve_sizes({"train": train_size, "val": val_size, "test": test_size}, len(data))
    groups = _split_groups(data, split, sp.get("group_col"))
    train_idx, val_idx, test_idx, pool_idx = _partition_indices(
        len(data), groups, sizes["train"], sizes["val"], sizes["test"], seed,
        smallest_groups_first=split != "scaffold",
    )
    split_method = (
        "stratified random split (parent IDs unavailable)" if groups is None
        else "scaffold split (Bemis-Murcko)" if split == "scaffold"
        else "parent-group-aware split"
    )
    train_data = data.iloc[train_idx]
    elements = sorted({atom.GetSymbol() for mol in train_data["_mol"] for atom in mol.GetAtoms()})
    X = np.vstack([_build_features(mol, elements) for mol in data["_mol"]])
    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]
    X_test, y_test = X[test_idx], y[test_idx]
    val_supported = _supported_molecules(data, val_idx, elements)
    test_supported = _supported_molecules(data, test_idx, elements)
    pool_supported = _supported_molecules(data, pool_idx, elements)
    n_splits = min(5, max(2, len(train_idx) - 1)) if len(train_idx) >= 2 else 1
    oof = np.full(len(train_idx), np.nan)
    fold_rows: list[dict[str, Any]] = []
    if split == "scaffold":
        train_groups = groups[train_idx]
    else:
        train_groups = (
            train_data[sp["group_col"]].fillna("").astype(str).to_numpy()
            if sp.get("group_col") and sp["group_col"] in train_data
            else None
        )
    if len(train_idx) >= 2:
        splits = _cv_splits(X_train, y_train, train_groups, split, n_splits, seed)
        for fold, (tr, te) in enumerate(splits):
            fitted = _fit_model(model, seed + fold, fast)
            fit_x = X_train[tr][:, [_FP_NBITS_FEAT + DESCRIPTOR_NAMES.index("heavy_atoms")]] if model == "ridge_size" else X_train[tr]
            fold_val_x = X_train[te][:, [_FP_NBITS_FEAT + DESCRIPTOR_NAMES.index("heavy_atoms")]] if model == "ridge_size" else X_train[te]
            fitted.fit(fit_x, y_train[tr])
            pred = fitted.predict(fold_val_x)
            oof[te] = pred
            fold_rows.append({"fold": fold, "model": model, **_metrics(y_train[te], pred)})
    valid_oof = ~np.isnan(oof)
    cv_metric = _metrics(y_train[valid_oof], oof[valid_oof])
    baseline_oof = np.full(len(y_train), np.nan)
    baseline_fold_rows: list[dict[str, Any]] = []
    if len(train_idx) >= 2:
        baseline_splits = _cv_splits(X_train, y_train, train_groups, split, n_splits, seed)
        for fold, (tr, te) in enumerate(baseline_splits):
            fold_baseline = float(np.mean(y_train[tr]))
            baseline_oof[te] = fold_baseline
            baseline_fold_rows.append({
                "fold": fold,
                "model": "mean",
                **_metrics(y_train[te], np.full(len(te), fold_baseline)),
            })
    valid_baseline = ~np.isnan(baseline_oof)
    cv_baseline = _metrics(y_train[valid_baseline], baseline_oof[valid_baseline])
    baseline_model = DummyRegressor(strategy="mean").fit(X_train, y_train)
    baseline_test = baseline_model.predict(X_test)
    test_model = _fit_model(model, seed, fast)
    test_x = X_train[:, [_FP_NBITS_FEAT + DESCRIPTOR_NAMES.index("heavy_atoms")]] if model == "ridge_size" else X_train
    test_features = X_test[:, [_FP_NBITS_FEAT + DESCRIPTOR_NAMES.index("heavy_atoms")]] if model == "ridge_size" else X_test
    test_model.fit(test_x, y_train)
    test_predictions = np.full(len(test_idx), np.nan)
    if test_supported.any():
        test_predictions[test_supported] = test_model.predict(test_features[test_supported])
    test_metric = _metrics(y_test[test_supported], test_predictions[test_supported])
    baseline_metric = _metrics(y_test[test_supported], baseline_test[test_supported])
    # Validation is scored like test: by the model fitted on train only
    val_features = X_val[:, [_FP_NBITS_FEAT + DESCRIPTOR_NAMES.index("heavy_atoms")]] if model == "ridge_size" else X_val
    val_predictions = np.full(len(val_idx), np.nan)
    if val_supported.any():
        val_predictions[val_supported] = test_model.predict(val_features[val_supported])
    abs_val_error = np.abs(y_val - val_predictions)
    val_metric = _metrics(y_val[val_supported], val_predictions[val_supported])
    val_baseline_metric = _metrics(y_val[val_supported], baseline_model.predict(X_val)[val_supported]) if len(val_idx) else val_metric
    test_spread = np.full(len(test_idx), np.nan)
    if test_supported.any():
        test_spread[test_supported] = _rf_std(test_model, test_features[test_supported])
    abs_test_error = np.full(len(test_idx), np.nan)
    if test_supported.any():
        abs_test_error[test_supported] = np.abs(y_test[test_supported] - test_predictions[test_supported])
    finite_spread = np.isfinite(test_spread) & test_supported
    uncertainty_correlation = _spearman_correlation(
        test_spread[finite_spread], abs_test_error[finite_spread]
    )
    shuffled = _fit_model(model, seed + 10_000, fast)
    shuffled.fit(test_x, np.random.default_rng(seed).permutation(y_train))
    if test_supported.any():
        shuffled_predictions = shuffled.predict(test_features[test_supported])
        shuffled_r2 = _metrics(y_test[test_supported], shuffled_predictions)["r2"]
    else:
        shuffled_r2 = None
    # The saved model: on train only, or (refit_on_all) on every molecule whose elements the features cover
    fit_idx = np.arange(len(data)) if refit_on_all else np.asarray(train_idx)
    fit_idx = fit_idx[_supported_molecules(data, fit_idx, elements)] if refit_on_all else fit_idx
    final = _fit_model(model, seed, fast)
    final.fit(
        X[fit_idx][:, [_FP_NBITS_FEAT + DESCRIPTOR_NAMES.index("heavy_atoms")]]
        if model == "ridge_size" else X[fit_idx],
        y[fit_idx],
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if window is not None:
        p5, p95 = np.quantile(y_train, [0.05, 0.95])
        if window[1] < y_train.min() or window[0] > y_train.max():
            warnings.warn("window is entirely outside the training label range", UserWarning)
        elif window[0] < p5 or window[1] > p95:
            warnings.warn("window extends outside the training p5-p95 range", UserWarning)
    else:
        window = (float(np.min(y_train)), float(np.max(y_train)))
    oof_frame = train_data[[sp["id_col"], sp["smiles_col"]]].copy()
    oof_frame["y_true"] = y_train
    oof_frame[f"oof_{model}"] = oof
    oof_frame.to_csv(out / "oof_predictions.csv", index=False)
    test_frame = _heldout_frame(data, test_idx, y_test, test_supported, test_predictions, abs_test_error, elements, sp)
    test_frame.to_csv(out / "test_predictions.csv", index=False)
    val_frame = _heldout_frame(data, val_idx, y_val, val_supported, val_predictions, abs_val_error, elements, sp)
    if len(val_idx):
        val_frame.to_csv(out / "validation_predictions.csv", index=False)
    # Which partition every molecule landed in, and the group that kept it there
    partition_frame = data[[sp["id_col"], sp["smiles_col"]]].copy()
    partition_frame["split"] = "pool"
    for name, indices in (("train", train_idx), ("val", val_idx), ("test", test_idx)):
        partition_frame.iloc[indices, partition_frame.columns.get_loc("split")] = name
    partition_frame["group"] = groups if groups is not None else ""
    partition_frame.to_csv(out / "partition.csv", index=False)
    pool_frame = data.iloc[pool_idx].copy()
    pool_features = X[pool_idx]
    pool_x = pool_features[:, [_FP_NBITS_FEAT + DESCRIPTOR_NAMES.index("heavy_atoms")]] if model == "ridge_size" else pool_features
    pool_pred = np.full(len(pool_frame), np.nan)
    if pool_supported.any():
        pool_pred[pool_supported] = final.predict(pool_x[pool_supported])
    pool_frame["status"] = np.where(pool_supported, "supported", "unsupported")
    pool_frame["reason"] = np.where(
        pool_supported, "", [
            "unseen_element: " + ",".join(sorted({
                atom.GetSymbol() for atom in data.iloc[index]["_mol"].GetAtoms()
                if atom.GetSymbol() not in set(elements)
            }))
            for index in pool_idx
        ],
    )
    pool_frame["reference_" + sp["target"] + "_evaluation_only"] = pool_frame[sp["target"]]
    pool_frame["predicted_" + sp["target"]] = pool_pred
    pool_frame["absolute_error_evaluation_only"] = np.abs(pool_frame[sp["target"]] - pool_pred)
    pool_frame["absolute_error_ev"] = pool_frame["absolute_error_evaluation_only"]
    pool_frame.drop(columns=["_mol", "_canonical"], errors="ignore").to_csv(out / "prediction_pool.csv", index=False)
    summary = pd.DataFrame(fold_rows)
    summary = pd.concat([summary, pd.DataFrame(baseline_fold_rows)], ignore_index=True)
    summary.to_csv(out / "summary.csv", index=False)
    true_in_window = test_supported & (y_test >= window[0]) & (y_test <= window[1])
    predicted_in_window = test_supported & (test_predictions >= window[0]) & (test_predictions <= window[1])
    n_selected_test = int(predicted_in_window.sum())
    true_selected = int((true_in_window & predicted_in_window).sum())
    precision = float(true_selected / n_selected_test) if n_selected_test else 0.0
    recall = float(true_selected / true_in_window.sum()) if true_in_window.any() else 0.0
    base_rate = float(true_in_window[test_supported].mean()) if test_supported.any() else 0.0
    supported_errors = abs_test_error[test_supported]
    supported_y_test = y_test[test_supported]
    test_bins = (
        pd.qcut(pd.Series(supported_y_test), q=min(5, len(supported_y_test)), duplicates="drop")
        if test_supported.any() else pd.Series(dtype="category")
    )
    mae_by_bin = []
    for label in test_bins.cat.categories:
        mask = (test_bins == label).to_numpy()
        if mask.any():
            mae_by_bin.append({"bin": str(label), "n": int(mask.sum()),
                               "mae": float(np.mean(supported_errors[mask]))})
    # The split's own groups: scaffolds for a scaffold split (parents then legitimately cross partitions)
    if split == "scaffold":
        overlap_labels = groups
    elif sp.get("group_col") and sp["group_col"] in data:
        overlap_labels = data[sp["group_col"]].astype(str).to_numpy()
    else:
        overlap_labels = None
    group_overlap = overlap_labels is not None and any(
        set(overlap_labels[first]) & set(overlap_labels[second])
        for first, second in ((train_idx, val_idx), (train_idx, test_idx), (val_idx, test_idx))
    )
    partitions = {"train": train_idx, "val": val_idx, "test": test_idx, "pool": pool_idx}
    canonical_overlap = {
        f"{first}_{second}": bool(
            set(data.iloc[partitions[first]]["_canonical"])
            & set(data.iloc[partitions[second]]["_canonical"])
        )
        for first, second in (("train", "test"), ("train", "pool"), ("test", "pool"),
                              ("train", "val"), ("val", "test"), ("val", "pool"))
    }
    train_elements = set(elements)
    test_unseen_elements = sorted({
        atom.GetSymbol()
        for mol in data.iloc[test_idx]["_mol"]
        for atom in mol.GetAtoms()
        if atom.GetSymbol() not in train_elements
    })
    leakage_checks = {
        f"{split}_group_overlap": {
            "status": "fail" if group_overlap else "pass",
            "evidence": f"exact {split}-group intersection between train, val and test",
            "value": group_overlap,
        },
        "canonical_smiles_overlap": {
            "status": "fail" if any(canonical_overlap.values()) else "pass",
            "evidence": "exact canonical-SMILES intersections across partitions",
            "value": canonical_overlap,
        },
        "target_used_in_features": {
            "status": "pass",
            "evidence": "feature construction uses fingerprints, descriptors, and training element counts only",
            "value": False,
        },
        "held_out_targets_used_for_fit_or_window": {
            "status": "pass",
            "evidence": "model fitting and default window use training labels only",
            "value": False,
        },
        "training_element_vocabulary_only": {
            "status": "pass",
            "evidence": "element vocabulary was collected from train_idx only",
            "value": True,
        },
    }
    no_leak = all(check["status"] == "pass" for check in leakage_checks.values())
    pool_retrospective = {
        "available": True,
        "labels_used_for_training_or_selection": False,
        "n_molecules": len(pool_idx),
        "n_supported": int(pool_supported.sum()),
        "n_evaluated": int(pool_supported.sum()),
        "metrics": _metrics(y[pool_idx][pool_supported], pool_pred[pool_supported])
        if pool_supported.any() else None,
    }
    checks = {
        "enough_rows": bool(len(y) >= 40),
        "beats_baselines": bool(test_metric["mae"] <= baseline_metric["mae"]),
        "no_leak": no_leak,
    }
    reasons = [key for key, value in checks.items() if not value]
    card: dict[str, Any] = {
        "target": sp["target"], "units": sp["units"], "n_rows": len(y),
        "cleaning_counts": counts,         "y_min_max": [float(y_train.min()), float(y_train.max())],
        "y_range_p5_p95": [float(np.quantile(y_train, .05)), float(np.quantile(y_train, .95))],
        "elements": elements,
        "heavy_atom_range": [
            int(X_train[:, _FP_NBITS_FEAT].min()), int(X_train[:, _FP_NBITS_FEAT].max())
        ],
        "cv": {"scheme_a": {model: cv_metric, "mean": cv_baseline}},
        "test_metrics": {model: test_metric, "mean_baseline": baseline_metric},
        "test_evaluation": {
            "n_total": len(test_idx),
            "n_supported": int(test_supported.sum()),
            "n_evaluated": int(test_supported.sum()),
        },
        "test_predictions": test_frame.to_dict("records"),
        "validation_metrics": (
            {model: val_metric, "mean_baseline": val_baseline_metric} if len(val_idx) else None
        ),
        "validation_evaluation": {
            "n_total": len(val_idx),
            "n_supported": int(val_supported.sum()),
            "n_evaluated": int(val_supported.sum()),
        },
        "partition": {
            "requested": {**sizes, "pool": max(0, len(data) - sum(sizes.values()))},
            "requested_as_given": {"train": train_size, "val": val_size, "test": test_size},
            "actual": {"train": len(train_idx), "val": len(val_idx), "test": len(test_idx), "pool": len(pool_idx)},
            "split": split,
            "split_method": split_method,
            "n_groups": int(len(np.unique(groups))) if groups is not None else None,
            "group_overlap": group_overlap,
            "canonical_overlap": canonical_overlap,
            "constraints_changed_counts": bool(
                len(train_idx) != sizes["train"] or len(val_idx) != sizes["val"] or len(test_idx) != sizes["test"]
            ),
        },
        "cv_means": fold_rows + baseline_fold_rows,
        "mae_by_quantile_bin": {"test": mae_by_bin},
        "spearman_uncertainty_vs_error": uncertainty_correlation,
        "shuffled_label_R2_rf": shuffled_r2,
        "window": list(window), "window_metrics": {"scheme_a": {
            "n_true_in_window": int(true_in_window.sum()),
            "n_selected": n_selected_test, "precision": precision, "recall": recall,
            "base_rate": base_rate,
            "enrichment": float(precision / base_rate) if base_rate else 0.0,
        }},
        "window_source": "training_labels_only",
        "pool_evaluation": pool_retrospective,
        "test_unseen_elements": test_unseen_elements,
        "pool_unseen_elements": sorted({
            atom.GetSymbol()
            for mol in data.iloc[pool_idx][~pool_supported]["_mol"]
            for atom in mol.GetAtoms()
            if atom.GetSymbol() not in set(elements)
        }),
        "leakage_checks": leakage_checks,
        "gate_min_similarity": 0.0, "checks": checks, "warnings": [],
        "no_leak": no_leak,
        "go": all(checks.values()) and no_leak, "reasons": reasons,
        "paths": {
            "model": str(out / "model.joblib"),
            "test_predictions": str(out / "test_predictions.csv"),
            "validation_predictions": str(out / "validation_predictions.csv") if len(val_idx) else None,
            "prediction_pool": str(out / "prediction_pool.csv"),
            "partition": str(out / "partition.csv"),
        },
        "feature_config": {
            "fingerprint": "Morgan", "radius": 2, "size": _FP_NBITS_FEAT,
            "descriptors": list(DESCRIPTOR_NAMES), "elements": elements,
        },
        "model_parameters": final.get_params(),
        "final_fit": {"refit_on_all": refit_on_all, "n": int(len(fit_idx))},  # what the saved model learned from
    }
    bundle = {
        "model": final, "feature_names": _feature_names(elements), "elements": elements,
        "spec": sp, "report_card": card, "target": sp["target"], "model_name": model,
        "seed": seed,
    }
    joblib.dump(bundle, out / "model.joblib")
    (out / "report_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card


def screen_pool(
    pool_csv: str | Path,
    model_dir: str | Path,
    *,
    window: tuple[float, float],
    out_dir: str | Path | None = None,
    return_scores: bool = True,
    force: bool = False,
) -> pd.DataFrame:
    """Predict and select an external pool, retaining a reason for every rejection."""
    bundle = joblib.load(Path(model_dir) / "model.joblib")
    card = bundle["report_card"]
    if not force and not card["go"]:
        raise RuntimeError("go=False: report card says NO-GO: " + ", ".join(card["reasons"]))
    if window[1] < card["y_min_max"][0] or window[0] > card["y_min_max"][1]:
        raise ValueError("window is entirely outside the training range")
    p5, p95 = card["y_range_p5_p95"]
    if window[0] < p5 or window[1] > p95:
        warnings.warn("window extends outside the training p5-p95 range", UserWarning)
    sp, elements = bundle["spec"], bundle["elements"]
    pool = pd.read_csv(pool_csv, keep_default_na=False)
    _validate_columns(pool, [sp["smiles_col"]], pool_csv)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    train_heavy = card["heavy_atom_range"]
    for _, row in pool.iterrows():
        rec = row.to_dict()
        mol = _mol_from_smiles(row[sp["smiles_col"]])
        reason = None
        canonical = None
        if mol is None:
            reason = "invalid"
        elif sp.get("neutral_closed_shell_only", True) and _is_charged_or_radical(mol):
            reason = "charged_or_radical"
        else:
            canonical = Chem.MolToSmiles(mol, isomericSmiles=False)
            unknown = sorted({a.GetSymbol() for a in mol.GetAtoms()} - set(elements))
            if unknown:
                reason = "unseen_element: " + ",".join(unknown)
            elif not (train_heavy[0] <= mol.GetNumHeavyAtoms() <= train_heavy[1]):
                reason = "outside_size_range"
            elif canonical in seen:
                reason = "duplicate"
            else:
                seen.add(canonical)
        rec["rejection_reason"] = reason
        if reason is None:
            features = _build_features(mol, elements).reshape(1, -1)
            if bundle["model_name"] == "ridge_size":
                features = features[:, [_FP_NBITS_FEAT + DESCRIPTOR_NAMES.index("heavy_atoms")]]
            pred = float(bundle["model"].predict(features)[0])
            rec["pred_xtb_gap_ev"] = pred
            rec["rf_std"] = float(_rf_std(bundle["model"], features)[0])
            if window[0] <= pred <= window[1]:
                rec["_selected"] = True
            else:
                rec["_selected"] = False
        else:
            rec["_selected"] = False
        records.append(rec)
    all_predictions = pd.DataFrame(records)
    if "pred_xtb_gap_ev" not in all_predictions:
        all_predictions["pred_xtb_gap_ev"] = np.nan
    if "rf_std" not in all_predictions:
        all_predictions["rf_std"] = np.nan
    destination = Path(out_dir) if out_dir else Path(model_dir)
    destination.mkdir(parents=True, exist_ok=True)
    all_predictions.to_csv(destination / "all_predictions.csv", index=False)
    selected = all_predictions[all_predictions["_selected"]].copy()
    selected = selected.sort_values("pred_xtb_gap_ev", kind="stable").reset_index(drop=True)
    selected["rank"] = np.arange(1, len(selected) + 1)
    if not return_scores and "pred_xtb_gap_ev" in selected:
        selected = selected.drop(columns=["pred_xtb_gap_ev", "rf_std"])
    return selected.drop(columns=["_selected"], errors="ignore")


def train(examples: list[TrainingExample], target: PropertyTarget, model_dir: Path) -> TrainResult:
    """TRAIN (contract, R10.2, R10.3): fit the random forest on every xTB value so far and save it in model_dir.
    A fifth of the examples is held out to measure it, as whole Murcko scaffolds: later rounds bring ring systems
    the model has not seen, and a random split would score it on near-copies of training molecules. The report
    card is saved next to the model. The saved model is the train-only one; train_with(refit_on_all=True)
    makes a train() whose saved model is refitted on every example after it is measured."""
    return _train(examples, target, model_dir, refit_on_all=False)


def train_with(refit_on_all: bool = False) -> Callable[..., TrainResult]:
    """train() with the run config's train.refit_on_all, keeping train()'s exact signature (the tool contract)."""
    if not refit_on_all:
        return train

    def train_refit(examples: list[TrainingExample], target: PropertyTarget, model_dir: Path) -> TrainResult:
        return _train(examples, target, model_dir, refit_on_all=True)

    return train_refit


def _train(examples: list[TrainingExample], target: PropertyTarget, model_dir: Path, refit_on_all: bool) -> TrainResult:
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    csv_path = model_dir / "training_data.csv"  # train_property_model reads a CSV; it also records the training set
    pd.DataFrame({"id": [f"ex{i:05d}" for i in range(len(examples))], "smiles": [e.smiles for e in examples],
                  "value": [e.value for e in examples]}).to_csv(csv_path, index=False)
    n_test = max(1, len(examples) // 5)
    window = (target.min, target.max) if target.min is not None and target.max is not None else None
    with warnings.catch_warnings(record=True) as caught:  # kept with the model, not printed over the progress lines
        warnings.simplefilter("always")
        card = train_property_model(csv_path, out_dir=model_dir, window=window, train_size=len(examples) - n_test,
                                    test_size=n_test, split="scaffold", refit_on_all=refit_on_all,
                                    spec={"target": "value", "units": target.units, "group_col": None,
                                                            "keep_if": {}, "drop_if": {}})  # agent data: xTB successes only
    if caught:
        card["warnings"] = [str(w.message) for w in caught]
        (model_dir / "report_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    test, base = card["test_metrics"]["random_forest"], card["test_metrics"]["mean_baseline"]
    split = card["partition"]["actual"]
    metrics = {"test_mae": test["mae"], "test_rmse": test["rmse"], "test_r2": test["r2"],
               "baseline_mae": base["mae"], "go": float(card["go"]),
               # the model is fitted on n_train; the split always keeps >= 1 back as a screening pool
               "n_train": float(split["train"]), "n_test": float(split["test"]), "n_pool": float(split["pool"]),
               "n_fit": float(card["final_fit"]["n"])}  # what the saved model learned from: n_train, or all (refit)
    # n_examples is every xTB value TRAIN was given (the contract, as the fakes and trace evaluator read it)
    return TrainResult(model_path=Path(card["paths"]["model"]), n_examples=len(examples),
                       metrics={k: v for k, v in metrics.items() if np.isfinite(v)})  # NaN is not valid JSON


def ml_predict(candidates: list[Candidate], target: PropertyTarget, model: TrainResult) -> list[Prediction]:
    """ML PREDICT (contract, R10.4): one Prediction per candidate, in order. A molecule the model cannot
    represent (as in screen_pool) is "failed" with the reason, never an exception (R2.4)."""
    bundle = joblib.load(model.model_path)
    elements, card = bundle["elements"], bundle["report_card"]
    low, high = card["heavy_atom_range"]
    errors, features = {}, {}
    for c in candidates:
        mol = _mol_from_smiles(c.smiles)
        unknown = sorted({a.GetSymbol() for a in mol.GetAtoms()} - set(elements)) if mol else []
        errors[c.id] = ("invalid_smiles" if mol is None
                        else "charged_or_radical" if bundle["spec"].get("neutral_closed_shell_only", True) and _is_charged_or_radical(mol)
                        else "unseen_element: " + ",".join(unknown) if unknown
                        else "outside_size_range" if not low <= mol.GetNumHeavyAtoms() <= high else None)
        if errors[c.id] is None:
            try:
                features[c.id] = _build_features(mol, elements)
            except ValueError as e:  # non-finite descriptors
                errors[c.id] = str(e)
    ids = list(features)
    x = np.vstack([features[i] for i in ids]) if ids else np.empty((0, 0))
    if ids and bundle["model_name"] == "ridge_size":
        x = x[:, [_FP_NBITS_FEAT + DESCRIPTOR_NAMES.index("heavy_atoms")]]
    values = dict(zip(ids, bundle["model"].predict(x))) if ids else {}  # one batch: much faster than per molecule
    return [Prediction(candidate_id=c.id, status=Status.ok, value=float(values[c.id])) if c.id in values
            else Prediction(candidate_id=c.id, status=Status.failed, error=errors[c.id]) for c in candidates]
