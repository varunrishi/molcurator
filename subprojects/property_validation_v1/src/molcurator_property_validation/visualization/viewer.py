"""Read-only molecular visualization for MolCurator result artifacts.

Uses the xTB-optimized geometry returned by Prediction.xyz_path. No QC is executed.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Iterable


def read_xyz(path: str | Path) -> str:
    """Validate a well-formed, finite XYZ and return its original text."""
    import math
    from rdkit import Chem

    path = Path(path)
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    if not lines:
        raise ValueError("empty XYZ")
    try:
        count = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError("invalid XYZ atom count") from exc
    if count < 1 or len(lines) != count + 2:
        raise ValueError("invalid XYZ atom count")
    table = Chem.GetPeriodicTable()
    for line in lines[2:]:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("invalid XYZ coordinate line")
        try:
            valid = table.GetAtomicNumber(fields[0]) > 0
            finite = all(math.isfinite(float(x)) for x in fields[1:])
        except (ValueError, RuntimeError):
            valid, finite = False, False
        if not valid or not finite:
            raise ValueError("invalid XYZ coordinate line")
    return content


def render_xyz_html(xyz_path: str | Path, output_html: str | Path,
                    *, title: str = "MolCurator molecule", width: int = 760,
                    height: int = 520) -> Path:
    """Export rotatable 3D viewer HTML (py3Dmol JavaScript loaded on viewing).

    The input file is never changed. This works on HPC without an X display.
    """
    if width <= 0 or height <= 0:
        raise ValueError("viewer dimensions must be positive")
    xyz = read_xyz(xyz_path)
    try:
        import py3Dmol
    except ImportError as exc:
        raise RuntimeError("Install py3Dmol: uv add py3Dmol") from exc
    view = py3Dmol.view(width=width, height=height)
    view.addModel(xyz, "xyz")
    view.setStyle({"stick": {"radius": 0.16}, "sphere": {"scale": 0.28}})
    view.setBackgroundColor("white")
    view.zoomTo()
    markup = view._make_html()
    # py3Dmol escapes XYZ content in its own generated JS; title is escaped here.
    document = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                f"<title>{html.escape(title)}</title>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "</head><body><main>"
                f"<h1>{html.escape(title)}</h1>{markup}"
                "<p>Geometry: xTB-optimized XYZ. Viewer requires JavaScript and access to the 3Dmol.js CDN.</p>"
                "</main></body></html>")
    out = Path(output_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")
    return out


def export_prediction_gallery(predictions: Iterable[Any], output_dir: str | Path,
                              *, max_molecules: int = 30) -> dict[str, Any]:
    """Export HTML for successful predictions and a JSON index.

    Accepts Pydantic Prediction instances or equivalent dictionaries. Preserves
    every record in index.json, including failed/missing geometries. Does not
    change Prediction.value or the shared agent schema.
    """
    if max_molecules < 0:
        raise ValueError("max_molecules must be nonnegative")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    count = 0
    for pred in predictions:
        if hasattr(pred, "model_dump"):
            pred = pred.model_dump(mode="json")
        if not isinstance(pred, dict):
            raise TypeError("Predictions must be dictionaries or Pydantic models")
        cid = str(pred.get("candidate_id", ""))
        record: dict[str, Any] = {
            "candidate_id": cid,
            "status": str(pred.get("status", "")),
            "raw_xtb_gap_ev": pred.get("value"),
            "xyz_path": str(pred.get("xyz_path")) if pred.get("xyz_path") else None,
            "error": pred.get("error"),
            "viewer_file": None,
        }
        # Use a numeric output filename rather than untrusted candidate IDs.
        if record["status"] == "ok" and record["xyz_path"] and count < max_molecules:
            filename = f"molecule_{len(records):04d}.html"
            try:
                render_xyz_html(record["xyz_path"], out / filename, title=f"MolCurator: {cid}")
                record["viewer_file"] = filename
                count += 1
            except (OSError, ValueError, RuntimeError) as exc:
                record["viewer_error"] = f"{type(exc).__name__}: {exc}"
        records.append(record)
    result = {"total": len(records), "viewers_generated": count, "records": records}
    (out / "index.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result
