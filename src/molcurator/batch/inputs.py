"""Independent CSV and SMILES input validation."""
import csv
from pathlib import Path
from molcurator.schemas import Candidate
from .chem.calculations import safe_id


def read_candidates(path, format="auto"):
    path = Path(path)
    format = ("csv" if path.suffix.lower() == ".csv" else "smi") if format == "auto" else format
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        if format == "csv":
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not {"id", "smiles"} <= set(reader.fieldnames):
                raise ValueError("CSV requires id and smiles headers")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"malformed CSV row {reader.line_num}")
                rows.append(row)
        else:
            for line_number, line in enumerate(handle, 1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                fields = line.split()
                if len(fields) > 2:
                    raise ValueError(f"SMILES line {line_number} must contain SMILES and optional ID")
                rows.append(dict(smiles=fields[0], id=fields[1] if len(fields) == 2 else f"mol{len(rows)+1:06d}"))
    candidates = []
    seen = set()
    for row in rows:
        cid = safe_id(row["id"].strip())
        if cid in seen:
            raise ValueError(f"duplicate candidate ID: {cid}")
        seen.add(cid)
        smiles = row["smiles"].strip()
        if not smiles:
            raise ValueError(f"empty SMILES for {cid}")
        candidates.append(Candidate(id=cid, smiles=smiles,
            parent_smiles=(row.get("parent_smiles") or smiles).strip(),
            round=int(row.get("round") or 1), generator=(row.get("generator") or "batch_input").strip()))
    if not candidates:
        raise ValueError("input contains no molecules")
    return candidates
