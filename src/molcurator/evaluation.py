"""Offline dataset evaluation; no chemistry programs or agent services are invoked."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

from rdkit import Chem, rdBase

from molcurator.chem.audit import audit_candidates
from molcurator.schemas import PropertyTarget


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_records(path: str | Path, profile: str) -> tuple[list[dict], dict]:
    """Read explicit collaborator CSV or curated JSONL, retaining source line numbers.

    Invalid molecular/field values are evaluated, not discarded. Broken file syntax
    raises a contextual error rather than returning a deceptively partial dataset.
    """
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    records = []
    if profile == "csv":
        reader = csv.DictReader(text.splitlines(keepends=True), strict=True)
        required = {"dataset", "candidate_id", "smiles", "qm_method", "status", "orca_gap_ev"}
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ValueError(f"{path}: missing required collaborator CSV columns: "
                             f"{sorted(required - set(reader.fieldnames or []))}")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"{path}: duplicate CSV headers")
        try:
            for record in reader:
                if None in record or any(value is None for value in record.values()):
                    raise ValueError(f"{path}:{reader.line_num}: inconsistent CSV row width")
                records.append(dict(record, _source_line=reader.line_num))
        except csv.Error as exc:
            raise ValueError(f"{path}:{reader.line_num}: invalid CSV: {exc}") from exc
    elif profile == "jsonl":
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line, object_pairs_hook=_unique_object)
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            # The evaluator owns this field; input cannot override source attribution.
            records.append(dict(record, _source_line=line_number))
    else:
        raise ValueError("profile must be csv or jsonl")
    return records, {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                     "profile": profile}


def _present(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _canonical(smiles: str, stereo: bool) -> str:
    # Settle representations which change aromaticity on the first round trip.
    out = Chem.MolToSmiles(Chem.MolFromSmiles(smiles), isomericSmiles=stereo)
    again = Chem.MolFromSmiles(out)
    return Chem.MolToSmiles(again, isomericSmiles=stereo) if again is not None else out


def _ratio(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def evaluate_dataset(
    records: list[dict], *, target: PropertyTarget, qm_method: str,
    profile: str, seeds: list[str] | None = None,
    qm_results: list[dict] | None = None, source: dict | None = None,
    artifact_root: str | Path | None = None,
) -> dict:
    """Evaluate rows without mutation, assuming gap/eV semantics from the caller.

    JSONL requires matching successful QMResult evidence; a validated flag alone
    is insufficient. CSV status is only reported success, not raw-log verification.
    Duplicate record identities are ambiguous and excluded from QM assessment.
    """
    if profile not in {"csv", "jsonl"}:
        raise ValueError("profile must be csv or jsonl")
    if not _present(qm_method) or not qm_method.startswith("dft:") or "/" not in qm_method[4:]:
        raise ValueError("qm_method must be an explicit dft:method/basis label")
    if any(bound is not None and _finite(bound) is None for bound in (target.min, target.max)):
        raise ValueError("target bounds must be finite")
    if target.min is None and target.max is None or (
        target.min is not None and target.max is not None and target.min > target.max
    ):
        raise ValueError("target needs ordered min and/or max bounds")
    if any(not isinstance(row, dict) for row in records):
        raise ValueError("records must be objects")
    if profile == "csv" and qm_results is not None:
        raise ValueError("QMResult sidecars apply to curated JSONL only")
    seeds = list(seeds or [])
    smiles_by_row = {str(i): row.get("smiles") for i, row in enumerate(records, 1)}
    # The existing audit needs a seed even for validity. Its seed-derived fields
    # are ignored when none was supplied; no seed identity is inferred.
    audits = [audit_candidates(seed, smiles_by_row)["candidates"] for seed in (seeds or ["C"])]

    identities = []
    for i, row in enumerate(records, 1):
        cid = row.get("candidate_id" if profile == "csv" else "id")
        dataset = row.get("dataset") if profile == "csv" else None
        identity = (dataset, cid) if profile == "csv" else (cid,)
        # Missing or malformed IDs stay rows, but must not become join keys.
        identities.append(identity if _present(cid) and (profile != "csv" or _present(dataset))
                          else ("invalid-row", i))
    counts = Counter(identities)
    evidence = {}
    for item in qm_results or []:
        if not isinstance(item, dict) or not _present(item.get("candidate_id")):
            raise ValueError("QM results require object records with candidate_id")
        evidence.setdefault(item["candidate_id"], []).append(item)

    seen_exact, seen_noiso, seen_ids = {}, {}, {}
    molecules = []
    for i, (row, identity) in enumerate(zip(records, identities), 1):
        audit = audits[0][str(i)]
        valid = audit["valid"]
        canonical = _canonical(row["smiles"], True) if valid else None
        noiso = _canonical(row["smiles"], False) if valid else None
        cid = row.get("candidate_id" if profile == "csv" else "id")
        issues = []
        duplicate_id = seen_ids.get(identity)
        seen_ids.setdefault(identity, i)
        if not _present(cid):
            issues.append("missing_or_invalid_id")
        if counts[identity] > 1:
            issues.append("ambiguous_record_identity")
        if not valid:
            issues.append("invalid_smiles")
        result = dict(row=i, source_line=row.get("_source_line", i),
                      dataset=row.get("dataset") if profile == "csv" else None,
                      candidate_id=cid if isinstance(cid, str) else None,
                      smiles=row.get("smiles") if isinstance(row.get("smiles"), str) else None,
                      valid=valid, canonical_smiles=canonical, canonical_smiles_no_stereo=noiso,
                      duplicate_id_of_row=duplicate_id,
                      duplicate_exact_of_row=seen_exact.get(canonical) if valid else None,
                      duplicate_no_stereo_of_row=seen_noiso.get(noiso) if valid else None,
                      seed_overlap_exact=any(a[str(i)]["same_as_seed_exact"] for a in audits) if seeds else None,
                      seed_overlap_no_stereo=any(a[str(i)]["same_as_seed_ignoring_stereo"] for a in audits) if seeds else None,
                      max_seed_tanimoto=max(a[str(i)]["tanimoto_to_seed"] for a in audits) if seeds and valid else None)
        if valid:
            seen_exact.setdefault(canonical, i)
            seen_noiso.setdefault(noiso, i)
        if profile == "csv":
            missing = [key for key in ("dataset", "candidate_id", "qm_method", "reference_method", "source_csv")
                       if not _present(row.get(key))]
            result["geometry_available"] = None
            result["geometry_policy_available"] = _present(row.get("geometry_policy"))
            status, method, raw_value = row.get("status"), row.get("qm_method"), row.get("orca_gap_ev")
            level = "reported_success" if status == "ok" else "reported_status"
            qm_reasons = []
        else:
            provenance = row.get("provenance")
            provenance = provenance if isinstance(provenance, dict) else {}
            missing = [f"provenance.{key}" for key in ("parent", "generator", "round")
                       if not _present(provenance.get(key))]
            if not (_present(provenance.get("seed")) or _present(provenance.get("seeds"))):
                missing.insert(0, "provenance.seed_or_seeds")
            geometry = row.get("xyz_path")
            result["geometry_available"] = None
            if _present(geometry) and artifact_root is not None:
                path = Path(geometry)
                result["geometry_available"] = (Path(artifact_root) / path).is_file()
            result["geometry_path_recorded"] = _present(geometry)
            matches = [item for item in evidence.get(cid, []) if item.get("method") == qm_method] if _present(cid) else []
            qm_reasons = []
            status, method, raw_value, level = None, None, None, "unavailable"
            properties = row.get("properties")
            properties = properties if isinstance(properties, dict) else {}
            if len(matches) > 1:
                qm_reasons.append("conflicting_or_repeated_qm_results")
            elif not matches:
                qm_reasons.append("missing_matching_qm_result")
            else:
                item = matches[0]
                status, method, raw_value = item.get("status"), item.get("method"), item.get("value")
                level = "qm_result"
                if row.get("validated") is not True:
                    qm_reasons.append("validated_flag_not_true")
                if item.get("error") and status == "ok":
                    qm_reasons.append("conflicting_qm_error")
                curated_value = _finite(properties.get(qm_method))
                if curated_value is None:
                    qm_reasons.append("missing_or_nonfinite_curated_qm_value")
                elif _finite(raw_value) != curated_value:
                    qm_reasons.append("curated_qm_value_mismatch")
            if row.get("validated") is True and not matches:
                issues.append("validated_claim_without_qm_evidence")
        result["provenance_missing"] = missing
        result["provenance_complete"] = not missing
        result["raw_log_verified"] = False
        value = _finite(raw_value)
        if target.name != "homo_lumo_gap" or target.units != "eV":
            qm_reasons.append("unsupported_property_or_units")
        if not valid:
            qm_reasons.append("invalid_smiles")
        if not _present(cid) or (profile == "csv" and not _present(row.get("dataset"))):
            qm_reasons.append("missing_record_identity")
        if counts[identity] > 1:
            qm_reasons.append("ambiguous_record_identity")
        if method != qm_method:
            qm_reasons.append("qm_method_mismatch_or_missing")
        if status != "ok":
            qm_reasons.append("qm_failed" if status == "failed" else "qm_status_unknown")
        if value is None or value < 0:
            qm_reasons.append("missing_or_invalid_qm_gap")
        outcome = "not_assessable"
        if not qm_reasons:
            meets = (target.min is None or value >= target.min) and (target.max is None or value <= target.max)
            outcome = "meets_target" if meets else "outside_target"
        result.update(qm_method=method if isinstance(method, str) else None, qm_value=value,
                      qm_status=status if isinstance(status, str) else None,
                      qm_evidence=level, qm_outcome=outcome,
                      qm_reasons=list(dict.fromkeys(qm_reasons)), issues=issues)
        molecules.append(result)

    total = len(molecules)
    valid_count = sum(row["valid"] for row in molecules)
    assessed = [row for row in molecules if row["qm_outcome"] != "not_assessable"]
    hits = [row for row in assessed if row["qm_outcome"] == "meets_target"]
    record_ids = {row.get("id") for row in records if _present(row.get("id"))}
    return dict(
        report_version=1,
        metadata=dict(profile=profile, source=source, target=target.model_dump(),
                      qm_method=qm_method, seeds=seeds, seed_source="explicit" if seeds else "unavailable",
                      rdkit_version=rdBase.rdkitVersion,
                      property_semantics="homo_lumo_gap/eV supplied by caller; not encoded in CuratedEntry",
                      provenance_scope="field completeness only; source claims and geometry contents are not verified"),
        summary=dict(
            rows=total, validity=_ratio(valid_count, total),
            unique_exact=len(seen_exact), unique_no_stereo=len(seen_noiso),
            duplicate_id_rows=sum(row["duplicate_id_of_row"] is not None for row in molecules),
            duplicate_exact_rows=valid_count - len(seen_exact),
            duplicate_no_stereo_rows=valid_count - len(seen_noiso),
            seed_overlap_exact=sum(row["seed_overlap_exact"] is True for row in molecules) if seeds else None,
            seed_overlap_no_stereo=sum(row["seed_overlap_no_stereo"] is True for row in molecules) if seeds else None,
            provenance_completeness=_ratio(sum(row["provenance_complete"] for row in molecules), total),
            qm_coverage=_ratio(len(assessed), total), qm_hit_rate=_ratio(len(hits), len(assessed)),
            qm_outcomes=dict(Counter(row["qm_outcome"] for row in molecules)),
            unique_qualifying_exact=len({row["canonical_smiles"] for row in hits}),
            unique_qualifying_no_stereo=len({row["canonical_smiles_no_stereo"] for row in hits}),
            orphan_qm_result_ids=sorted(set(evidence) - record_ids) if profile == "jsonl" else []),
        molecules=molecules,
    )


def write_reports(report: dict, json_path: str | Path, csv_path: str | Path) -> None:
    """Write strict JSON plus one CSV row per input molecule; never overwrite outputs."""
    json_path, csv_path = Path(json_path), Path(csv_path)
    if json_path.resolve() == csv_path.resolve():
        raise ValueError("JSON and CSV output paths must differ")
    if json_path.exists() or csv_path.exists():
        raise ValueError("report outputs must be new files")
    if not json_path.parent.is_dir() or not csv_path.parent.is_dir():
        raise ValueError("report output parent directories must exist")
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    rows = report["molecules"]
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ["row", "candidate_id", "qm_outcome"]
    created = []
    try:
        with ExitStack() as stack:
            json_handle = stack.enter_context(json_path.open("x", encoding="utf-8", newline=""))
            created.append(json_path)
            csv_handle = stack.enter_context(csv_path.open("x", encoding="utf-8", newline=""))
            created.append(csv_path)
            json_handle.write(serialized)
            writer = csv.DictWriter(csv_handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(value, allow_nan=False) if isinstance(value, (list, dict)) else value
                                 for key, value in row.items()})
    except BaseException:
        # Only remove outputs exclusively created here, after closing handles.
        for path in created:
            path.unlink(missing_ok=True)
        raise
