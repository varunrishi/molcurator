"""The FastAPI application: API routes under /api, interactive docs at /api/docs, and the
web app (app/web) at "/".

Start it with scripts/run.sh, or from the repository root:
    python -m uvicorn server.main:app --app-dir app --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from . import __version__, assistant, routes
from .run_manager import RunManager
from .settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="MolCurator API", version=__version__,
                  description="Start, watch and download MolCurator agent runs. Reference: docs/api/.",
                  docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.runs = RunManager(settings)
    app.state.assistant_client = assistant.make_client  # tests replace it with a fake Claude

    # Token auth (not cookies) protects the API, so any origin may call it; restrict with MOLCURATOR_CORS_ORIGINS.
    # Compress responses: the web app's structure library shrinks from 3.5 MB to about 1 MB, which
    # matters behind a tunnel (ngrok's free plan allows 1 GB a month).
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
    app.include_router(routes.public)
    app.include_router(routes.system)
    app.include_router(routes.runs)

    if settings.web_dir.is_dir():  # mounted last, so /api/* always wins
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")

    print(f"MolCurator API {__version__}: repo {settings.repo}, runs in {settings.runs_root}", flush=True)
    if settings.api_token is None:
        print("WARNING: authentication is off (MOLCURATOR_NO_AUTH=1). Do not expose this server publicly.", flush=True)
    elif settings.token_was_generated:
        print(f"API token (enter it in the web app's Settings): {settings.api_token}", flush=True)
    return app


app = create_app()
