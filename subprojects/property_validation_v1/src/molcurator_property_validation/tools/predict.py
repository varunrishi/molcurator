"""Contract adapter: lowest FF minimum -> GFN2-xTB geometry and orbital gap."""
import json
import shutil
from pathlib import Path

from molcurator_property_validation.chem.calculations import require_gap_target, run, safe_id, xtb_gap
from molcurator_property_validation.chem.geometry import lowest_ff_conformer, xyz_symbols
from molcurator.schemas import Candidate, Prediction, PropertyTarget, Status


def predict(candidates: list[Candidate], target: PropertyTarget, xyz_dir: Path) -> list[Prediction]:
    """Return one ordered result per candidate; report FF weights in per-molecule JSON."""
    results = []
    for candidate in candidates:
        try:
            require_gap_target(target)
            cid = safe_id(candidate.id)
            folder = (xyz_dir / "calculations" / cid / "xtb").resolve()
            folder.mkdir(parents=True, exist_ok=True)
            # A repeat attempt must not accept a stale optimized geometry.
            optimized = folder / "xtbopt.xyz"
            optimized.unlink(missing_ok=True)
            output = (xyz_dir / f"{cid}.xyz").resolve()
            output.unlink(missing_ok=True)
            xyz, report = lowest_ff_conformer(candidate.smiles)
            report.update(candidate_id=cid, smiles=candidate.smiles,
                          parent_smiles=candidate.parent_smiles, round=candidate.round,
                          generator=candidate.generator)
            initial = folder / "initial.xyz"
            initial.write_text(xyz)
            (folder / "geometry_report.json").write_text(json.dumps(report, indent=2))
            (folder / "geometry_report.md").write_text(
                f"# Geometry selection: {cid}\n\n"
                f"Lowest converged {report['force_field']} energy conformer: "
                f"{report['selected_ff_energy_kcal_mol']:.6f} kcal/mol.\n\n"
                f"FF-based Boltzmann weight: {report['selected_ff_boltzmann_weight']:.2%} "
                f"at {report['temperature_k']} K, among {report['n_unique']} unique "
                "sampled converged FF minima. This is conditional on the sampled "
                "conformer set and force-field energy model. The selected geometry "
                "is refined once with GFN2-xTB before QM validation.\n")
            run("XTB_BIN", "xtb", ["initial.xyz", "--gfn", "2", "--opt", "normal",
                                  "--chrg", "0", "--uhf", "0"], folder, folder / "xtb.out")
            value = xtb_gap((folder / "xtb.out").read_text(errors="replace"))
            if xyz_symbols(initial) != xyz_symbols(optimized):
                raise ValueError("xTB changed XYZ atom identities or order")
            shutil.copyfile(optimized, output)
            results.append(Prediction(candidate_id=candidate.id, status=Status.ok,
                                      value=value, xyz_path=output))
        except Exception as exc:
            results.append(Prediction(candidate_id=candidate.id, status=Status.failed,
                                      error=f"{type(exc).__name__}: {exc}"))
    return results
