"""Prompts for the agent's decision nodes, built fresh from the state for every call (Phase 2, R3, R3.6)."""
import time

from molcurator.agent.budgets import qm_calls_left
from molcurator.agent.state import AgentState
from molcurator.agent.summaries import best_estimate, parent_options, target_distance
from molcurator.config import RunConfig

SYSTEM = ("You make one decision for MolCurator, an agent that curates molecules whose property lies in a target "
          "window. Tools run the chemistry and code enforces the budgets; you only choose the values asked for. "
          "Use only the ids you are shown, stay inside the allowed ranges, and give a one-sentence reason.")


def target_window(config: RunConfig) -> str:
    """The target as words, e.g. "between 3.0 and 3.5 eV" or, one-sided like TADF, "at most 0.2 eV"."""
    t = config.target
    window = (f"between {t.min} and {t.max}" if t.min is not None and t.max is not None
              else f"at least {t.min}" if t.min is not None else f"at most {t.max}")
    return f"{window} {t.units}"


def round_lines(stats: list) -> list[str]:
    """One line per finished round, every value named: unlabeled columns get misread by the model."""
    return [f"round {s['round']}: generated={s['generated']}, duplicates={s['duplicates']}, xtb={s['xtb_runs']}, "
            f"ml={s['ml_predicted']}, screened_in={s['screened_in']}, hits={s['hits']}" for s in stats]


def plan_round_prompt(state: AgentState, config: RunConfig) -> str:
    """Plan round (R3.1): the parent table, last round's settings and statistics, and the allowed ranges."""
    t, limits, molecules = config.target, config.generation, state["molecules"]
    lines = [f"Target: {t.name} {target_window(config)}. Round {state['round']}.",
             "Parents you may choose (id | SMILES | best estimate (level) | distance to target | status):"]
    for pid, smiles in parent_options(state, config).items():
        m = molecules.get(pid)  # seeds are not molecule records
        value = best_estimate(m) if m else None
        level = next((k for k in ("qm", "xtb", "ml") if m and m[k] is not None), "-")
        lines.append(f"{pid} | {smiles} | " + ("- | - | seed" if value is None else
                     f"{value:.2f} ({level}) | {target_distance(value, t):.2f} | {m['status']}"))
    if state["round_stats"]:
        s = state["round_stats"][-1]
        lines.append(f"Last round: plan {state['round_plan']}; generated {s['generated']}, duplicates {s['duplicates']}, "
                     f"screened in {s['screened_in']}, hits {s['hits']}.")
    lines.append(f"Allowed: generator in {limits.generators}, n_candidates 1-{limits.max_candidates}, "
                 f"mutation_strength 1-{limits.max_mutation_strength}, 1-10 parents.")
    return "\n".join(lines)


def continue_prompt(state: AgentState, config: RunConfig) -> str:
    """Continue or stop (R3.3): every round's statistics and the budgets used so far."""
    b, stats = config.budget, state["round_stats"]
    lines = [f"Target: {config.target.name}. Decide whether another round is worth running.", "Rounds so far:"]
    lines += round_lines(stats)
    used_qm = b.max_qm_calls - qm_calls_left(state, b)
    minutes = (time.time() - state["started_at"]) / 60
    lines += [f"Budgets used: rounds {state['round']}/{b.max_rounds}, QM calls {used_qm}/{b.max_qm_calls}, "
              f"dataset {state['dataset_size']}/{b.target_dataset_size}, time {minutes:.0f}/{b.max_wall_time / 60:.0f} min.",
              "Answer decision 'continue' or 'stop'. Stop early only if more rounds look unlikely to add hits; "
              "the budgets are enforced in code, so 'continue' never exceeds them."]
    return "\n".join(lines)


def summary_prompt(state: AgentState, config: RunConfig) -> str:
    """Write summary (R3.4): what the run did, round by round, and why it stopped."""
    lines = [f"Write a short Markdown report (a '# Run {state['run_id']}' heading, at most 150 words) of this "
             f"MolCurator run for a chemist. Use only the numbers given here.",
             f"Target: {config.target.name} {target_window(config)}. Seeds: {', '.join(config.seeds)}.",
             "Rounds (xtb = molecules computed with xTB; ml = scored by the ML model, 0 means ML was not used; "
             "screened_in = passed the screen; hits = added to the dataset):"]
    lines += round_lines(state["round_stats"])
    lines += [f"Last round's plan: {state['round_plan']}. Earlier rounds' settings are not recorded here, "
              "so do not describe them.",
              f"Dataset: {state['dataset_size']} molecules (target size {config.budget.target_dataset_size}).",
              f"Stopped because: {state['stop_reason']}" + (f" ({state['error']})" if state["error"] else "") + "."]
    return "\n".join(lines)
