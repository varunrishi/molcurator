"""tools/train.py: train() and ml_predict() keep the tool contract the agent relies on (Phase 2, R10.2-R10.4, R2.4)."""
import pandas as pd
import pytest
from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold

from molcurator.config import load_config
from molcurator.schemas import Candidate, Status, TrainingExample
import json

from molcurator.tools.train import ml_predict, train, train_property_model, train_with
from tests.agent.test_graph import CONFIG


def test_train_then_ml_predict_keeps_the_contract(tmp_path):
    smiles = [head + "C" * n for n in range(1, 17) for head in ("", "O", "N", "c1ccccc1", "c1ccncc1")]  # 80 small molecules
    mols = [Chem.MolFromSmiles(s) for s in smiles]
    examples = [TrainingExample(smiles=s, value=6.0 - 0.15 * m.GetNumHeavyAtoms() + 0.5 * any(a.GetIsAromatic() for a in m.GetAtoms()))
                for s, m in zip(smiles, mols)]  # a simple, learnable "gap"
    target = load_config(CONFIG).target
    model = train(examples, target, tmp_path / "round-1")
    assert model.model_path.is_file() and {"test_mae", "go"} <= set(model.metrics)
    assert model.n_examples == 80 == sum(model.metrics[k] for k in ("n_train", "n_test", "n_pool"))  # all given
    assert model.metrics["test_mae"] < model.metrics["baseline_mae"]  # it learned something
    candidates = [Candidate(id=f"c{i}", smiles=s, parent_smiles="C", round=2, generator="stoned_selfies")
                  for i, s in enumerate(["CCCCCO", "[se]1cccc1", "c1ccccc1CCC"])]
    results = ml_predict(candidates, target, model)
    assert [r.candidate_id for r in results] == ["c0", "c1", "c2"]  # one per candidate, in order (R2.4)
    assert [r.status for r in results] == [Status.ok, Status.failed, Status.ok]
    assert results[1].error == "unseen_element: Se" and results[0].value is not None


def test_scaffold_split_keeps_each_scaffold_in_one_partition(tmp_path):
    rings = ["c1ccccc1", "c1ccncc1", "C1CCCCC1", "c1ccsc1", "c1ccoc1", "c1ccc2ccccc2c1", "C1CCNCC1", "c1cncnc1"]
    smiles = [ring + "C" * n for ring in rings for n in range(1, 11)]  # 8 scaffolds x 10 molecules
    rows = [{"id": f"m{i:03d}", "smiles": s, "xtb_gap_ev": 6.0 - 0.15 * Chem.MolFromSmiles(s).GetNumHeavyAtoms(),
             "status": "ok", "fractional_occupation": False, "parent_mol_id": f"seed{i % 2}"}  # parents cross scaffolds
            for i, s in enumerate(smiles)]
    csv_path = tmp_path / "data.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    card = train_property_model(csv_path, out_dir=tmp_path / "model", fast=True, split="scaffold",
                                train_size=0.7, val_size=0.15, test_size=0.15)  # fractions of the 80 molecules
    assert card["partition"]["requested"] == {"train": 56, "val": 12, "test": 12, "pool": 0}
    assert card["partition"]["split_method"] == "scaffold split (Bemis-Murcko)" and card["partition"]["n_groups"] == 8
    assert card["leakage_checks"]["scaffold_group_overlap"]["status"] == "pass"  # parent overlap is not a leak here
    partition = pd.read_csv(tmp_path / "model" / "partition.csv")
    assert {"train", "val", "test"} <= set(partition["split"]) and len(partition) == 80
    assert (partition.groupby("group")["split"].nunique() == 1).all()  # no scaffold in two partitions
    assert partition["group"].tolist() == [MurckoScaffold.MurckoScaffoldSmiles(s) for s in partition["smiles"]]
    validation = pd.read_csv(tmp_path / "model" / "validation_predictions.csv")
    assert len(validation) == card["partition"]["actual"]["val"] == card["validation_evaluation"]["n_total"]
    assert set(validation["id"]) == set(partition.loc[partition["split"] == "val", "id"])
    assert card["validation_metrics"]["random_forest"]["mae"] >= 0


def test_default_split_has_no_validation_set(tmp_path):
    rows = [{"id": f"m{i:03d}", "smiles": "C" * n + head, "xtb_gap_ev": 6.0 - 0.1 * n, "status": "ok",
             "fractional_occupation": False, "parent_mol_id": f"seed{n % 4}"}
            for i, (n, head) in enumerate((n, head) for n in range(1, 16) for head in ("", "O"))]
    csv_path = tmp_path / "data.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    card = train_property_model(csv_path, out_dir=tmp_path / "model", fast=True, train_size=20, test_size=5)
    assert card["partition"]["actual"]["val"] == 0 and card["validation_metrics"] is None
    assert card["partition"]["split_method"] == "parent-group-aware split"
    assert "parent_group_overlap" in card["leakage_checks"]
    assert not (tmp_path / "model" / "validation_predictions.csv").exists()


def test_fractional_sizes_must_sum_to_at_most_one(tmp_path):
    csv_path = tmp_path / "data.csv"
    pd.DataFrame([{"id": f"m{n}", "smiles": "C" * n, "xtb_gap_ev": 6.0 - 0.1 * n, "status": "ok",
                   "fractional_occupation": False, "parent_mol_id": f"seed{n % 3}"} for n in range(1, 21)]).to_csv(csv_path, index=False)
    with pytest.raises(ValueError, match="sum to at most 1"):
        train_property_model(csv_path, out_dir=tmp_path / "model", fast=True, train_size=0.8, test_size=0.3)


def test_refit_on_all_is_optional_and_fits_the_saved_model_on_every_example(tmp_path):
    """train.refit_on_all: off by default (saved model = the measured train-only one); on, the saved model is
    refitted on all examples after measuring, while n_examples, the split and the test metrics stay the same."""
    smiles = [head + "C" * n for n in range(1, 21) for head in ("", "O", "N", "c1ccccc1")]
    examples = [TrainingExample(smiles=s, value=6.0 - 0.15 * Chem.MolFromSmiles(s).GetNumHeavyAtoms()) for s in smiles]
    target = load_config(CONFIG).target
    assert train_with(False) is train  # the default is the plain contract function
    plain, refit = train(examples, target, tmp_path / "plain"), train_with(True)(examples, target, tmp_path / "refit")
    assert plain.metrics["n_fit"] == plain.metrics["n_train"] < 80  # saved model: training split only
    assert refit.metrics["n_fit"] == 80  # saved model: every example
    for key in ("n_train", "n_test", "n_pool", "test_mae", "baseline_mae"):
        assert refit.metrics[key] == pytest.approx(plain.metrics[key])  # same split and measurement (parallel-sum noise)
    assert refit.n_examples == plain.n_examples == 80
    card = json.loads((tmp_path / "refit" / "report_card.json").read_text())
    assert card["final_fit"] == {"refit_on_all": True, "n": 80}


def test_train_model_option_defaults_to_catboost():
    """train.model: CatBoost unless the config names the random forest; anything else is rejected."""
    from molcurator.config import TrainSettings
    assert TrainSettings().model == "catboost" and train_with(False, "catboost") is train
    assert train_with(False, "random_forest") is not train
    with pytest.raises(ValueError):
        TrainSettings(model="xgboost")
