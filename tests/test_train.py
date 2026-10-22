"""tools/train.py: train() and ml_predict() keep the tool contract the agent relies on (Phase 2, R10.2-R10.4, R2.4)."""
from rdkit import Chem

from molcurator.config import load_config
from molcurator.schemas import Candidate, Status, TrainingExample
from molcurator.tools.train import ml_predict, train
from tests.agent.test_graph import CONFIG


def test_train_then_ml_predict_keeps_the_contract(tmp_path):
    smiles = [head + "C" * n for n in range(1, 21) for head in ("", "O", "N", "c1ccccc1")]  # 80 small molecules
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
