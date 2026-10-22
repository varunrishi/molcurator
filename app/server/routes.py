"""All API endpoints. Every path starts with /api; see docs/api/ for the full reference.

Two groups:
- system: health, tools and capabilities, presets, config validation, seed inspection
- runs:   start, list, watch (overview + events), results, downloads, stop, resume
"""
import math
import secrets
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, ValidationError
from starlette.background import BackgroundTask

from molcurator.config import RunConfig, load_config

from . import __version__, assistant, capabilities, chem, run_files
from .run_manager import RunConflict, RunManager
from .settings import Settings

bearer = HTTPBearer(auto_error=False)  # also adds the "Authorize" button to /api/docs


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


def runs_of(request: Request) -> RunManager:
    return request.app.state.runs


def require_token(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    """Every endpoint except /api/health needs "Authorization: Bearer <token>" (unless auth is off)."""
    expected = settings_of(request).api_token
    if expected is None:
        return
    if credentials is None or not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(401, "Missing or wrong API token. Send 'Authorization: Bearer <token>'.")


public = APIRouter(prefix="/api", tags=["system"])
system = APIRouter(prefix="/api", tags=["system"], dependencies=[Depends(require_token)])
runs = APIRouter(prefix="/api/runs", tags=["runs"], dependencies=[Depends(require_token)])


# ====================================================================== helpers
class ConfigBody(BaseModel):
    config: dict[str, Any] = Field(description="A run config, as in configs/*.yaml (missing keys use defaults).")


class StartBody(ConfigBody):
    run_id: str | None = Field(None, description="Optional run folder name; default: UTC time + random suffix.")


class InspectBody(BaseModel):
    smiles: str
    xyz: bool = Field(True, description="Also return a quick 3D preview structure (XYZ).")


def parse_config(raw: dict) -> RunConfig:
    """A validated RunConfig, or HTTP 422 listing every problem."""
    try:
        return RunConfig.model_validate(raw)
    except ValidationError as e:
        problems = [f"{'.'.join(str(p) for p in err['loc']) or 'config'}: {err['msg']}" for err in e.errors()]
        raise HTTPException(422, {"message": "Invalid run configuration.", "problems": problems})


def open_run(request: Request, run_id: str) -> Path:
    try:
        return run_files.run_dir(settings_of(request), run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


def json_safe(value):
    """NaN/inf are not valid JSON; send them as null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    return value


# ====================================================================== system
@public.get("/health")
def health(request: Request) -> dict:
    """Is the server up? Needs no token, so a client can find out whether it must ask for one."""
    s = settings_of(request)
    return {"status": "ok", "version": __version__, "auth_required": s.api_token is not None,
            "repo_url": s.repo_url}


@system.get("/system")
def system_info(request: Request) -> dict:
    """External programs found on the server, what this version supports, and the run limit."""
    s = settings_of(request)
    return {"version": __version__, "tools": capabilities.tool_status(s), "capabilities": capabilities.capabilities(),
            "limits": {"max_concurrent_runs": s.max_runs, "running": runs_of(request).running_ids()},
            "assistant": {"available": assistant.available(s), "model": assistant.model_name(s)}}


@system.get("/presets")
def presets(request: Request) -> list[dict]:
    """The use-case configs shipped in configs/*.yaml, with every default filled in."""
    out = []
    orca_found = capabilities.tool_status(settings_of(request))["orca"]["found"]
    for path in sorted((settings_of(request).repo / "configs").glob("*.yaml")):
        text = path.read_text()
        try:  # load_config, as the CLI does: it also reads `seeds_file:` (a seeds CSV next to the YAML)
            parsed = load_config(path)
        except (ValueError, OSError):  # an invalid config (ValidationError is a ValueError) or a missing seeds file
            continue
        config = parsed.model_dump(mode="json")
        level = capabilities.predict_level(parsed)
        notes = []
        if "PLACEHOLDER" in text:
            notes.append("The seed in this preset is a placeholder; replace it with your own molecule.")
        if not level["xtb"] and not orca_found:
            notes.append(f"PREDICT runs {level['label']} through ORCA, which was not found on this server.")
        out.append({"name": path.stem, "file": f"configs/{path.name}", "supported": True, "reason": None,
                    "predict_level": level, "notes": notes, "config": config})
    return out


@system.get("/config/schema")
def config_schema() -> dict:
    """JSON Schema of a run config (the RunConfig model in src/molcurator/config.py)."""
    return RunConfig.model_json_schema()


@system.post("/config/validate")
def validate_config(body: ConfigBody, request: Request) -> dict:
    """Check a config without starting a run: the normalised config, blocking problems and warnings."""
    try:
        config = parse_config(body.config)
    except HTTPException as e:
        return {"valid": False, "config": None, "problems": e.detail["problems"], "warnings": []}
    problems, warnings = capabilities.preflight(config, settings_of(request))
    return {"valid": not problems, "config": config.model_dump(mode="json"), "problems": problems, "warnings": warnings}


@system.post("/chem/inspect")
def inspect_molecule(body: InspectBody) -> dict:
    """Canonical SMILES (RDKit), problems the tools would reject, and a quick 3D preview."""
    return chem.inspect_smiles(body.smiles, with_xyz=body.xyz)


class PlanBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000, description="What the user wants, in plain language.")
    current: dict[str, Any] | None = Field(None, description="The proposal being refined (from a previous answer).")


@system.post("/assistant/plan")
def assistant_plan(body: PlanBody, request: Request) -> dict:
    """Turn a prompt into a proposed run config with Claude, checked like any other config.
    Nothing is started: the client shows the proposal and starts it with POST /api/runs."""
    s = settings_of(request)
    if not assistant.available(s):
        raise HTTPException(503, "The assistant needs ANTHROPIC_API_KEY on the server.")
    shipped = presets(request)
    if not shipped:
        raise HTTPException(500, "No valid preset in configs/*.yaml to start a proposal from.")
    client = request.app.state.assistant_client(s)
    try:
        draft = assistant.ask_claude(client, assistant.model_name(s), body.prompt, body.current)
    except ValueError as e:
        raise HTTPException(502, f"Claude's answer could not be used: {e}")
    except Exception as e:  # API errors, timeouts: reported, never replaced by a guess
        raise HTTPException(502, f"Claude could not be reached: {type(e).__name__}: {e}")
    plan = assistant.build_plan(draft, shipped, body.current, s)
    plan["model"] = assistant.model_name(s)
    return json_safe(plan)


# ====================================================================== runs
@runs.get("")
def list_runs(request: Request) -> list[dict]:
    """All runs, newest first."""
    s, manager = settings_of(request), runs_of(request)
    items = []
    for run_id in run_files.list_run_ids(s):
        path = s.runs_root / run_id
        items.append(run_files.list_item(run_id, path, run_files.read_events(path), manager.process(run_id)))
    return items


@runs.post("", status_code=202)
def start_run(body: StartBody, request: Request) -> dict:
    """Validate the config, check the server can run it, and start the agent in the background."""
    config = parse_config(body.config)
    problems, warnings = capabilities.preflight(config, settings_of(request))
    if problems:
        raise HTTPException(422, {"message": "This run cannot start on this server.", "problems": problems})
    try:
        run_id = runs_of(request).start(config, body.run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RunConflict as e:
        raise HTTPException(409, str(e))
    return {"run_id": run_id, "status": "running", "warnings": warnings}


@runs.get("/{run_id}")
def run_overview(request: Request, run_id: str,
                 events_since: int | None = Query(None, ge=0, description="Also return trace events from this index."),
                 compact: bool = Query(True, description="Replace per-molecule result lists by counts.")) -> dict:
    """Status, current step, round statistics and budget use. With events_since, also the new trace
    events, so a client can follow a run with one request per poll."""
    manager = runs_of(request)
    try:
        path = run_files.run_dir(settings_of(request), run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError:
        process = manager.process(run_id)
        if not process["tracked"]:
            raise HTTPException(404, f"run {run_id!r} not found")
        return starting_overview(run_id, process, events_since)  # the agent has not created its folder yet
    events = run_files.read_events(path)
    out = run_files.overview(run_id, path, events, manager.process(run_id))
    if events_since is not None:
        new = events[events_since:]
        out["events"] = [run_files.compact_event(e) for e in new] if compact else new
        out["events_next"] = len(events)
    return json_safe(out)


def starting_overview(run_id: str, process: dict, events_since: int | None) -> dict:
    """The overview of a run whose process has started but not yet created its folder (or died first)."""
    if process["alive"]:
        status = "starting"
    else:  # exited before creating its folder: stopped by the user, or failed (see the log)
        status = "interrupted" if process["stop_requested"] else "failed"
    failed = status == "failed"
    out = {"run_id": run_id, "status": status, "resumable": False,
           "exit_code": process["exit_code"], "started_at": None, "updated_at": None, "running_seconds": 0,
           "target": None, "qm_enabled": False, "decisions": None, "nodes": [], "current": {"node": None, "round": None},
           "last_event": None, "rounds": [], "budget": {}, "stop_reason": None,
           "error": "The agent exited before creating the run folder; see the run log." if failed else None,
           "event_count": 0, "files": {}}
    if events_since is not None:
        out["events"], out["events_next"] = [], 0
    return out


@runs.get("/{run_id}/events")
def run_events(request: Request, run_id: str, since: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=10000),
               compact: bool = False) -> dict:
    """Trace events (one per finished step) from index `since`; `next` is the index to ask for next time."""
    events = run_files.read_events(open_run(request, run_id))
    chunk = events[since:since + limit]
    return json_safe({"events": [run_files.compact_event(e) for e in chunk] if compact else chunk,
                      "next": since + len(chunk), "total": len(events)})


@runs.get("/{run_id}/molecules")
def run_molecules(request: Request, run_id: str) -> list[dict]:
    """Every molecule of the run with its status and values at each level (rebuilt from the trace)."""
    path = open_run(request, run_id)
    return json_safe(run_files.molecules(path, run_files.read_events(path), run_files.read_config(path)))


@runs.get("/{run_id}/dataset")
def run_dataset(request: Request, run_id: str) -> list[dict]:
    """The curated dataset (dataset.csv) as JSON rows."""
    return json_safe(run_files.dataset_rows(open_run(request, run_id)))


@runs.get("/{run_id}/molecules/{molecule_id}/xyz", response_class=PlainTextResponse)
def molecule_xyz(request: Request, run_id: str, molecule_id: str) -> str:
    """The geometry PREDICT selected for a molecule (MMFF94, XYZ format)."""
    path = open_run(request, run_id)
    try:
        file = path / "xyz" / f"{run_files.check_id(molecule_id)}.xyz"
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not file.is_file():
        raise HTTPException(404, f"no geometry for {molecule_id!r}")
    return file.read_text()


@runs.get("/{run_id}/files/{name}")
def download_file(request: Request, run_id: str, name: str) -> FileResponse:
    """Download one run file: dataset.csv, dataset_ml_only.csv, summary.md, config.yaml or trace.jsonl."""
    path = open_run(request, run_id)
    if name not in run_files.DOWNLOADS:
        raise HTTPException(404, f"unknown file {name!r}; choose one of {sorted(run_files.DOWNLOADS)}")
    file = path / run_files.DOWNLOADS[name]
    if not file.is_file():
        raise HTTPException(404, f"{name} does not exist yet for this run")
    return FileResponse(file, filename=f"{run_id}-{name}")


@runs.get("/{run_id}/archive")
def download_archive(request: Request, run_id: str) -> FileResponse:
    """The whole run folder as a .zip (dataset, geometries, models, trace, summary, checkpoint)."""
    path = open_run(request, run_id)
    tmp = Path(tempfile.mkdtemp())
    archive = tmp / f"{run_id}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for file in sorted(path.rglob("*")):
            if file.is_file():
                z.write(file, Path(run_id) / file.relative_to(path))
    return FileResponse(archive, filename=archive.name, media_type="application/zip",
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@runs.get("/{run_id}/log", response_class=PlainTextResponse)
def run_log(request: Request, run_id: str, lines: int = Query(200, ge=1, le=5000)) -> str:
    """The last lines the agent process printed (only for runs started through the API)."""
    try:
        return runs_of(request).log_tail(run_id, lines)
    except ValueError as e:
        raise HTTPException(400, str(e))


@runs.get("/{run_id}/evaluation")
def run_evaluation(request: Request, run_id: str) -> dict:
    """Check the run's trace with the trajectory evaluator (src/molcurator/trajectory_evaluation.py)."""
    from molcurator.trajectory_evaluation import evaluate_trajectory, load_trace
    path = open_run(request, run_id)
    trace = path / "traces" / "trace.jsonl"
    if not trace.is_file():
        raise HTTPException(404, "this run has no trace yet")
    try:
        events, source = load_trace(trace)
        report = evaluate_trajectory(events, source=source)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, f"the evaluator could not read this trace: {e}")
    return json_safe(report)


@runs.post("/{run_id}/stop", status_code=202)
def stop_run(request: Request, run_id: str) -> dict:
    """Stop a running run (like Ctrl-C). Finished steps are kept, so it can be resumed."""
    try:
        run_files.check_id(run_id)
        runs_of(request).stop(run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RunConflict as e:
        raise HTTPException(409, str(e))
    return {"run_id": run_id, "status": "stopping"}


@runs.post("/{run_id}/resume", status_code=202)
def resume_run(request: Request, run_id: str) -> dict:
    """Continue an interrupted run from its last finished step, with its saved config."""
    path = open_run(request, run_id)
    overview = run_files.overview(run_id, path, run_files.read_events(path), runs_of(request).process(run_id))
    if not overview["resumable"]:
        raise HTTPException(409, f"run {run_id!r} cannot be resumed (status: {overview['status']})")
    try:
        runs_of(request).resume(run_id)
    except RunConflict as e:
        raise HTTPException(409, str(e))
    return {"run_id": run_id, "status": "running"}
