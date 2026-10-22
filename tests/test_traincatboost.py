"""tools/traincatboost.py: train_catboost_model() matches the report-card contract
of train_property_model() and all leakage invariants hold.

Tests are structured to mirror test_train.py so that any divergence between
the two training functions is immediately visible.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from rdkit import Chem

pytest.importorskip("catboost")

from molcurator.tools.traincatboost import (
    _CB_EARLY_STOP_FRAC,
    _CB_EARLY_STOP_MIN_TRAIN,
    _early_stop_split,
    _fit_catboost,
    train_catboost_model,
)


# ---------------------------------------------------------------------------
# Shared synthetic dataset fixture
# ---------------------------------------------------------------------------

def _make_csv(path: Path, n: int = 80, groups: int = 4) -> Path:
    """Write a learnable labelled CSV; returns the path."""
    smiles_base = [
        head + "C" * k
        for k in range(1, (n // (4 * groups)) + 2)
        for head in ("", "O", "N", "c1ccccc1")
    ]
    rows = []
    rng = np.random.default_rng(0)
    for i in range(n):
        smi = smiles_base[i % len(smiles_base)]
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            continue
        ha = mol.GetNumHeavyAtoms()
        y = 6.0 - 0.15 * ha + 0.5 * any(a.GetIsAromatic() for a in mol.GetAtoms())
        y += float(rng.normal(0, 0.05))
        rows.append({
            "id": f"m{i:04d}",
            "smiles": smi,
            "xtb_gap_ev": y,
            "status": "ok",
            "fractional_occupation": False,
            "parent_mol_id": f"grp_{i % groups}",
        })
    csv = path / "data.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    return csv


# ---------------------------------------------------------------------------
# _early_stop_split invariants
# ---------------------------------------------------------------------------

class TestEarlyStopSplit:
    def test_sentinel_when_too_small(self):
        """Below _CB_EARLY_STOP_MIN_TRAIN the sentinel is returned."""
        n = _CB_EARLY_STOP_MIN_TRAIN - 1
        X = np.eye(n)
        y = np.ones(n)
        Xf, yf, Xe, ye = _early_stop_split(X, y, 0)
        assert Xe is X and Xf is X  # same object = sentinel

    def test_splits_at_threshold(self):
        """Exactly at the minimum threshold a real split is returned."""
        n = _CB_EARLY_STOP_MIN_TRAIN
        X = np.eye(n)
        y = np.ones(n)
        Xf, yf, Xe, ye = _early_stop_split(X, y, 0)
        assert Xe is not X
        assert len(Xf) + len(Xe) == n

    def test_eval_fraction_is_correct(self):
        """Eval fraction matches _CB_EARLY_STOP_FRAC to ±1 row."""
        n = 200
        X = np.random.default_rng(7).standard_normal((n, 5))
        y = np.ones(n)
        _, _, Xe, _ = _early_stop_split(X, y, 42)
        expected = round(n * _CB_EARLY_STOP_FRAC)
        assert abs(len(Xe) - expected) <= 1

    def test_reproducible_with_same_seed(self):
        """Two calls with the same seed return identical arrays."""
        X = np.random.default_rng(1).standard_normal((100, 10))
        y = np.arange(100, dtype=float)
        Xf1, yf1, Xe1, ye1 = _early_stop_split(X, y, 99)
        Xf2, yf2, Xe2, ye2 = _early_stop_split(X, y, 99)
        assert np.array_equal(Xf1, Xf2) and np.array_equal(Xe1, Xe2)

    def test_different_seeds_give_different_splits(self):
        X = np.random.default_rng(2).standard_normal((100, 10))
        y = np.arange(100, dtype=float)
        Xf_a, *_ = _early_stop_split(X, y, 0)
        Xf_b, *_ = _early_stop_split(X, y, 1)
        assert not np.array_equal(Xf_a, Xf_b)

    def test_no_overlap_between_fit_and_eval(self):
        """Row indices in fit and eval must be disjoint."""
        X = np.arange(100).reshape(100, 1).astype(float)
        y = np.ones(100)
        Xf, _, Xe, _ = _early_stop_split(X, y, 5)
        # X values are unique (0..99), so check uniqueness via set intersection
        fit_vals = set(Xf[:, 0].tolist())
        eval_vals = set(Xe[:, 0].tolist())
        assert not (fit_vals & eval_vals)

    def test_union_equals_input(self):
        """fit + eval rows together cover the full input."""
        n = 80
        X = np.arange(n).reshape(n, 1).astype(float)
        y = np.ones(n)
        Xf, _, Xe, _ = _early_stop_split(X, y, 3)
        combined = sorted(Xf[:, 0].tolist() + Xe[:, 0].tolist())
        assert combined == list(range(n))


# ---------------------------------------------------------------------------
# _fit_catboost factory
# ---------------------------------------------------------------------------

class TestFitCatboost:
    def test_hyperparameters_match_spec(self):
        """The factory must set the documented hyperparameter values."""
        m = _fit_catboost(seed=0, fast=True)
        p = m.get_params()
        assert p["depth"] == 5
        assert p["l2_leaf_reg"] == 5.0
        assert p["min_data_in_leaf"] == 5
        assert math.isclose(p["rsm"], 0.8, rel_tol=1e-6)
        assert math.isclose(p["bagging_temperature"], 0.5, rel_tol=1e-6)
        assert math.isclose(p["learning_rate"], 0.05, rel_tol=1e-6)
        assert p["posterior_sampling"] is False

    def test_fast_budget_smaller_than_full(self):
        fast = _fit_catboost(seed=0, fast=True).get_params()["iterations"]
        full = _fit_catboost(seed=0, fast=False).get_params()["iterations"]
        assert fast < full

    def test_different_seeds_produce_different_predictions(self):
        """Seeds must affect the random number stream (regression guard)."""
        X = np.random.default_rng(9).standard_normal((50, 20))
        y = X[:, 0] * 2 + 1
        m1 = _fit_catboost(seed=0, fast=True)
        m2 = _fit_catboost(seed=1, fast=True)
        m1.fit(X, y)
        m2.fit(X, y)
        pred1 = m1.predict(X)
        pred2 = m2.predict(X)
        # Very unlikely to be identical with different seeds on a real dataset
        assert not np.allclose(pred1, pred2)

    def test_early_stop_fit_terminates(self, tmp_path):
        """Fitting with an eval_set and use_best_model=True must not raise."""
        X = np.random.default_rng(10).standard_normal((60, 30))
        y = X[:, 0] + 0.1 * np.random.default_rng(10).standard_normal(60)
        Xf, yf, Xe, ye = _early_stop_split(X, y, 0)
        assert Xe is not X  # ensure early stop is triggered (n=60 >= threshold)
        m = _fit_catboost(seed=0, fast=True)
        m.fit(Xf, yf, eval_set=(Xe, ye), use_best_model=True)
        assert hasattr(m, "best_iteration_")
        assert m.best_iteration_ >= 0


# ---------------------------------------------------------------------------
# train_catboost_model — report-card contract
# ---------------------------------------------------------------------------

class TestTrainCatboostModel:
    def test_report_card_has_required_keys(self, tmp_path):
        csv = _make_csv(tmp_path)
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=42,
            train_size=40, test_size=10,
        )
        required = {
            "target", "units", "n_rows", "cv", "test_metrics",
            "partition", "elements", "feature_config", "model_parameters",
            "leakage_checks", "no_leak", "go", "checks", "early_stopping",
        }
        assert required <= set(card.keys()), (
            f"Missing keys: {required - set(card.keys())}"
        )

    def test_model_parameters_match_factory(self, tmp_path):
        """model_parameters in the card must reflect the actual factory values."""
        csv = _make_csv(tmp_path)
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=42,
            train_size=40, test_size=10,
        )
        p = card["model_parameters"]
        assert p["depth"] == 5
        assert p["l2_leaf_reg"] == 5.0
        assert p["min_data_in_leaf"] == 5

    def test_beats_mean_baseline(self, tmp_path):
        """CatBoost must beat the mean baseline on this learnable dataset."""
        csv = _make_csv(tmp_path, n=80)
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=42,
            train_size=40, test_size=10,
        )
        cb_mae = card["test_metrics"]["catboost"]["mae"]
        bl_mae = card["test_metrics"]["mean_baseline"]["mae"]
        assert cb_mae < bl_mae, (
            f"CatBoost MAE {cb_mae:.4f} did not beat baseline {bl_mae:.4f}"
        )

    def test_no_leakage_flags(self, tmp_path):
        csv = _make_csv(tmp_path)
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=42,
            train_size=40, test_size=10,
        )
        assert card["no_leak"] is True
        for check_name, check in card["leakage_checks"].items():
            assert check["status"] == "pass", (
                f"Leakage check '{check_name}' failed: {check}"
            )

    def test_canonical_smiles_deduplication(self, tmp_path):
        """Duplicate SMILES (canonical) must not appear in both train and test."""
        # Write a CSV with explicit duplicates
        rows = []
        for i in range(50):
            smi = "C" * (i % 8 + 1)  # only 8 unique SMILES
            rows.append({
                "id": f"m{i:03d}", "smiles": smi, "xtb_gap_ev": float(i % 8),
                "status": "ok", "fractional_occupation": False,
            })
        csv = tmp_path / "dupes.csv"
        pd.DataFrame(rows).to_csv(csv, index=False)
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=0,
            train_size=4, test_size=2,
            spec={"group_col": None},
        )
        assert card["leakage_checks"]["canonical_smiles_overlap"]["status"] == "pass"

    def test_output_files_are_written(self, tmp_path):
        csv = _make_csv(tmp_path)
        out = tmp_path / "out"
        train_catboost_model(
            csv, out_dir=out, fast=True, seed=42,
            train_size=40, test_size=10,
        )
        for fname in ("model.joblib", "report_card.json",
                      "oof_predictions.csv", "test_predictions.csv",
                      "prediction_pool.csv", "summary.csv"):
            assert (out / fname).is_file(), f"Missing output: {fname}"

    def test_report_card_json_is_valid(self, tmp_path):
        """report_card.json must be valid JSON with no NaN/Inf literals."""
        csv = _make_csv(tmp_path)
        out = tmp_path / "out"
        train_catboost_model(
            csv, out_dir=out, fast=True, seed=42,
            train_size=40, test_size=10,
        )
        text = (out / "report_card.json").read_text(encoding="utf-8")
        parsed = json.loads(text)  # raises if invalid JSON
        assert "target" in parsed

    def test_bundle_model_name_is_catboost(self, tmp_path):
        """The serialised bundle must carry model_name='catboost'."""
        import joblib
        csv = _make_csv(tmp_path)
        out = tmp_path / "out"
        train_catboost_model(
            csv, out_dir=out, fast=True, seed=42,
            train_size=40, test_size=10,
        )
        bundle = joblib.load(out / "model.joblib")
        assert bundle["model_name"] == "catboost"

    def test_unseen_element_handled_gracefully(self, tmp_path):
        """A test molecule with an unseen element must be excluded, not raise."""
        rows = []
        for i in range(60):
            smi = "C" * (i % 6 + 2) + ("O" if i % 3 == 0 else "")
            rows.append({
                "id": f"m{i:03d}", "smiles": smi, "xtb_gap_ev": float(i % 5),
                "status": "ok", "fractional_occupation": False,
                "parent_mol_id": f"g{i % 4}",
            })
        # Add a molecule with Si (not in training set)
        rows.append({
            "id": "mSi", "smiles": "[SiH4]", "xtb_gap_ev": 3.0,
            "status": "ok", "fractional_occupation": False,
            "parent_mol_id": "g0",
        })
        csv = tmp_path / "unseen.csv"
        pd.DataFrame(rows).to_csv(csv, index=False)
        # Force the Si molecule into the test set by using a fixed seed and small sizes
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=0,
            train_size=40, test_size=20,
        )
        # Must complete without raising; unseen-element molecules appear in
        # test_unseen_elements when they end up in the test partition.
        assert isinstance(card["test_unseen_elements"], list)

    def test_partition_sizes_recorded(self, tmp_path):
        csv = _make_csv(tmp_path, n=80)
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=42,
            train_size=40, test_size=10,
        )
        actual = card["partition"]["actual"]
        assert actual["train"] >= 1
        assert actual["test"] >= 1
        assert actual["pool"] >= 0

    def test_early_stopping_info_in_card(self, tmp_path):
        """The early_stopping dict must always be present with the right shape."""
        csv = _make_csv(tmp_path, n=80)
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=42,
            train_size=40, test_size=10,
        )
        es = card["early_stopping"]
        assert isinstance(es["enabled"], bool)
        assert isinstance(es["eval_fraction"], float)
        assert isinstance(es["n_fit"], int)
        assert isinstance(es["n_eval"], int)
        # best_iteration is int when enabled, None otherwise
        if es["enabled"]:
            assert isinstance(es["best_iteration"], int)
        else:
            assert es["best_iteration"] is None

    def test_cv_metrics_finite(self, tmp_path):
        """CV metrics must be finite numbers, not NaN or Inf."""
        csv = _make_csv(tmp_path, n=80)
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=42,
            train_size=40, test_size=10,
        )
        for key, m in card["cv"]["scheme_a"].items():
            for metric, val in m.items():
                assert math.isfinite(val), (
                    f"CV metric cv.scheme_a.{key}.{metric} = {val} is not finite"
                )

    def test_feature_config_preserved(self, tmp_path):
        """Feature configuration must match the production values."""
        csv = _make_csv(tmp_path)
        card = train_catboost_model(
            csv, out_dir=tmp_path / "out", fast=True, seed=42,
            train_size=40, test_size=10,
        )
        fc = card["feature_config"]
        assert fc["fingerprint"] == "Morgan"
        assert fc["radius"] == 2
        assert fc["size"] == 1024
