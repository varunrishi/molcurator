"""The on-top xTB correction: PREDICT turns calculated xTB gaps into DFT-like ones (predict.correction)."""
import csv

import pytest

from molcurator.agent.nodes import xtb_fields
from molcurator.agent.runner import run_agent
from molcurator.agent.toolset import Toolset
from molcurator.config import RunConfig, load_config
from tests.agent.test_graph import CONFIG, FakeToolsRealCurate, raw_config


def test_xtb_fields_correct_and_flag_out_of_range_values():
    """slope * xTB + intercept; xtb_raw keeps the calculation; values outside the fitted range are flagged."""
    c = load_config(CONFIG)
    slope, intercept = c.predict.correction.slope, c.predict.correction.intercept
    assert xtb_fields(2.0, c) == {"xtb": pytest.approx(slope * 2.0 + intercept), "xtb_raw": 2.0,
                                  "xtb_extrapolated": False}
    assert xtb_fields(0.1, c)["xtb_extrapolated"] is True  # below the fitted xTB range
    assert xtb_fields(None, c) == {"xtb": None, "xtb_raw": None, "xtb_extrapolated": None}  # a failed xTB run
    assert xtb_fields(2.0, raw_config()) == {"xtb": 2.0, "xtb_raw": 2.0, "xtb_extrapolated": False}


class SpyTools(FakeToolsRealCurate):
    """Fake chemistry whose raw xTB values (around 1.45 eV) correct to around the 4.0-4.5 eV window, some from
    below the fitted xTB range (extrapolated); records TRAIN's data."""

    def __init__(self):
        super().__init__(value_center=1.45, value_spread=0.8)
        self.trained_on = []

    def train(self, examples, target, model_dir):
        self.trained_on = [e.value for e in examples]
        return super().train(examples, target, model_dir)


def corrected_run(tmp_path, **target) -> tuple[RunConfig, SpyTools, dict]:
    """One fake round of 1000 candidates with the shipped config's correction, optionally another window."""
    data = load_config(CONFIG).model_dump()
    data["generation"]["defaults"]["n_candidates"] = 1000
    data["budget"].update(max_rounds=1, target_dataset_size=1000)
    data["target"].update(target)
    config, tools = RunConfig.model_validate(data), SpyTools()
    return config, tools, run_agent(config, tools=Toolset.from_object(tools), runs_root=tmp_path, run_id="c")


def test_shipped_config_trains_and_curates_on_corrected_values(tmp_path):
    """With configs/homo_lumo.yaml's correction, TRAIN learns from corrected values only; the dataset holds the
    corrected xtb (inside the user's window) and the raw value."""
    config, tools, state = corrected_run(tmp_path)
    measured = [m for m in state["molecules"].values() if m["xtb_raw"] is not None]
    assert sorted(tools.trained_on) == pytest.approx(sorted(m["xtb"] for m in measured))  # corrected, not raw
    c = config.predict.correction
    with (tmp_path / "c" / "dataset.csv").open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["xtb"]]
    assert rows
    for r in rows:
        assert float(r["xtb"]) == pytest.approx(c.slope * float(r["xtb_raw"]) + c.intercept)
        assert config.target.min <= float(r["xtb"]) <= config.target.max  # the user's window, read as DFT-like
        assert r["xtb_extrapolated"] == "False" and c.xtb_range[0] <= float(r["xtb_raw"]) <= c.xtb_range[1]


def test_extrapolated_values_are_not_curated(tmp_path):
    """A window below the correction's fitted range (corrected < ~3.94 eV) is reached only by extrapolated values:
    they are screened but too uncertain to curate. (ML-only molecules carry no flag and can still be.)"""
    config, _, state = corrected_run(tmp_path, min=3.0, max=3.5)
    in_window = [m for m in state["molecules"].values()
                 if m["xtb"] is not None and config.target.min <= m["xtb"] <= config.target.max]
    assert in_window and all(m["xtb_extrapolated"] and m["status"] != "curated" for m in in_window)
    assert all(m["xtb"] is None for m in state["molecules"].values() if m["status"] == "curated")


def test_correction_is_rejected_for_other_properties():
    """The correction is fitted on HOMO-LUMO gaps only, so a config pairing it with another target fails to load."""
    tadf = load_config(CONFIG.parent / "tadf.yaml").model_dump()  # target s1_t1_gap, no correction: loads
    tadf["predict"]["correction"] = load_config(CONFIG).predict.correction.model_dump()
    with pytest.raises(ValueError, match="applies to homo_lumo_gap only, not 's1_t1_gap'"):
        RunConfig.model_validate(tadf)


@pytest.mark.parametrize("method,ok", [(None, True), ("gfn2-xtb", True), ("GFN2-xTB", True), ("gfn1-xtb", False),
                                       ("B97-3c", False)])
def test_correction_needs_gfn2_xtb_predict(method, ok):
    """The correction is fitted on GFN2-xTB gaps, so another PREDICT method (predict.method) is refused with it."""
    data = load_config(CONFIG).model_dump()
    data["predict"]["method"] = method
    if ok:
        assert RunConfig.model_validate(data).predict.correction is not None
    else:
        with pytest.raises(ValueError, match="fitted for GFN2-xTB"):
            RunConfig.model_validate(data)
