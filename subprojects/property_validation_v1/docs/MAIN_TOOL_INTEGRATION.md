# Main tool integration

The ordinary imports used by the agent now delegate to the chemistry implementation:

```python
from molcurator.tools.predict import predict
from molcurator.tools.validate import validate

# predictions = predict(candidates, config.target, run_dir / 'xyz')
# results = validate(selected_predictions, config.target, config.qm)
```

Signatures and shared result models are unchanged. Root setuptools includes the isolated implementation in the normal root installation, so no sys.path manipulation or second subproject installation is required. In an existing compatible environment, run `python -m pip install --no-deps -e .` from the repository root to refresh installation; use the project's normal dependency setup on a fresh machine.

Export XTB_BIN and ORCA_BIN or place executables on PATH and load required cluster runtime modules. PREDICT estimates raw GFN2-xTB HOMO-LUMO gap in eV and returns an optimized XYZ. VALIDATE reuses that geometry for one configured ORCA single point per selected molecule. IDs/order, failed records, geometry reports, raw logs and attempt records are retained. The graph owns selection and cumulative budgets.

Scope is neutral closed-shell HOMO-LUMO gaps. PySCF, TADF and ML selection remain separate work. No graph, schema, screening policy or LLM decision changes are included. The agent/orchestrator branch's Toolset.default() already imports these root functions and will use them when both contributions are integrated.

This integration PR includes the implementation from PRs #3 and #4 plus the missing root entry points, packaging and public-import tests. It supersedes separately integrating those implementation-only patches for this use case. Merge through review; no direct changes to main are made.

Tests verify public imports, argument/result delegation, mixed failures, configured ORCA method and geometry reuse. External program output is simulated; actual cluster compatibility still needs real calculations. The root install/wheel check verifies that both package trees are included.
