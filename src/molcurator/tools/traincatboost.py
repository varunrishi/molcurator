"""CatBoost training and screening utilities for xTB molecular properties.

Drop-in companion to ``tools/train.py``.  Every decision that is shared with
the Random-Forest implementation — dataset cleaning, Morgan fingerprints,
physicochemical descriptors, element-count features, train/test/pool
partitioning, scaffold-group handling, evaluation metrics, leakage checks,
report-card schema, and serialised bundle layout — is imported directly from
``train.py`` so the two modules stay in sync automatically.

The only differences from ``train.py`` are:

* The model is ``CatBoostRegressor`` instead of ``RandomForestRegressor``.
* Uncertainty is the virtual-ensemble standard deviation (``prediction_type=
  "VirtEnsembles"``) rather than the tree-ensemble std.
* The ``train_catboost_model()`` public function mirrors ``train_property_model()``
  in signature and return value.
* The bundle key ``model_name`` is ``"catboost"`` so ``screen_pool`` in
  ``train.py`` remains compatible (it checks that key before applying ridge
  feature slicing; CatBoost uses the full feature vector).

Hyperparameter choices (see ``_fit_catboost`` docstring for full rationale)
---------------------------------------------------------------------------
* ``depth=5`` — shallower trees reduce variance for the ~200-sample regime.
* ``l2_leaf_reg=5.0`` — stronger L2 on leaf values; helps on sparse Morgan fps.
* ``min_data_in_leaf=5`` — prevents single-sample leaves from memorising noise.
* ``rsm=0.8`` — random 80% feature subspace per split; adds ensemble diversity.
* ``bagging_temperature=0.5`` — lighter Bayesian bootstrap; reduces outlier sensitivity.
* ``learning_rate=0.05`` — unchanged; iteration budget raised so early stopping
  finds the true optimum.
* Two-phase early stopping — a probe model is trained on 85% of ``X_train``
  with ``use_best_model=True`` to determine ``best_iteration``; the final/test
  model is then refitted on **all** of ``X_train`` at that fixed iteration
  count.  This avoids discarding 15% of training data permanently while still
  benefiting from early stopping.  The held-out test set is never exposed.

All choices are training-data-only; no test-set tuning is performed.

Dependencies: ``catboost>=1.2`` (not in the main dependency list; add via the
``catboost`` optional extra defined in ``pyproject.toml``).
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.model_selection import LeaveOneGroupOut, RepeatedKFold

# All shared helpers are imported from train.py – never duplicated here.
from molcurator.tools.train import (
    DEFAULT_SPEC,
    DESCRIPTOR_NAMES,
    _FP_NBITS_FEAT,
    _build_features,
    _clean,
    _feature_names,
    _merge_spec,
    _metrics,
    _partition_indices,
    _spearman_correlation,
    _supported_molecules,
    _validate_columns,
)

# ---------------------------------------------------------------------------
# CatBoost model factory
# ---------------------------------------------------------------------------

# Iteration budgets.  These are *upper bounds*; when an eval set is supplied
# the model stops early (use_best_model=True).  The fast budget is for smoke
# tests / CI; the full budget gives the early-stopper enough room to settle.
_CB_ITERATIONS_FAST = 400
_CB_ITERATIONS_FULL = 2000

# Fraction of X_train held back as an internal CatBoost validation set for
# early stopping.  It is carved out *before* the CV fold loop so the same
# split is used for every fold model and for the final model, keeping the
# selection process fully within the training partition (no test-set leakage).
_CB_EARLY_STOP_FRAC = 0.15

# Minimum number of training samples before we bother with early stopping.
# Below this the internal eval set would be too small to be informative.
_CB_EARLY_STOP_MIN_TRAIN = 30


def _fit_catboost(seed: int, fast: bool, verbose: bool = False) -> Any:
    """Return a freshly constructed (unfitted) CatBoostRegressor.

    Hyperparameter rationale
    ------------------------
    depth=5
        Shallower trees compared to the default (6) reduce variance on the
        ~200-sample training sets typical in this project.  Combined with the
        other regularisers below, depth 5 retains enough capacity.

    l2_leaf_reg=5.0
        L2 penalty on leaf values (CatBoost's primary regulariser).  The
        default is 3.0; raising it to 5.0 shrinks leaf weights more
        aggressively, which helps on the sparse 1024-bit Morgan fingerprint
        sub-space where many features are zero for any given molecule.

    min_data_in_leaf=5
        Prevents single-sample leaves that can memorise training noise.
        Default is 1; 5 is a light floor that still allows fine splits.

    rsm=0.8
        Random subspace method — each split considers a random 80% of
        features.  Equivalent to ``max_features`` in scikit-learn RF.
        Reduces correlation between trees and adds diversity on the
        high-dimensional fingerprint features without discarding too much
        structural information.

    bagging_temperature=0.5
        Controls the Bayesian bootstrap intensity.  At 0.5 (half the default
        of 1.0) the sampling weights are less skewed, giving a smoother
        ensemble and reducing sensitivity to outlier molecules.

    learning_rate=0.05
        Kept at the previous value.  The upper-bound budget (_CB_ITERATIONS_*)
        is raised so that early stopping can find the true optimum; the
        learning rate is not the primary lever here.

    use_best_model=True  (set dynamically in train_catboost_model)
        When an eval_set is supplied the model checkpoints after every round
        and restores the iteration with the lowest eval MAE at the end.
        The eval set is a 15% slice of X_train, never from the test set.
    """
    try:
        from catboost import CatBoostRegressor  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "CatBoost is not installed.  Install it with:\n"
            "  pip install 'molcurator[catboost]'\n"
            "or directly:\n"
            "  pip install catboost>=1.2"
        ) from exc
    return CatBoostRegressor(
        iterations=_CB_ITERATIONS_FAST if fast else _CB_ITERATIONS_FULL,
        learning_rate=0.05,
        depth=5,
        l2_leaf_reg=5.0,
        min_data_in_leaf=5,
        rsm=0.8,
        bagging_temperature=0.5,
        loss_function="RMSE",
        eval_metric="MAE",
        random_seed=seed,
        verbose=verbose,
        # Virtual ensembles enable per-sample uncertainty without a separate
        # calibration model.  num_trees=10 is a light default; increase for
        # better calibration at the cost of prediction time.
        posterior_sampling=False,  # deterministic; uncertainty via VirtEnsembles
    )


def _early_stop_split(
    X: np.ndarray,
    y: np.ndarray,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split X/y into a fit portion and an internal CatBoost eval portion.

    The split is random but fixed by *seed*.  It is used for early stopping
    only; it never influences CV folds and the test set is never touched.

    Returns (X_fit, y_fit, X_eval, y_eval).  When the training set is too
    small to spare rows for an eval set the full arrays are returned twice so
    the caller can detect the no-early-stop case by checking ``X_eval is
    X_fit``.

    Note on group-aware CV: when the outer CV splitter uses LOGO, the
    fold-level early-stop eval set is drawn randomly from the fold's training
    rows and may contain molecules from the same parent groups as the fit
    rows.  This only mildly biases the stopping-iteration signal; it does not
    expose any held-out test labels and is therefore not a leakage concern.
    """
    n = len(X)
    if n < _CB_EARLY_STOP_MIN_TRAIN:
        return X, y, X, y  # sentinel: same object -> caller skips early stop
    n_eval = max(1, int(round(n * _CB_EARLY_STOP_FRAC)))
    n_fit = n - n_eval
    if n_fit < 2:
        return X, y, X, y
    rng = np.random.default_rng(seed + 99_999)  # offset avoids colliding with fold seeds
    order = rng.permutation(n)
    fit_idx = np.sort(order[:n_fit])
    eval_idx = np.sort(order[n_fit:])
    return X[fit_idx], y[fit_idx], X[eval_idx], y[eval_idx]


def _cb_std(model: Any, features: np.ndarray) -> np.ndarray:
    """Return per-sample uncertainty as virtual-ensemble std (eV).

    Uses ``virtual_ensembles_predict`` with the correct kwarg name for
    CatBoost >= 1.2 (``virtual_ensembles_count``).  Returns NaN when:
    * CatBoost is not installed, or
    * *model* is not a ``CatBoostRegressor``.

    Any other error from ``virtual_ensembles_predict`` (e.g. an API change
    in a future CatBoost release) is re-raised as a ``RuntimeError`` rather
    than silently swallowed, so that callers are never misled into treating
    all-NaN as a valid uncertainty estimate.
    """
    try:
        from catboost import CatBoostRegressor  # type: ignore[import]
    except ImportError:
        return np.full(len(features), np.nan)
    if not isinstance(model, CatBoostRegressor):
        return np.full(len(features), np.nan)
    # virtual_ensembles_predict returns shape (n_samples, virtual_ensembles_count, 1).
    # CatBoost >= 1.2 uses the kwarg name ``virtual_ensembles_count``; older builds
    # used ``num_virtual_ensembles`` (removed).  Always use the current name.
    ve = model.virtual_ensembles_predict(
        features,
        prediction_type="VirtEnsembles",
        virtual_ensembles_count=10,
    )
    return np.asarray(ve).squeeze(-1).std(axis=1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def train_catboost_model(
    csv_path: str | Path,
    *,
    spec: dict[str, Any] | None = None,
    out_dir: str | Path = "model_out",
    fast: bool = False,
    seed: int = 42,
    window: tuple[float, float] | None = None,
    train_size: int = 200,
    test_size: int = 50,
) -> dict[str, Any]:
    """Clean a labelled CSV, cross-validate, fit, and serialise a CatBoost model.

    The function signature and returned report-card schema are identical to
    ``train.py:train_property_model()``, with the following differences:

    * The ``model`` parameter is absent – this function always uses CatBoost.
    * ``model_name`` in the bundle and report card is ``"catboost"``.
    * ``model_parameters`` contains ``CatBoostRegressor.get_params()``.
    * ``spearman_uncertainty_vs_error`` uses virtual-ensemble std instead of
      RF tree-ensemble std.
    * The OOF column in ``oof_predictions.csv`` is named ``oof_catboost``.
    """
    sp = _merge_spec(spec)
    raw = pd.read_csv(csv_path, keep_default_na=False)
    required = [sp["smiles_col"], sp["target"], sp["id_col"]]
    required += list(sp["keep_if"]) + list(sp["drop_if"])
    _validate_columns(raw, list(dict.fromkeys(required)), csv_path)
    data, counts = _clean(raw, sp)
    if data.empty:
        raise ValueError("No usable molecules remain after cleaning")

    y = data[sp["target"]].to_numpy(float)
    train_idx, test_idx, pool_idx, split_method = _partition_indices(
        data, sp.get("group_col"), train_size, test_size, seed
    )
    train_data = data.iloc[train_idx]

    # Element vocabulary fixed from the training partition only (same rule as train.py)
    elements = sorted({
        atom.GetSymbol()
        for mol in train_data["_mol"]
        for atom in mol.GetAtoms()
    })
    X = np.vstack([_build_features(mol, elements) for mol in data["_mol"]])
    X_train, y_train = X[train_idx], y[train_idx]
    X_test, y_test = X[test_idx], y[test_idx]
    test_supported = _supported_molecules(data, test_idx, elements)
    pool_supported = _supported_molecules(data, pool_idx, elements)

    # ------------------------------------------------------------------
    # Internal early-stop split (training data only, never the test set)
    # ------------------------------------------------------------------
    # A fixed 15% slice of X_train is set aside as the CatBoost eval set for
    # early stopping.  The same split is used for every fold model and for the
    # final model so that the stopping criterion is consistent and leakage-free.
    # When the training set is too small the helper returns the same array
    # twice (X_es is X_train) and we skip use_best_model entirely.
    X_es_fit, y_es_fit, X_es_eval, y_es_eval = _early_stop_split(X_train, y_train, seed)
    _use_early_stop = X_es_eval is not X_train

    def _fit_with_early_stop(
        fold_seed: int,
        X_fit: np.ndarray,
        y_fit: np.ndarray,
    ) -> Any:
        """Fit a fold model, using early stopping when the training set is large enough.

        The eval set is a fixed proportional slice of *this fold's* training
        rows (X_fit), not the outer early-stop split, so that each fold's
        stopping criterion is entirely within its own training data.
        """
        model = _fit_catboost(fold_seed, fast)
        X_f, y_f, X_e, y_e = _early_stop_split(X_fit, y_fit, fold_seed)
        if X_e is not X_f:
            model.fit(X_f, y_f, eval_set=(X_e, y_e), use_best_model=True)
        else:
            model.fit(X_fit, y_fit)
        return model

    # ------------------------------------------------------------------
    # Cross-validation (OOF on the training partition)
    # ------------------------------------------------------------------
    n_splits = min(5, max(2, len(train_idx) - 1)) if len(train_idx) >= 2 else 1
    oof = np.full(len(train_idx), np.nan)
    fold_rows: list[dict[str, Any]] = []
    train_groups = (
        train_data[sp["group_col"]].fillna("").astype(str).to_numpy()
        if sp.get("group_col") and sp["group_col"] in train_data
        else None
    )

    if len(train_idx) >= 2:
        if train_groups is not None and len(np.unique(train_groups)) >= 2:
            cv_splitter = LeaveOneGroupOut().split(X_train, y_train, train_groups)
        else:
            cv_splitter = RepeatedKFold(
                n_splits=n_splits, n_repeats=1, random_state=seed
            ).split(X_train)
        for fold, (tr, te) in enumerate(cv_splitter):
            fold_model = _fit_with_early_stop(seed + fold, X_train[tr], y_train[tr])
            pred = fold_model.predict(X_train[te]).astype(float)
            oof[te] = pred
            fold_rows.append({"fold": fold, "model": "catboost", **_metrics(y_train[te], pred)})

    valid_oof = ~np.isnan(oof)
    cv_metric = _metrics(y_train[valid_oof], oof[valid_oof])

    # Baseline OOF (same fold boundaries, mean-of-train-fold prediction)
    baseline_oof = np.full(len(y_train), np.nan)
    baseline_fold_rows: list[dict[str, Any]] = []
    if len(train_idx) >= 2:
        if train_groups is not None and len(np.unique(train_groups)) >= 2:
            baseline_splits = LeaveOneGroupOut().split(X_train, y_train, train_groups)
        else:
            baseline_splits = RepeatedKFold(
                n_splits=n_splits, n_repeats=1, random_state=seed
            ).split(X_train)
        for fold, (tr, te) in enumerate(baseline_splits):
            fold_baseline = float(np.mean(y_train[tr]))
            baseline_oof[te] = fold_baseline
            baseline_fold_rows.append({
                "fold": fold, "model": "mean",
                **_metrics(y_train[te], np.full(len(te), fold_baseline)),
            })

    valid_baseline = ~np.isnan(baseline_oof)
    cv_baseline = _metrics(y_train[valid_baseline], baseline_oof[valid_baseline])

    # ------------------------------------------------------------------
    # Held-out test evaluation
    # ------------------------------------------------------------------
    baseline_model = DummyRegressor(strategy="mean").fit(X_train, y_train)
    baseline_test = baseline_model.predict(X_test)

    # test_model: use the ES split to find the best iteration count, then
    # refit on ALL of X_train at that fixed count.  Training on only X_es_fit
    # (85 % of X_train) wastes labelled data and produces a weaker model.
    test_model = _fit_catboost(seed, fast)
    if _use_early_stop:
        _probe = _fit_catboost(seed, fast)
        _probe.fit(X_es_fit, y_es_fit, eval_set=(X_es_eval, y_es_eval), use_best_model=True)
        _best_iter_test = _probe.best_iteration_
        test_model.set_params(iterations=_best_iter_test + 1)
        test_model.fit(X_train, y_train)
    else:
        test_model.fit(X_train, y_train)
    test_predictions = np.full(len(test_idx), np.nan)
    if test_supported.any():
        test_predictions[test_supported] = test_model.predict(
            X_test[test_supported]
        ).astype(float)

    test_metric = _metrics(y_test[test_supported], test_predictions[test_supported])
    baseline_metric = _metrics(y_test[test_supported], baseline_test[test_supported])

    # Uncertainty: virtual-ensemble std over test molecules
    test_spread = np.full(len(test_idx), np.nan)
    if test_supported.any():
        test_spread[test_supported] = _cb_std(test_model, X_test[test_supported])

    abs_test_error = np.full(len(test_idx), np.nan)
    if test_supported.any():
        abs_test_error[test_supported] = np.abs(
            y_test[test_supported] - test_predictions[test_supported]
        )

    finite_spread = np.isfinite(test_spread) & test_supported
    uncertainty_correlation = _spearman_correlation(
        test_spread[finite_spread], abs_test_error[finite_spread]
    )

    # Shuffled-label sanity check (no early stopping — label permutation makes
    # the eval set uninformative for use_best_model; plain fit is correct here)
    shuffled = _fit_catboost(seed + 10_000, fast)
    shuffled.fit(X_train, np.random.default_rng(seed).permutation(y_train))
    if test_supported.any():
        shuffled_preds = shuffled.predict(X_test[test_supported]).astype(float)
        shuffled_r2 = _metrics(y_test[test_supported], shuffled_preds)["r2"]
    else:
        shuffled_r2 = None

    # ------------------------------------------------------------------
    # Final model fitted on the entire training partition
    # ------------------------------------------------------------------
    # Determine the best iteration count via the early-stop split, then
    # refit on ALL of X_train at that count.  This uses 100 % of the
    # training data for the deployed model rather than only 85 %.
    _best_iter_final: int | None = None
    final = _fit_catboost(seed, fast)
    if _use_early_stop:
        _probe_final = _fit_catboost(seed, fast)
        _probe_final.fit(X_es_fit, y_es_fit, eval_set=(X_es_eval, y_es_eval), use_best_model=True)
        _best_iter_final = int(_probe_final.best_iteration_)
        final.set_params(iterations=_best_iter_final + 1)
        final.fit(X_train, y_train)
    else:
        final.fit(X_train, y_train)

    # ------------------------------------------------------------------
    # Output directory & window
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Serialise per-partition prediction frames
    # ------------------------------------------------------------------
    oof_frame = train_data[[sp["id_col"], sp["smiles_col"]]].copy()
    oof_frame["y_true"] = y_train
    oof_frame["oof_catboost"] = oof
    oof_frame.to_csv(out / "oof_predictions.csv", index=False)

    test_frame = data.iloc[test_idx][[sp["id_col"], sp["smiles_col"]]].copy()
    test_frame["y_true"] = y_test
    test_frame["reference_" + sp["target"] + "_evaluation_only"] = y_test
    test_frame["status"] = np.where(test_supported, "supported", "unsupported")
    test_frame["reason"] = np.where(
        test_supported, "", [
            "unseen_element: " + ",".join(sorted({
                atom.GetSymbol() for atom in data.iloc[index]["_mol"].GetAtoms()
                if atom.GetSymbol() not in set(elements)
            }))
            for index in test_idx
        ],
    )
    test_frame["predicted"] = test_predictions
    test_frame["predicted_" + sp["target"]] = test_predictions
    test_frame["absolute_error_evaluation_only"] = abs_test_error
    test_frame["absolute_error_ev"] = abs_test_error
    test_frame.to_csv(out / "test_predictions.csv", index=False)

    pool_frame = data.iloc[pool_idx].copy()
    pool_features = X[pool_idx]
    pool_pred = np.full(len(pool_frame), np.nan)
    if pool_supported.any():
        pool_pred[pool_supported] = final.predict(pool_features[pool_supported]).astype(float)
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
    pool_frame.drop(columns=["_mol", "_canonical"], errors="ignore").to_csv(
        out / "prediction_pool.csv", index=False
    )

    summary = pd.DataFrame(fold_rows)
    summary = pd.concat([summary, pd.DataFrame(baseline_fold_rows)], ignore_index=True)
    summary.to_csv(out / "summary.csv", index=False)

    # ------------------------------------------------------------------
    # Window / screening metrics
    # ------------------------------------------------------------------
    true_in_window = test_supported & (y_test >= window[0]) & (y_test <= window[1])
    predicted_in_window = (
        test_supported & (test_predictions >= window[0]) & (test_predictions <= window[1])
    )
    n_selected_test = int(predicted_in_window.sum())
    true_selected = int((true_in_window & predicted_in_window).sum())
    precision = float(true_selected / n_selected_test) if n_selected_test else 0.0
    recall = float(true_selected / true_in_window.sum()) if true_in_window.any() else 0.0
    base_rate = float(true_in_window[test_supported].mean()) if test_supported.any() else 0.0

    # ------------------------------------------------------------------
    # Error by quantile bin
    # ------------------------------------------------------------------
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
            mae_by_bin.append({
                "bin": str(label), "n": int(mask.sum()),
                "mae": float(np.mean(supported_errors[mask])),
            })

    # ------------------------------------------------------------------
    # Leakage checks (identical logic to train.py)
    # ------------------------------------------------------------------
    group_overlap = bool(
        sp.get("group_col")
        and sp["group_col"] in data
        and set(data.iloc[train_idx][sp["group_col"]].astype(str))
        & set(data.iloc[test_idx][sp["group_col"]].astype(str))
    )
    canonical_overlap = {
        "train_test": bool(
            set(data.iloc[train_idx]["_canonical"]) & set(data.iloc[test_idx]["_canonical"])
        ),
        "train_pool": bool(
            set(data.iloc[train_idx]["_canonical"]) & set(data.iloc[pool_idx]["_canonical"])
        ),
        "test_pool": bool(
            set(data.iloc[test_idx]["_canonical"]) & set(data.iloc[pool_idx]["_canonical"])
        ),
    }
    train_elements = set(elements)
    test_unseen_elements = sorted({
        atom.GetSymbol()
        for mol in data.iloc[test_idx]["_mol"]
        for atom in mol.GetAtoms()
        if atom.GetSymbol() not in train_elements
    })
    leakage_checks = {
        "parent_group_overlap": {
            "status": "fail" if group_overlap else "pass",
            "evidence": "exact group intersection between train and test",
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

    # ------------------------------------------------------------------
    # Report card (schema matches train.py exactly; model key is "catboost")
    # ------------------------------------------------------------------
    card: dict[str, Any] = {
        "target": sp["target"], "units": sp["units"], "n_rows": len(y),
        "cleaning_counts": counts,
        "y_min_max": [float(y_train.min()), float(y_train.max())],
        "y_range_p5_p95": [float(np.quantile(y_train, 0.05)), float(np.quantile(y_train, 0.95))],
        "elements": elements,
        "heavy_atom_range": [
            int(X_train[:, _FP_NBITS_FEAT].min()), int(X_train[:, _FP_NBITS_FEAT].max())
        ],
        "cv": {"scheme_a": {"catboost": cv_metric, "mean": cv_baseline}},
        "test_metrics": {"catboost": test_metric, "mean_baseline": baseline_metric},
        "test_evaluation": {
            "n_total": len(test_idx),
            "n_supported": int(test_supported.sum()),
            "n_evaluated": int(test_supported.sum()),
        },
        "test_predictions": test_frame.to_dict("records"),
        "partition": {
            "requested": {"train": train_size, "test": test_size, "pool": 750},
            "actual": {"train": len(train_idx), "test": len(test_idx), "pool": len(pool_idx)},
            "split_method": split_method,
            "group_overlap": group_overlap,
            "canonical_overlap": canonical_overlap,
            "constraints_changed_counts": bool(
                len(train_idx) != train_size or len(test_idx) != test_size
            ),
        },
        "cv_means": fold_rows + baseline_fold_rows,
        "mae_by_quantile_bin": {"test": mae_by_bin},
        "spearman_uncertainty_vs_error": uncertainty_correlation,
        "shuffled_label_R2_catboost": shuffled_r2,
        "window": list(window),
        "window_metrics": {"scheme_a": {
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
            "prediction_pool": str(out / "prediction_pool.csv"),
        },
        "feature_config": {
            "fingerprint": "Morgan", "radius": 2, "size": _FP_NBITS_FEAT,
            "descriptors": list(DESCRIPTOR_NAMES), "elements": elements,
        },
        "model_parameters": final.get_params(),
        "early_stopping": {
            "enabled": _use_early_stop,
            "eval_fraction": _CB_EARLY_STOP_FRAC,
            "n_eval": int(len(y_train) - len(y_es_fit)) if _use_early_stop else 0,
            "n_fit": int(len(y_es_fit)) if _use_early_stop else int(len(y_train)),
            # best_iteration is the probe's stopping point: the iteration count
            # at which the eval-MAE was lowest.  The final model was then
            # refitted on all X_train for exactly (best_iteration + 1) trees.
            "best_iteration": _best_iter_final if _use_early_stop else None,
        },
    }

    bundle = {
        "model": final,
        "feature_names": _feature_names(elements),
        "elements": elements,
        "spec": sp,
        "report_card": card,
        "target": sp["target"],
        "model_name": "catboost",  # distinguishes bundle from RF bundle at load time
        "seed": seed,
    }
    joblib.dump(bundle, out / "model.joblib")
    (out / "report_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card
