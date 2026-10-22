"""Stable CSV exports and normalized table rows independent of plotting."""
import csv
import io
import json
from molcurator.chem.fileio import atomic_json

CSV_COLUMNS = ('csv_schema_version', 'candidate_id', 'smiles', 'parent_smiles', 'round', 'generator', 'xtb_status', 'xtb_gap_ev', 'xtb_error', 'xyz_path', 'orca_status', 'orca_selection', 'failure_stage', 'prevalidation_status', 'prevalidation_stage', 'prevalidation_code', 'prevalidation_error', 'input_formal_charge', 'input_radical_electrons', 'orca_gap_ev', 'orca_error', 'method', 'ff_energy_kcal_mol', 'ff_boltzmann_weight', 'temperature_k', 'n_unique_conformers', 'xtb_calls_total', 'orca_calls_total', 'cache_hits_total', 'runtime_s_total')

def build_rows(state, root, attempts):
    rows = []
    warnings = []
    for item in state["rows"]:
        candidate = item["candidate"]
        prediction = item.get("prediction") or {}
        qm = item.get("qm_result") or {}
        cid = candidate["id"]
        selected = [r for r in attempts if r.get("candidate_id") == cid]
        geometry = {}
        path = root / "xyz/calculations" / cid / "xtb/geometry_report.json"
        if path.is_file() and prediction.get("status") == "ok":
            try:
                geometry = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                warnings.append(f"Geometry report for {cid}: {exc}")
        prevalidation = {}
        pre_path = root / "xyz/calculations" / cid / "xtb/prevalidation.json"
        if pre_path.is_file() and prediction:
            try:
                prevalidation = json.loads(pre_path.read_text())
            except (OSError, ValueError) as exc:
                warnings.append(f"Prevalidation report for {cid}: {exc}")
        details = prevalidation.get("details", {})
        rows.append(dict(csv_schema_version=2, candidate_id=cid, smiles=candidate["smiles"],
            parent_smiles=candidate["parent_smiles"], round=candidate["round"],
            generator=candidate["generator"], xtb_status=prediction.get("status", "pending"),
            xtb_gap_ev=prediction.get("value"), xtb_error=prediction.get("error"),
            xyz_path=prediction.get("xyz_path"),
            orca_status=qm.get("status", "pending" if item["orca_selection"] in ("pending", "selected") else "not_run"),
            orca_selection=item["orca_selection"],
            failure_stage="predict" if prediction.get("status") == "failed" else "validate" if qm.get("status") == "failed" else None,
            prevalidation_status=prevalidation.get("status"),
            prevalidation_stage=prevalidation.get("stage"), prevalidation_code=prevalidation.get("code"),
            prevalidation_error=prevalidation.get("error"),
            input_formal_charge=details.get("formal_charge"), input_radical_electrons=details.get("radical_electrons"),
            orca_gap_ev=qm.get("value"), orca_error=qm.get("error"), method=qm.get("method"),
            ff_energy_kcal_mol=geometry.get("selected_ff_energy_kcal_mol"),
            ff_boltzmann_weight=geometry.get("selected_ff_boltzmann_weight"),
            temperature_k=geometry.get("temperature_k"), n_unique_conformers=geometry.get("n_unique"),
            xtb_calls_total=sum(r.get("electronic_calls_attempted", 0) for r in selected if r.get("backend") == "xtb"),
            orca_calls_total=sum(r.get("electronic_calls_attempted", 0) for r in selected if r.get("backend") == "orca"),
            cache_hits_total=sum(bool(r.get("cache_hit")) for r in selected),
            runtime_s_total=sum(r.get("runtime_s", 0) for r in selected)))
    return rows, warnings



def write_csv(root, rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path = root / "summary.csv"
    temp = path.with_name("summary.csv.tmp")
    temp.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    temp.replace(path)
    atomic_json(root / "csv_schema.json", dict(schema_version=2, columns=list(CSV_COLUMNS),
        units={"xtb_gap_ev":"eV", "orca_gap_ev":"eV", "ff_energy_kcal_mol":"kcal/mol",
               "temperature_k":"K", "runtime_s_total":"seconds"},
        missing_values="blank CSV cells are unavailable, never zero-filled",
        count_scope="*_total columns include all retained attempts in this run directory"))
