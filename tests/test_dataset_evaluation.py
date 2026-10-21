"""Synthetic evidence and structural-quality tests; no electronic calculations."""
import copy
import csv
import json

import pytest

from molcurator.evaluation import evaluate_dataset, load_records, write_reports
from molcurator.schemas import PropertyTarget

METHOD = "dft:B3LYP/def2-SVP"
TARGET = PropertyTarget(name="homo_lumo_gap", min=3, max=3.5)


def csv_row(cid="a", smiles="CCO", value="3.25", **changes):
    return dict(dataset="synthetic", candidate_id=cid, smiles=smiles, qm_method=METHOD,
                status="ok", orca_gap_ev=value, reference_method="B3LYP/def2-SVP",
                source_csv="original.csv", **changes)


def evaluate(rows, **kwargs):
    return evaluate_dataset(rows, target=kwargs.pop("target", TARGET),
                            qm_method=METHOD, profile=kwargs.pop("profile", "csv"), **kwargs)


def curated(cid="a", **changes):
    row = dict(id=cid, smiles="CCO", properties={METHOD: 3.25}, validated=True,
               xyz_path=None, provenance=dict(seed="C", parent="CC", generator="test", round="1"))
    return dict(row, **changes)


def qm(cid="a", **changes):
    return dict(dict(candidate_id=cid, method=METHOD, status="ok", value=3.25, error=None), **changes)


def test_validity_equivalent_smiles_duplicates_and_id_preservation():
    rows = [csv_row("a"), csv_row("a", "OCC"), csv_row("b", ""), csv_row("c", "C1CC")]
    original = copy.deepcopy(rows)
    report = evaluate(rows)
    assert rows == original
    assert len(report["molecules"]) == 4
    summary = report["summary"]
    assert summary["validity"] == dict(numerator=2, denominator=4, value=.5)
    assert summary["unique_exact"] == 1
    assert summary["duplicate_id_rows"] == 1
    assert summary["duplicate_exact_rows"] == 1
    assert report["molecules"][1]["duplicate_id_of_row"] == 1
    assert all(row["qm_outcome"] == "not_assessable" for row in report["molecules"])


def test_stereo_policy_and_multiple_seeds():
    rows = [csv_row("a", "C[C@H](O)F"), csv_row("b", "C[C@@H](O)F"), csv_row("c", "CCO")]
    summary = evaluate(rows, seeds=["CCO", "C[C@H](O)F"])["summary"]
    assert summary["unique_exact"] == 3
    assert summary["unique_no_stereo"] == 2
    assert summary["seed_overlap_exact"] == 2
    assert summary["seed_overlap_no_stereo"] == 3


def test_absent_and_invalid_seeds():
    report = evaluate([csv_row()])
    assert report["summary"]["seed_overlap_exact"] is None
    assert report["molecules"][0]["max_seed_tanimoto"] is None
    with pytest.raises(ValueError):
        evaluate([], seeds=["not-smiles"])


def test_repeated_seeds_are_counted_as_duplicate_molecules():
    summary = evaluate([csv_row("a"), csv_row("b", "OCC")], seeds=["CCO"])["summary"]
    assert summary["seed_overlap_exact"] == 2
    assert summary["duplicate_exact_rows"] == 1
    assert summary["unique_exact"] == 1


def test_exported_hit_flag_is_recomputed():
    row = dict(csv_row(value="4"), true_hit="True")
    assert evaluate([row])["molecules"][0]["qm_outcome"] == "outside_target"


@pytest.mark.parametrize("value,outcome", [("3", "meets_target"), ("3.5", "meets_target"),
    ("2.99", "outside_target"), ("3.51", "outside_target"), ("", "not_assessable"),
    ("nan", "not_assessable"), ("inf", "not_assessable"), ("-1", "not_assessable"),
    (True, "not_assessable")])
def test_qm_boundaries_and_bad_values(value, outcome):
    assert evaluate([csv_row(value=value)])["molecules"][0]["qm_outcome"] == outcome


@pytest.mark.parametrize("changes,reason", [({"status": ""}, "qm_status_unknown"),
    ({"status": "failed"}, "qm_failed"), ({"qm_method": "dft:PBE0/def2-SVP"}, "qm_method_mismatch_or_missing")])
def test_csv_status_and_method(changes, reason):
    row = dict(csv_row(), **changes)
    result = evaluate([row])["molecules"][0]
    assert result["qm_outcome"] == "not_assessable"
    assert reason in result["qm_reasons"]


def test_target_semantics_and_finite_bounds():
    for target in [PropertyTarget(name="s1_t1_gap", max=.2), PropertyTarget(name="homo_lumo_gap", min=3, units="Ha")]:
        assert evaluate([csv_row()], target=target)["molecules"][0]["qm_outcome"] == "not_assessable"
    with pytest.raises(ValueError, match="finite"):
        evaluate([], target=PropertyTarget(name="homo_lumo_gap", min=float("nan")))
    for target in [PropertyTarget(name="homo_lumo_gap", min=3), PropertyTarget(name="homo_lumo_gap", max=3.5)]:
        assert evaluate([csv_row()], target=target)["summary"]["qm_hit_rate"]["value"] == 1


def test_denominators_duplicates_across_cohorts_and_empty_data():
    rows = [csv_row("a"), csv_row("b", value="4"), dict(csv_row("c"), status=""),
            dict(csv_row("a"), dataset="other")]
    summary = evaluate(rows)["summary"]
    assert summary["qm_coverage"] == dict(numerator=3, denominator=4, value=.75)
    assert summary["qm_hit_rate"]["numerator"] == 2
    assert summary["qm_hit_rate"]["denominator"] == 3
    assert summary["unique_qualifying_exact"] == 1
    assert summary["duplicate_id_rows"] == 0
    empty = evaluate([])["summary"]
    assert empty["validity"]["value"] is None
    assert empty["qm_hit_rate"]["value"] is None


def test_jsonl_flag_alone_is_not_evidence_and_ml_only_is_allowed():
    rows = [curated(), curated("b", validated=False, properties={"ml": 3.25}, provenance={})]
    report = evaluate(rows, profile="jsonl")
    assert report["summary"]["qm_coverage"]["numerator"] == 0
    assert report["molecules"][0]["issues"] == ["validated_claim_without_qm_evidence"]
    assert report["molecules"][1]["geometry_path_recorded"] is False
    assert report["molecules"][1]["provenance_complete"] is False


def test_jsonl_success_provenance_geometry_and_orphans(tmp_path):
    (tmp_path / "molecule.xyz").write_text("fixture")
    report = evaluate([curated(xyz_path="molecule.xyz")], profile="jsonl",
                      qm_results=[qm(), qm("orphan")], artifact_root=tmp_path)
    row = report["molecules"][0]
    assert row["qm_outcome"] == "meets_target"
    assert row["qm_evidence"] == "qm_result"
    assert row["provenance_complete"] and row["geometry_available"]
    assert not row["raw_log_verified"]
    assert report["summary"]["orphan_qm_result_ids"] == ["orphan"]


@pytest.mark.parametrize("record,results,reason", [
    (curated(validated=False), [qm()], "validated_flag_not_true"),
    (curated(properties={METHOD: 3.3}), [qm()], "curated_qm_value_mismatch"),
    (curated(properties={METHOD: float("inf")}), [qm()], "missing_or_nonfinite_curated_qm_value"),
    (curated(), [qm(), qm(value=3.4)], "conflicting_or_repeated_qm_results"),
    (curated(), [qm(error="conflict")], "conflicting_qm_error"),
    (curated(), [qm(status="failed", value=None, error="failed")], "qm_failed"),
])
def test_conflicting_jsonl_evidence(record, results, reason):
    row = evaluate([record], profile="jsonl", qm_results=results)["molecules"][0]
    assert row["qm_outcome"] == "not_assessable"
    assert reason in row["qm_reasons"]


def test_provenance_is_separate_from_target_membership():
    row = dict(csv_row(), source_csv="", geometry_policy="")
    result = evaluate([row])["molecules"][0]
    assert result["qm_outcome"] == "meets_target"
    assert result["provenance_missing"] == ["source_csv"]
    assert result["geometry_available"] is None


def test_loaders_roundtrip_reports_and_bom(tmp_path):
    path = tmp_path / "data.csv"
    row = csv_row()
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=row)
        writer.writeheader()
        writer.writerow(row)
    records, source = load_records(path, "csv")
    assert records[0]["_source_line"] == 2
    assert len(source["sha256"]) == 64
    report = evaluate(records, source=source)
    json_path, csv_path = tmp_path / "report.json", tmp_path / "report.csv"
    write_reports(report, json_path, csv_path)
    assert json.loads(json_path.read_text()) == report
    with csv_path.open(newline="") as handle:
        output = list(csv.DictReader(handle))
    assert len(output) == 1
    assert output[0]["qm_outcome"] == "meets_target"
    assert json.loads(output[0]["qm_reasons"]) == []
    with pytest.raises(ValueError, match="new files"):
        write_reports(report, json_path, csv_path)
    jsonl = tmp_path / "data.jsonl"
    jsonl.write_text("\n" + json.dumps(curated()) + "\n")
    loaded, _ = load_records(jsonl, "jsonl")
    assert loaded[0]["_source_line"] == 2


@pytest.mark.parametrize("text,profile", [("{}\n{broken", "jsonl"), ("[]", "jsonl"),
    ("smiles\nCCO\n", "csv"), ("dataset,candidate_id,smiles,qm_method,status,orca_gap_ev\na,b\n", "csv")])
def test_malformed_inputs_fail_without_partial_report(tmp_path, text, profile):
    path = tmp_path / "bad"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_records(path, profile)


def test_deterministic_output_and_empty_csv(tmp_path):
    assert evaluate([csv_row()]) == evaluate([csv_row()])
    write_reports(evaluate([]), tmp_path / "empty.json", tmp_path / "empty.csv")
    assert (tmp_path / "empty.csv").read_text().startswith("row,candidate_id,qm_outcome")


@pytest.mark.parametrize("bad_smiles", [None, "   ", 12, [], ""])
def test_non_molecular_values_stay_report_rows(bad_smiles):
    row = evaluate([csv_row(smiles=bad_smiles)])["molecules"][0]
    assert row["valid"] is False
    assert row["qm_outcome"] == "not_assessable"


def test_malformed_jsonl_id_and_duplicate_ids_are_not_joined():
    rows = [curated(id=["bad"]), curated(), curated()]
    report = evaluate(rows, profile="jsonl", qm_results=[qm()])
    assert len(report["molecules"]) == 3
    assert report["summary"]["qm_coverage"]["numerator"] == 0
    assert "missing_or_invalid_id" in report["molecules"][0]["issues"]


def test_missing_output_parent_does_not_write_partial_json(tmp_path):
    with pytest.raises(ValueError, match="parent directories"):
        write_reports(evaluate([]), tmp_path / "report.json", tmp_path / "absent" / "report.csv")
    assert not (tmp_path / "report.json").exists()


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text('{"status":"failed","status":"ok"}\n')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_records(path, "jsonl")


def test_orchestrator_provenance_seeds_alias():
    record = curated(provenance=dict(seeds="C;CC", parent="CC", generator="test", round="1"))
    assert evaluate([record], profile="jsonl")["molecules"][0]["provenance_complete"]


def test_malformed_status_is_unknown_and_serializable(tmp_path):
    report = evaluate([curated()], profile="jsonl", qm_results=[qm(status=float("nan"))])
    assert report["molecules"][0]["qm_status"] is None
    assert report["molecules"][0]["qm_outcome"] == "not_assessable"
    write_reports(report, tmp_path / "report.json", tmp_path / "report.csv")


def test_failed_csv_does_not_claim_success():
    assert evaluate([dict(csv_row(), status="failed")])["molecules"][0]["qm_evidence"] == "reported_status"


def test_output_failure_rolls_back_only_new_files(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("simulated write failure")
    monkeypatch.setattr(csv.DictWriter, "writeheader", fail)
    with pytest.raises(OSError, match="simulated"):
        write_reports(evaluate([]), tmp_path / "report.json", tmp_path / "report.csv")
    assert not (tmp_path / "report.json").exists()
    assert not (tmp_path / "report.csv").exists()
