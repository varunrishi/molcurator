"""Reports for a batch run directory: summary.csv, calculations.json and report.md (plus
optional PNG plots), rebuilt from results.json and the per-molecule calculation records."""
import csv
import io
import json
from pathlib import Path

from molcurator.chem import orca, xtb
from molcurator.fileio import atomic_json, native_path

CSV_SCHEMA_VERSION = 3
CSV_COLUMNS = ("csv_schema_version", "candidate_id", "smiles", "parent_smiles", "round", "generator", "property",
               "predict_status", "predict_value", "predict_method", "predict_error", "xyz_path", "qm_selection",
               "qm_status", "qm_value", "qm_method", "qm_error", "failure_stage", "geometry_failure_code",
               "formal_charge", "radical_electrons", "ff_energy_kcal_mol", "ff_boltzmann_weight", "temperature_k",
               "n_unique_conformers", "predict_runtime_s", "qm_runtime_s")


def require_plotting() -> None:
    from molcurator.batch.plotting import require_plotting as check
    check()


def unit_of(prop: str) -> str:
    spec = orca.PROPERTIES.get(prop) or xtb.PROPERTIES.get(prop)
    return spec.unit if spec else ""


def _read(path: Path, warnings: list[str]) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        warnings.append(f"{path}: {exc}")
        return {}


def summarize(xyz_dir: Path) -> dict:
    """Calculation records (calculations/<id>/predict.json and validate.json) of a run:
    counts by backend, failures and runtime. Each record is one attempted calculation."""
    records, errors = [], []
    for path in sorted(native_path(xyz_dir).glob("calculations/*/*.json")):
        if path.name not in ("predict.json", "validate.json"):
            continue
        try:
            records.append({"path": str(path), **json.loads(path.read_text())})
        except (OSError, ValueError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    launched = [r for r in records if r.get("backend")]  # geometry failures never reach a backend
    return {"records": records, "record_errors": errors, "calculations": len(launched),
            "by_backend": {b: sum(r["backend"] == b for r in launched) for b in ("xtb", "orca")},
            "failed": sum(r.get("status") == "failed" for r in records),
            "runtime_s": sum(r.get("runtime_s", 0) for r in launched)}


def build_rows(state: dict, root: Path) -> tuple[list[dict], list[str]]:
    rows, warnings = [], []
    for item in state["rows"]:
        candidate, cid = item["candidate"], item["candidate"]["id"]
        prediction, qm = item.get("prediction") or {}, item.get("qm_result") or {}
        folder = root / "xyz" / "calculations" / cid
        geometry = _read(folder / "geometry_report.json", warnings) if prediction else {}
        predict_record = _read(folder / "predict.json", warnings) if prediction else {}
        qm_record = _read(folder / "validate.json", warnings) if qm else {}
        rows.append({
            "csv_schema_version": CSV_SCHEMA_VERSION, "candidate_id": cid, "smiles": candidate["smiles"],
            "parent_smiles": candidate["parent_smiles"], "round": candidate["round"],
            "generator": candidate["generator"], "property": state["target"]["name"],
            "predict_status": prediction.get("status", "pending"), "predict_value": prediction.get("value"),
            "predict_method": predict_record.get("method_label"), "predict_error": prediction.get("error"),
            "xyz_path": prediction.get("xyz_path"), "qm_selection": item["qm_selection"],
            "qm_status": qm.get("status", "pending" if item["qm_selection"] in ("pending", "selected") else "not_run"),
            "qm_value": qm.get("value"), "qm_method": qm.get("method"), "qm_error": qm.get("error"),
            "failure_stage": ("predict" if prediction.get("status") == "failed"
                              else "validate" if qm.get("status") == "failed" else None),
            "geometry_failure_code": predict_record.get("failure_code"),
            "formal_charge": geometry.get("formal_charge"), "radical_electrons": geometry.get("radical_electrons"),
            "ff_energy_kcal_mol": geometry.get("selected_ff_energy_kcal_mol"),
            "ff_boltzmann_weight": geometry.get("selected_ff_boltzmann_weight"),
            "temperature_k": geometry.get("temperature_k"), "n_unique_conformers": geometry.get("n_unique"),
            "predict_runtime_s": predict_record.get("runtime_s"), "qm_runtime_s": qm_record.get("runtime_s")})
    return rows, warnings


def write_csv(root: Path, rows: list[dict], unit: str) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    temp = root / "summary.csv.tmp"
    temp.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    temp.replace(root / "summary.csv")
    atomic_json(root / "csv_schema.json", {
        "schema_version": CSV_SCHEMA_VERSION, "columns": list(CSV_COLUMNS),
        "units": {"predict_value": unit, "qm_value": unit, "ff_energy_kcal_mol": "kcal/mol", "temperature_k": "K",
                  "predict_runtime_s": "seconds", "qm_runtime_s": "seconds"},
        "missing_values": "blank CSV cells are unavailable, never zero-filled"})


def generate_report(root, plots: bool = False) -> dict:
    root = native_path(root)
    if plots:
        require_plotting()
    state = json.loads((root / "results.json").read_text())
    if state.get("schema_version") != 2 or not isinstance(state.get("rows"), list):
        raise ValueError("not a supported property batch results file")
    prop, unit = state["target"]["name"], unit_of(state["target"]["name"])
    summary = summarize(root / "xyz")
    rows, warnings = build_rows(state, root)
    warnings.extend(f"Calculation record {e['path']}: {e['error']}" for e in summary["record_errors"])
    write_csv(root, rows, unit)
    atomic_json(root / "calculations.json", summary)
    counts = {"total": len(rows), "predict_ok": sum(r["predict_status"] == "ok" for r in rows),
              "predict_failed": sum(r["predict_status"] == "failed" for r in rows),
              "qm_ok": sum(r["qm_status"] == "ok" for r in rows),
              "qm_failed": sum(r["qm_status"] == "failed" for r in rows)}
    lines = ["# Molecular property batch report", "", f"Run status: {state['run_status']}",
             f"Invocation: {state['invocation_id']}", f"Property: {prop} ({unit})",
             f"PREDICT method: {state['predict_method']}", "", "## Current results", "",
             (f"Candidates: {counts['total']}; predicted: {counts['predict_ok']}; prediction failed: "
              f"{counts['predict_failed']}."),
             f"QM validated: {counts['qm_ok']}; QM failed: {counts['qm_failed']}.",
             "Missing or unrequested values are blank, never zero.", "",
             "## Calculation history", "",
             (f"Calculations recorded: {summary['calculations']} (xTB {summary['by_backend']['xtb']}, "
              f"ORCA {summary['by_backend']['orca']}); recorded runtime: {summary['runtime_s']:.3f} s."),
             "Records keep the latest attempt per molecule and stage; resumed runs overwrite them.", "",
             "## Files", "", "- [Candidate results and configuration](results.json)",
             "- [CSV summary](summary.csv)", "- [Calculation records](calculations.json)", "",
             "## Interpretation", "",
             "Values are vertical: computed at the selected MMFF94 minimum, without re-optimisation. Its Boltzmann",
             "population is conditional on the unique sampled force-field minima. No calibration is fitted here.", ""]
    if state.get("qm"):
        lines += [f"QM method: {state['qm']['functional']}/{state['qm']['basis']} (ORCA).", ""]
    if plots:
        from molcurator.batch.plotting import render_plots
        render_plots(root, rows, summary["records"], f"{prop} / {unit}")
        lines += ["## Figures", "", "![Current values](plots/values.png)", "",
                  "![Current result coverage](plots/status.png)", "",
                  "![Calculation runtime](plots/execution.png)", "",
                  "![Geometry selection](plots/conformers.png)", ""]
    if warnings:
        lines += ["## Record warnings", ""] + ["- " + warning for warning in warnings]
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return {"counts": counts, "warnings": warnings, "summary": summary}
