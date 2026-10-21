"""Public property predictor for generated molecules; no generation or agent decisions."""
import hashlib
import json
import math
import re
import shutil
from uuid import uuid4
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from rdkit import Chem

from molcurator.schemas import Candidate, Prediction, QMSettings, Status
from .chem.calculations import run, safe_id
from .chem.geometry import lowest_ff_conformer, xyz_symbols
from .properties import UNITS, extract_properties
from .tools.predict import predict as xtb_predict


class PredictorSettings(BaseModel):
    backend: Literal["xtb", "orca", "ml"] = "xtb"
    properties: list[str] = Field(default_factory=lambda: ["homo_lumo_gap"], min_length=1)
    qm: QMSettings = Field(default_factory=QMSettings)
    geometry: Literal["xtb", "force_field"] = "xtb"
    model_path: Path | None = None

    @field_validator("properties")
    @classmethod
    def _supported(cls, names):
        if len(names) != len(set(names)) or not set(names) <= set(UNITS):
            raise ValueError(f"request unique supported properties: {list(UNITS)}")
        return names


class MolecularPrediction(BaseModel):
    """One input molecule's properties; partial values survive explicit failures."""

    candidate_id: str
    smiles: str
    backend: str
    method: str
    status: Status
    values: dict[str, float] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    xyz_path: Path | None = None
    errors: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    metadata: dict = Field(default_factory=dict)

    def as_prediction(self, property_name: str) -> Prediction:
        """Explicit bridge to the unchanged team's single-property prediction model."""
        if property_name in self.values:
            return Prediction(candidate_id=self.candidate_id, status=Status.ok,
                              value=self.values[property_name], xyz_path=self.xyz_path)
        return Prediction(candidate_id=self.candidate_id, status=Status.failed,
                          error=self.errors.get(property_name) or self.error or "property not requested")


def _valid_molecule(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None or not mol.GetNumAtoms() or len(Chem.GetMolFrags(mol)) != 1:
        raise ValueError("one valid connected molecule required")
    if Chem.GetFormalCharge(mol) or any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        raise ValueError("neutral closed-shell molecules required")
    return mol


def _orca(candidate, geometry, settings, folder, metadata):
    if settings.qm.backend != "orca":
        raise ValueError("ORCA backend requires qm.backend=orca")
    for keyword in (settings.qm.functional, settings.qm.basis):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_+*(),./-]*", keyword):
            raise ValueError("functional and basis must be single keywords")
    folder.mkdir(parents=True)
    shutil.copyfile(geometry, folder / "geometry.xyz")
    (folder / "properties.inp").write_text(
        f"! {settings.qm.functional} {settings.qm.basis} TightSCF\n"
        "%elprop\n Dipole true\nend\n%pal nprocs 1 end\n%maxcore 2000\n"
        "* xyzfile 0 1 geometry.xyz\n")
    attempt = dict(candidate_id=candidate.id, method=metadata["method"],
                   qm_calls_attempted=1, status="started")
    attempt_path = folder / "attempt.json"
    attempt_path.write_text(json.dumps(attempt, indent=2))
    metadata["qm_calls_attempted"] = 1
    metadata["attempt_path"] = str(attempt_path)
    try:
        run("ORCA_BIN", "orca", ["properties.inp"], folder, folder / "orca.out")
        values = extract_properties((folder / "orca.out").read_text(errors="replace"), "orca")
        attempt.update(status="ok", values=values)
        return values
    except Exception as exc:
        attempt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        attempt_path.write_text(json.dumps(attempt, indent=2))


def predict_properties(candidates: list[Candidate], settings: PredictorSettings,
                       output_dir: Path, *, xyz_paths: dict[str, Path] | None = None
                       ) -> list[MolecularPrediction]:
    """One ordered record per generated molecule using exactly the chosen backend.

    ORCA can use supplied XYZ, the default xTB-refined geometry, or explicit FF-only
    geometry. ML needs a separately trained model; it runs no QM or embedding.
    A new output directory is required. The agent owns all budget and policy decisions.
    """
    ids = [c.id for c in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate IDs must be unique")
    if xyz_paths is not None and settings.backend != "orca":
        raise ValueError("supplied XYZ geometries apply to ORCA only")
    model = None
    if settings.backend == "ml":
        if settings.model_path is None:
            raise ValueError("ML prediction requires a trained model_path")
        from .ml import FingerprintModel
        model_bytes = settings.model_path.read_bytes()
        model = FingerprintModel(json.loads(model_bytes.decode("utf-8-sig")))
        model_hash = hashlib.sha256(model_bytes).hexdigest()
        method = "ml:fingerprint-ridge:" + model.artifact["reference_method"]
    else:
        method = ("xtb:GFN2" if settings.backend == "xtb" else
                  f"dft:{settings.qm.functional}/{settings.qm.basis}")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    predictions = []
    for candidate in candidates:
        metadata = dict(method=method, qm_calls_attempted=0)
        geometry = None
        try:
            cid = safe_id(candidate.id)
            mol = _valid_molecule(candidate.smiles)
            if settings.backend == "ml":
                values = model.predict(candidate.smiles)
                metadata.update(reference_method=model.artifact["reference_method"],
                                uncertainty="not_available",
                                model_sha256=model_hash)
            else:
                if xyz_paths is not None:
                    geometry = Path(xyz_paths[cid]).resolve()
                    expected = sorted(a.GetSymbol() for a in Chem.AddHs(mol).GetAtoms())
                    if sorted(xyz_symbols(geometry)) != expected:
                        raise ValueError("supplied XYZ element composition differs from SMILES")
                    metadata["geometry_source"] = "supplied_xyz"
                elif settings.backend == "xtb" or settings.geometry == "xtb":
                    from molcurator.schemas import PropertyTarget
                    raw = xtb_predict([candidate], PropertyTarget(name="homo_lumo_gap", min=0),
                                      root / "xyz")[0]
                    if raw.status is not Status.ok:
                        raise RuntimeError(raw.error)
                    geometry = raw.xyz_path
                    metadata["geometry_source"] = "lowest_ff_then_gfn2_xtb"
                    report_path = root / "xyz" / "calculations" / cid / "xtb" / "geometry_report.json"
                    if report_path.exists():
                        metadata["geometry_report"] = json.loads(report_path.read_text())
                else:
                    geometry = root / "xyz" / f"{cid}.xyz"
                    geometry.parent.mkdir(parents=True, exist_ok=True)
                    xyz, report = lowest_ff_conformer(candidate.smiles)
                    geometry.write_text(xyz)
                    (geometry.parent / f"{cid}.geometry_report.json").write_text(json.dumps(report, indent=2))
                    metadata.update(geometry_source="lowest_ff_only", geometry_report=report)
                if settings.backend == "xtb":
                    log = root / "xyz" / "calculations" / cid / "xtb" / "xtb.out"
                    values = extract_properties(log.read_text(errors="replace"), "xtb")
                else:
                    values = _orca(candidate, geometry, settings,
                                   root / "calculations" / cid / "orca", metadata)
            selected, errors = {}, {}
            for name in settings.properties:
                value = values.get(name)
                if value is None or not math.isfinite(value):
                    errors[name] = "requested property unavailable from backend/model"
                elif name in ("homo_lumo_gap", "dipole") and value < 0:
                    errors[name] = "backend predicted a negative gap or dipole magnitude"
                else:
                    selected[name] = value
            result = MolecularPrediction(
                candidate_id=candidate.id, smiles=candidate.smiles, backend=settings.backend,
                method=method, status=Status.failed if errors else Status.ok,
                values=selected, units={p: UNITS[p] for p in selected}, xyz_path=geometry,
                errors=errors, error="some requested properties unavailable" if errors else None,
                metadata=metadata)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            result = MolecularPrediction(candidate_id=candidate.id, smiles=candidate.smiles,
                backend=settings.backend, method=method, status=Status.failed,
                errors={p: error for p in settings.properties}, error=error,
                xyz_path=geometry, metadata=metadata)
        predictions.append(result)
        temporary = root / "predictions.tmp"
        temporary.write_text(json.dumps(dict(settings=settings.model_dump(mode="json"),
                              predictions=[p.model_dump(mode="json") for p in predictions]),
                              indent=2, allow_nan=False))
        temporary.replace(root / "predictions.json")
    if not candidates:
        (root / "predictions.json").write_text('{"predictions": []}\n')
    return predictions


class PropertyPredictor:
    """Bind a backend to the team's existing single-property PREDICT signature."""

    def __init__(self, settings: PredictorSettings):
        self.settings = settings

    def predict(self, candidates, target, xyz_dir):
        if target.name not in UNITS or target.units != UNITS.get(target.name):
            return [Prediction(candidate_id=c.id, status=Status.failed,
                               error="unsupported property or units") for c in candidates]
        settings = self.settings.model_copy(update={"properties": [target.name]})
        # The shared contract allows an already-created xyz_dir. Keep each request's
        # provenance separate while returning geometries at its expected <id>.xyz path.
        request_dir = Path(xyz_dir) / "property_predictions" / uuid4().hex
        records = predict_properties(candidates, settings, request_dir)
        outputs = []
        for record in records:
            result = record.as_prediction(target.name)
            if result.status is Status.ok and result.xyz_path is not None:
                try:
                    destination = (Path(xyz_dir) / f"{safe_id(result.candidate_id)}.xyz").resolve()
                    shutil.copyfile(result.xyz_path, destination)
                    result = result.model_copy(update={"xyz_path": destination})
                except Exception as exc:
                    result = Prediction(candidate_id=result.candidate_id, status=Status.failed,
                                        error=f"geometry handoff failed: {exc}")
            outputs.append(result)
        return outputs
