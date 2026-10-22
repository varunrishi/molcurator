"""Set up a run from a plain-language prompt, with Claude.

Claude only fills in a small, typed form (RunDraft) from what the user wrote. Everything after
that is the same code the dashboard uses: the draft is merged into a run config, validated
(RunConfig), checked against what this server can run (capabilities.preflight), and the seed
is checked and drawn with RDKit (chem.inspect_smiles). Nothing is started here: the web app
shows the proposal and the user presses Start.

Available only when ANTHROPIC_API_KEY is set on the server (the web app hides it otherwise).
"""
import copy
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from molcurator.config import RunConfig

from molcurator.chem.properties import SCALAR_PROPERTIES

from . import capabilities, chem
from .settings import Settings

DEFAULT_MODEL = "claude-haiku-4-5"


class RunDraft(BaseModel):
    """What Claude may set. Fields left null keep the current value (or the preset's default)."""

    understood: bool = Field(description="false if the message is not a request to set up or change a run")
    target_property: Literal[SCALAR_PROPERTIES + ("other",)] | None = Field(
        None, description="the property asked for; null if not mentioned")
    window_min: float | None = Field(None, description="lower bound of the target window, in the property's unit, only if given")
    window_max: float | None = Field(None, description="upper bound of the target window, in the property's unit, only if given")
    seed_smiles: str | None = Field(None, description="seed molecule as SMILES, only if a molecule was given")
    seed_name: str | None = Field(None, description="the molecule name the user wrote, if they named it instead of giving SMILES")
    candidates_per_round: int | None = None
    max_rounds: int | None = None
    target_dataset_size: int | None = Field(None, description="stop once this many molecules are curated")
    max_minutes: int | None = Field(None, description="time budget in minutes")
    qm: bool | None = Field(None, description="true to validate hits with DFT (ORCA), false to turn it off")
    reply: str = Field(description="one or two sentences to the user: what you set, what you need")
    missing: list[str] = Field(default_factory=list, description="information still needed, e.g. 'seed molecule'")


def _property_list() -> str:
    return "\n".join(f"- {t['name']} ({t['label']}; unit {t['units'] or 'none'}; PREDICT: {t['predict_method']})"
                      for t in capabilities.TARGETS)


SYSTEM = """You set up runs of MolCurator, an agent that searches for molecules whose value of one
property lies in a target window. It starts from a seed molecule, generates candidates, estimates the
property cheaply (PREDICT: GFN2-xTB where xTB can give it, else B97-3c DFT through ORCA) and with an
ML model, confirms hits with DFT (ORCA) when QM validation is on, and curates a dataset.

Properties a run can target (name, unit, PREDICT method):
""" + _property_list() + """

Fill in the RunDraft form from the user's message.
- Set a field only when the user gave that value. Leave everything else null; never guess numbers.
- The window is in the property's unit above. "TADF" or "singlet-triplet gap" means s1_t1_gap.
  If the user asks for a property not in the list, set target_property to "other".
- If the user names a molecule instead of giving SMILES, give its correct SMILES in seed_smiles and
  the name in seed_name. If you are not sure of the structure, leave seed_smiles null and list
  "seed molecule" in missing.
- When a current configuration is given, the message changes it: only set what the user changes.
- understood=false for messages that are not about setting up a run (then explain in reply).
- reply: short, plain, no markdown."""


def available(settings: Settings) -> bool:
    return bool(settings.env_value("ANTHROPIC_API_KEY"))


def model_name(settings: Settings) -> str:
    name = settings.env_value("LLM_MODEL") or DEFAULT_MODEL
    return name if name.startswith("claude-") else DEFAULT_MODEL  # .env may name a local model for the agent


def make_client(settings: Settings):
    import anthropic
    return anthropic.Anthropic(api_key=settings.env_value("ANTHROPIC_API_KEY"), max_retries=1)


def ask_claude(client, model: str, prompt: str, current: dict | None) -> RunDraft:
    message = prompt if current is None else (
        "Current configuration (JSON):\n" + _short_config(current) + "\n\nUser message:\n" + prompt)
    reply = client.messages.parse(model=model, max_tokens=1024, system=SYSTEM, output_format=RunDraft,
                                  messages=[{"role": "user", "content": message}], timeout=30)
    if reply.parsed_output is None:
        raise ValueError("Claude did not return a structured answer")
    return reply.parsed_output


def _short_config(config: dict) -> str:
    import json
    keep = {k: config.get(k) for k in ("target", "seeds", "budget", "qm", "decisions")}
    keep["generation"] = {"n_candidates": config.get("generation", {}).get("defaults", {}).get("n_candidates")}
    return json.dumps(keep)


def base_for(target: str, presets: list[dict]) -> dict:
    """Starting config for a target: the shipped preset for it (configs/homo_lumo.yaml,
    configs/tadf.yaml), else the preset whose PREDICT method fits (xTB or ORCA) with the target
    swapped in. The xTB-to-DFT gap correction is kept only for homo_lumo_gap, which it is fitted for."""
    by_name = {p["config"]["target"]["name"]: p["config"] for p in presets}
    if target in by_name:
        return copy.deepcopy(by_name[target])
    info = capabilities.target_info(target)
    model = by_name.get("s1_t1_gap" if info and info["needs_orca"] else "homo_lumo_gap") or next(iter(by_name.values()))
    config = copy.deepcopy(model)
    config["target"].update(name=target, units=info["units"] if info else None)
    config["predict"]["correction"] = None
    return config


def build_plan(draft: RunDraft, presets: list[dict], current: dict | None, settings: Settings) -> dict:
    """Merge the draft into a config and check it. `presets` are the shipped configs (all defaults
    filled in); `current` is the proposal being refined, if any."""
    target = draft.target_property or ((current or {}).get("target") or {}).get("name") or "homo_lumo_gap"
    notes, defaults_used = [], []
    if target == "other":
        return {"understood": draft.understood, "reply": draft.reply, "missing": draft.missing,
                "config": current, "seed": None, "warnings": [], "defaults_used": [], "ready": False,
                "problems": ["That property is not one the tools compute. Choose one of: " +
                             ", ".join(t["name"] for t in capabilities.TARGETS) + "."]}
    if current is not None and current["target"]["name"] == target:
        config = copy.deepcopy(current)
    else:
        # A new proposal, or a new target: the window and seed come from the user, never from a preset.
        config = base_for(target, presets)
        config["target"]["min"] = config["target"]["max"] = None
        config["seeds"] = []
        orca_found = capabilities.tool_status(settings)["orca"]["found"]
        config["qm"]["enabled"] = orca_found  # QM validation is on by default where ORCA can run it
        if not orca_found:
            notes.append("QM validation is off because ORCA was not found on the server.")
        if current is not None:  # keep what the user already chose
            config["seeds"] = current.get("seeds") or []
            config["budget"] = current["budget"]
            config["generation"]["defaults"]["n_candidates"] = current["generation"]["defaults"]["n_candidates"]
            config["qm"]["enabled"] = current["qm"]["enabled"]

    if draft.window_min is not None:
        config["target"]["min"] = draft.window_min
    if draft.window_max is not None:
        config["target"]["max"] = draft.window_max
    if draft.seed_smiles:
        config["seeds"] = [draft.seed_smiles]
    gen = config["generation"]["defaults"]
    if draft.candidates_per_round is not None:
        gen["n_candidates"] = draft.candidates_per_round
    budget = config["budget"]
    if draft.max_rounds is not None:
        budget["max_rounds"] = draft.max_rounds
    if draft.target_dataset_size is not None:
        budget["target_dataset_size"] = draft.target_dataset_size
    if draft.max_minutes is not None:
        budget["max_wall_time"] = draft.max_minutes * 60
    if draft.qm is not None:
        config["qm"]["enabled"] = draft.qm

    problems = []
    if config["target"].get("min") is None and config["target"].get("max") is None:
        unit = (capabilities.target_info(target) or {}).get("units") or ""
        problems.append(f"No target window given: give a minimum and/or maximum for {target}" +
                        (f" in {unit}." if unit else " (no unit)."))
    if not config.get("seeds"):
        problems.append("No seed molecule given: name one or give its SMILES.")
    if current is None:
        for label, given in (("candidates per round", draft.candidates_per_round), ("rounds", draft.max_rounds),
                             ("dataset size", draft.target_dataset_size), ("time budget", draft.max_minutes),
                             ("QM", draft.qm)):
            if given is None:
                defaults_used.append(label)
    if draft.seed_name and draft.seed_smiles:
        notes.append(f"The seed SMILES was written by Claude from the name '{draft.seed_name}'. Check the drawing.")

    seed = chem.inspect_smiles(config["seeds"][0]) if config.get("seeds") else None
    if seed is not None and not seed["valid"]:
        problems.append(f"The seed '{config['seeds'][0]}' is not a valid molecule.")

    warnings, level = [], None
    try:
        parsed = RunConfig.model_validate(config)
        config = parsed.model_dump(mode="json")
        level = capabilities.predict_level(parsed)
        blocking, warnings = capabilities.preflight(parsed, settings)
        problems += blocking
    except ValidationError as e:
        for err in e.errors():
            where = ".".join(str(p) for p in err["loc"])
            if problems and where.split(".")[0] in ("seeds", "target"):
                continue  # already explained above in plain words
            problems.append(f"{where}: {err['msg']}")
    if seed is not None and seed["valid"]:
        warnings = [f"Seed: {p}" for p in seed["problems"]] + warnings

    return {"understood": draft.understood, "reply": draft.reply, "missing": draft.missing,
            "config": config, "seed": seed, "problems": problems, "warnings": notes + warnings,
            "target": capabilities.target_info(target), "predict_level": level,
            "defaults_used": defaults_used, "ready": draft.understood and not problems}
