"""Live check of the LLM decider: a 3-round run with real Claude deciding and fake chemistry.

Calls the Anthropic API (about 7 short requests to Claude Haiku 4.5, a few cents), so it needs
ANTHROPIC_API_KEY in .env. Prints every decision with how it was made (fallback, retry, duration),
then the summary, so it can be checked by hand against the round stats printed below it.

    .venv/bin/python scripts/check_llm_decider.py <out_dir>
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # tests.agent.fakes, for the fake chemistry tools

from molcurator.agent.runner import run_agent
from molcurator.agent.toolset import Toolset
from molcurator.config import RunConfig, load_config
from tests.agent.fakes import FakeTools


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir", type=Path, help="where the run folder live-llm/ is written; "
                                                         "an existing live-llm/ there is never overwritten")
    args = parser.parse_args(argv)
    data = load_config(ROOT / "configs" / "homo_lumo.yaml").model_dump()
    data["decisions"] = "llm"
    data["budget"].update(target_dataset_size=1000, max_rounds=3)  # out of reach, so all 3 rounds run
    state = run_agent(RunConfig.model_validate(data), tools=Toolset.from_object(FakeTools()),
                      runs_root=args.out_dir, run_id="live-llm")
    events = [json.loads(line) for line in (args.out_dir / "live-llm" / "traces" / "trace.jsonl").read_text().splitlines()]
    for e in events:
        if "llm" in e:
            llm, d = e["llm"], e["llm"]["decision"]
            detail = d.get("reason") or d.get("summary", "")[:60].replace("\n", " ")
            plan = f" parents={d['parents']} n={d['n_candidates']} strength={d['mutation_strength']}" if "parents" in d else ""
            print(f"r{e['round']} {e['node']:16} {llm['source']:4} fallback={llm['fallback']} retried={llm['retried']} "
                  f"{llm['duration_s']:.1f}s{plan} | {detail}")
    print(f"\nstop: {state['stop_reason']} | dataset: {state['dataset_size']}\n")
    print((args.out_dir / "live-llm" / "summary.md").read_text())
    print("Recorded round stats, to check the summary against:")
    for s in state["round_stats"]:
        print({k: s[k] for k in ("round", "generated", "duplicates", "xtb_runs", "ml_predicted", "screened_in", "hits")})


if __name__ == "__main__":
    main()
