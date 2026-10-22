"""Stand-in for `molcurator run` in the API tests.

It runs the real agent (graph, trace, checkpoints, CURATE) with the repo's fake test tools
from tests/agent/fakes.py instead of xTB, and accepts the same arguments the API passes.
FAKE_AGENT_STEP_SECONDS slows each step down, so tests can stop a run while it is running.
FAKE_AGENT_STUBBORN=1 makes it ignore Ctrl-C and start a long-running helper in its own
session, like xtb/orca, to test that "stop" still ends both.
"""
import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # tests/server/fake_agent.py -> repo root
sys.path.insert(0, str(REPO / "tests" / "agent"))

from fakes import FakeTools  # noqa: E402

from molcurator.agent.runner import resume_agent, run_agent  # noqa: E402
from molcurator.agent.toolset import Toolset  # noqa: E402
from molcurator.config import load_config  # noqa: E402
from molcurator.tools.curate import curate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--config")
    parser.add_argument("--run-id")
    parser.add_argument("--resume")
    parser.add_argument("--runs-root")
    args = parser.parse_args()

    if os.environ.get("FAKE_AGENT_STUBBORN") == "1":
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        helper = subprocess.Popen(["sleep", "300"], start_new_session=True)
        Path(args.runs_root, "helper.pid").write_text(str(helper.pid))
        time.sleep(300)

    fake = FakeTools(seed=1)
    tools = Toolset(fake.generate, fake.predict, fake.train, fake.ml_predict, fake.validate, curate)
    delay = float(os.environ.get("FAKE_AGENT_STEP_SECONDS", "0"))

    def slow_down(event: dict) -> None:
        time.sleep(delay)

    if args.resume:
        resume_agent(args.resume, args.runs_root, tools=tools, on_event=slow_down)
    else:
        run_agent(load_config(args.config), tools=tools, runs_root=args.runs_root, run_id=args.run_id,
                  on_event=slow_down)


if __name__ == "__main__":
    main()
