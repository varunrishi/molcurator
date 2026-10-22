#!/usr/bin/env bash
# Start the MolCurator API server; the web app is served at the same address.
#
#   scripts/run.sh                   http://127.0.0.1:8000  (prints a fresh API token)
#   scripts/run.sh --port 9000
#   scripts/run.sh --host 0.0.0.0    listen on all interfaces (only behind a firewall or tunnel)
#   scripts/run.sh --install         first install the server's Python packages, then start
#
# Works from any folder: it changes to the repository root first.
#
# Settings come from environment variables or the repo's .env file; see app/server/README.md.
# Set MOLCURATOR_API_TOKEN for a token that stays the same across restarts.
set -euo pipefail
cd "$(dirname "$0")/.."   # repository root: the server reads .env and data/runs from here

HOST="${MOLCURATOR_HOST:-127.0.0.1}"
PORT="${MOLCURATOR_PORT:-8000}"
INSTALL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --install) INSTALL=1; shift ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (see scripts/run.sh --help)"; exit 2 ;;
    esac
done

# Use the project's virtual environment when there is one (scripts/setup.sh creates .venv).
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY="${PYTHON:-python3}"; fi

if [ "$INSTALL" = 1 ]; then
    "$PY" -m pip install -r app/server/requirements.txt
    "$PY" -c "import molcurator" 2>/dev/null || "$PY" -m pip install -e .
fi

if ! "$PY" -c "import fastapi, uvicorn, molcurator" 2>/dev/null; then
    echo "Missing Python packages for $PY."
    echo "Run: scripts/run.sh --install   (or: $PY -m pip install -r app/server/requirements.txt && $PY -m pip install -e .)"
    exit 1
fi

echo "MolCurator server: http://$HOST:$PORT   (API docs: http://$HOST:$PORT/api/docs)"
exec "$PY" -m uvicorn server.main:app --app-dir app --host "$HOST" --port "$PORT"