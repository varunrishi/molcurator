"""Run the actual upstream v1 agent with real tools and deliberately unavailable xTB.

This is a failure-handling demo, not a successful property/QM calculation. The
agent runs in a child process so its newer config cannot contaminate this reader.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from molcurator.trajectory_evaluation import evaluate_trajectory, load_trace

AGENT_PROGRAM = r'''
import json, os, pathlib, sys
agent_source, output = map(pathlib.Path, sys.argv[1:3])
sys.path.insert(0, str(agent_source / "subprojects/property_validation_v1/src"))
sys.path.insert(0, str(agent_source / "src"))
os.environ["XTB_BIN"] = str(output / "deliberately-unavailable-xtb")
settings = output / "chemistry.json"
settings.write_text(json.dumps(dict(nconfs=3, timeout_s=30)), encoding="utf-8")
os.environ["MOLCURATOR_CHEM_CONFIG"] = str(settings)
from molcurator.agent.decisions import RuleDecider
from molcurator.agent.graph import NODES, build_graph, initial_state
from molcurator.agent.toolset import Toolset
from molcurator.agent.trace import TraceWriter, write_run_start
from molcurator.config import RunConfig
config = RunConfig.model_validate(dict(
    target=dict(name="homo_lumo_gap", min=3., max=3.5), seeds=["CCO"],
    generation=dict(defaults=dict(n_candidates=4, mutation_strength=1)),
    predict=dict(n_xtb=2), train=dict(min_examples=200), qm=dict(enabled=False),
    decisions="rules", rng_seed=0,
    budget=dict(max_rounds=1, max_qm_calls=10, target_dataset_size=10, max_wall_time=120)))
writer = TraceWriter(output, "agent-v1-demo")
write_run_start(writer, config, NODES)
graph = build_graph(config, Toolset.default(), RuleDecider(), trace=writer)
state = graph.invoke(initial_state("agent-v1-demo", output), {"recursion_limit": 20})
(output / "agent-final-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
print(json.dumps(dict(stop_reason=state["stop_reason"], error=state["error"], dataset_size=state["dataset_size"])))
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-source", type=Path, required=True)
    parser.add_argument("--agent-revision", help="Source revision for provenance (recorded as supplied)")
    parser.add_argument("--out", type=Path, required=True, help="New output directory")
    args = parser.parse_args(argv)
    source, output = args.agent_source.resolve(), args.out.resolve()
    required = [source / "src/molcurator/agent" / name for name in ("graph.py", "trace.py")]
    if not all(path.is_file() for path in required):
        parser.error("agent-source must contain the actual v1 graph.py and trace.py")
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.error(str(exc))
    run = subprocess.run([sys.executable, "-B", "-c", AGENT_PROGRAM, str(source), str(output)],
        cwd=output, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", LANGSMITH_TRACING="false",
                            LANGCHAIN_TRACING_V2="false"), capture_output=True, text=True)
    (output / "agent-stdout.txt").write_text(run.stdout, encoding="utf-8")
    (output / "agent-stderr.txt").write_text(run.stderr, encoding="utf-8")
    manifest = dict(agent_source=str(source), agent_revision_supplied=args.agent_revision,
        agent_source_hashes={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in required},
        demo_kind="actual_agent_real_tools_with_unavailable_xtb", real_property_calculations=False,
        qm_enabled=False, agent_exit_code=run.returncode)
    (output / "demo-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if run.returncode:
        print(f"Agent failed; inspect {output / 'agent-stderr.txt'}", file=sys.stderr)
        return run.returncode
    events, provenance = load_trace(output / "traces/trace.jsonl")
    report = evaluate_trajectory(events, source=provenance)
    (output / "evaluation.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(dict(overall=report["overall"], checks=report["checks"],
        capabilities=report["capabilities"], summary=report["summary"]), indent=2))
    return 1 if report["overall"] == "fail" else 3 if report["overall"] == "not_assessable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
