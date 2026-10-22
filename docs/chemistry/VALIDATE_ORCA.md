# ORCA reference validation tool

Branch `tools/validate-orca` implements `validate(items, target, qm)` using unchanged shared Prediction/QMResult/QMSettings contracts. It supports HOMO–LUMO orbital gaps in eV for neutral closed-shell geometries. Input is the selected batch of successful predictions with existing XYZ paths. It does not generate molecules, prepare another geometry, select a target band or schedule jobs.

```python
from molcurator_property_validation.tools.validate import validate
# results = validate(selected_predictions, config.target, config.qm)
```

Set `ORCA_BIN` to the executable or put `orca` on PATH. The functional and basis come from QMSettings. The tool writes a TightSCF neutral-singlet single-point input, runs one process per item, requires successful termination/SCF convergence, and reads the final orbital table. It retains every input ID/order, including failures. Input geometries must have correct molecular identity; syntax validation alone cannot establish stereochemical provenance.

Artifacts are beside the XYZ under `calculations/<id>/orca/`: `gap.inp`, copied geometry, `orca.out`, and `attempt.json`. Failed attempted calculations count as expensive work. The attempt file describes the latest invocation, not cumulative campaign usage. There are no hidden retries; the agent owns selection, lifetime budgets and checkpointing.

Run real chemistry on an allocated compute node. Offline tests use synthetic program output. TADF, other requested properties, PySCF, automatic cache reuse and the wider multi-property API remain separate work. Root tools and agent modules are untouched; inject the callable explicitly.
