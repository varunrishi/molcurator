"""The real tools load and match the tool contract, so `molcurator run` can start (Phase 2, R2.2)."""
import inspect

from molcurator.agent.toolset import Toolset

CONTRACT = {  # parameter names of each tool, from the contract in tools/*.py and schemas.py
    "generate": ["parents", "settings", "round", "rng_seed"],
    "predict": ["candidates", "target", "xyz_dir"],
    "train": ["examples", "target", "model_dir"],
    "ml_predict": ["candidates", "target", "model"],
    "validate": ["items", "target", "qm"],
    "curate": ["entries", "run_dir"],
}


def test_default_toolset_has_every_contract_function():
    """R2.2: a tool PR that removes or reshapes a contract function fails here, not in a real run."""
    tools = Toolset.default()  # imports the real tool modules, exactly as run_agent does
    for name, params in CONTRACT.items():
        assert list(inspect.signature(getattr(tools, name)).parameters) == params, f"{name} breaks the tool contract"
