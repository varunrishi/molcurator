#!/usr/bin/env bash
# One-command setup for MolCurator:
#   1. .env settings file (from .env.example)
#   2. Python dependencies with uv (installs uv if missing)
#   3. ORCA check (xTB comes with the Python dependencies, through tblite)
#   4. Decision model: checks the Anthropic key, or sets up Ollama for the OpenAI-compatible backend
#
# Usage: scripts/setup.sh [--no-llm]
#   --no-llm   skip the Ollama step (e.g. a hosted LLM is configured in .env)
#
# Safe to re-run: every step skips work that is already done.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TOOLS_DIR="$ROOT/.tools"
OLLAMA_URL="http://localhost:11434"

SKIP_LLM=0
for arg in "$@"; do
    case "$arg" in
        --no-llm) SKIP_LLM=1 ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

PENDING=()
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m  %s\n' "$*"; }
warn() { printf '  \033[33m!!\033[0m  %s\n' "$*"; }

# Set KEY=VALUE in .env, replacing an existing line or appending a new one.
set_env_var() {
    local key="$1" value="$2" tmp
    tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" '
        BEGIN { done = 0 }
        $0 ~ "^"k"=" { print k"="v; done = 1; next }
        { print }
        END { if (!done) print k"="v }
    ' .env > "$tmp"
    mv "$tmp" .env
}

# ---------------------------------------------------------------- 1. .env
step "Settings (.env)"
if [ ! -f .env ]; then
    cp .env.example .env
    ok "created .env from .env.example"
else
    ok ".env already exists"
fi
# Load .env; variables already set in the environment take precedence.
while IFS='=' read -r key value; do
    case "$key" in ''|\#*) continue ;; esac
    if [ -z "${!key:-}" ]; then export "$key=$value"; fi
done < .env

# ---------------------------------------------------------------- 2. Python deps
step "Python dependencies (uv)"
if ! command -v uv >/dev/null 2>&1; then
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "  uv not found, installing it from https://astral.sh/uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
uv sync
ok "Python environment ready in .venv/"

# ---------------------------------------------------------------- 3. ORCA
# xTB needs no step: it runs through tblite, installed with the Python dependencies.
# ORCA (licensed) cannot be installed here; this only finds it and saves ORCA_BIN.
step "ORCA"
if [ -n "${ORCA_BIN:-}" ] && [ -x "${ORCA_BIN}" ]; then
    ok "using ORCA_BIN=$ORCA_BIN"
elif command -v orca >/dev/null 2>&1; then
    set_env_var ORCA_BIN "$(command -v orca)"
    ok "found orca on PATH: $(command -v orca) (ORCA_BIN saved to .env)"
else
    warn "ORCA not found"
    PENDING+=("Install ORCA 6.1.1 or newer (free academic licence: https://orcaforum.kofo.mpg.de), then set ORCA_BIN in .env. Needed for VALIDATE and for TD-DFT targets such as s1_t1_gap")
fi

# Open MPI, for ORCA on more than one core (orca_nprocs > 1): OPENMPI_HOME, else mpirun on
# PATH, else the first conda env (or base) that has one, saved as OPENMPI_HOME.
if [ -n "${OPENMPI_HOME:-}" ] && [ -x "${OPENMPI_HOME}/bin/mpirun" ]; then
    ok "using OPENMPI_HOME=$OPENMPI_HOME"
elif command -v mpirun >/dev/null 2>&1; then
    ok "found mpirun on PATH: $(command -v mpirun)"
else
    MPIRUN=""
    for base in "${CONDA_PREFIX:-}" "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3" /opt/conda; do
        [ -n "$base" ] || continue
        for candidate in "$base/bin/mpirun" "$base"/envs/*/bin/mpirun; do
            if [ -x "$candidate" ]; then MPIRUN="$candidate"; break 2; fi
        done
    done
    if [ -n "$MPIRUN" ]; then
        set_env_var OPENMPI_HOME "$(dirname "$(dirname "$MPIRUN")")"
        ok "found Open MPI: $MPIRUN (OPENMPI_HOME saved to .env)"
    else
        warn "Open MPI not found: ORCA runs on one core (orca_nprocs = 1)"
    fi
fi

# ---------------------------------------------------------------- 4. LLM
step "Decision model"
LLM_PROVIDER="${LLM_PROVIDER:-anthropic}"
if [ "$LLM_PROVIDER" = "anthropic" ]; then DEFAULT_MODEL="claude-haiku-4-5"; else DEFAULT_MODEL="qwen3:4b"; fi
LLM_MODEL="${LLM_MODEL:-$DEFAULT_MODEL}"
LLM_BASE_URL="${LLM_BASE_URL:-$OLLAMA_URL/v1}"
case "$LLM_BASE_URL" in
    *localhost:11434*|*127.0.0.1:11434*) LOCAL_LLM=1 ;;
    *) LOCAL_LLM=0 ;;
esac

ollama_up() { curl -fs -m 2 "$OLLAMA_URL/api/version" >/dev/null 2>&1; }

if [ "$SKIP_LLM" = 1 ]; then
    ok "skipped (--no-llm)"
elif [ "$LLM_PROVIDER" = "anthropic" ]; then
    if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        ok "Claude backend ($LLM_MODEL): ANTHROPIC_API_KEY is set, nothing to install"
    else
        warn "ANTHROPIC_API_KEY is not set"
        PENDING+=("Add ANTHROPIC_API_KEY to .env for LLM decisions, or use 'decisions: rules' in the run config")
    fi
elif [ "$LOCAL_LLM" = 0 ]; then
    ok "hosted endpoint configured ($LLM_BASE_URL, model $LLM_MODEL); nothing to install"
elif ! command -v ollama >/dev/null 2>&1 && [ ! -d /Applications/Ollama.app ]; then
    warn "Ollama is not installed"
    PENDING+=("Install Ollama from https://ollama.com/download and re-run this script (or set a hosted LLM in .env)")
else
    if ! ollama_up; then
        echo "  starting the Ollama server"
        if [ "$(uname -s)" = "Darwin" ] && [ -d /Applications/Ollama.app ]; then
            open -a Ollama
        else
            mkdir -p "$TOOLS_DIR"
            nohup ollama serve > "$TOOLS_DIR/ollama.log" 2>&1 &
        fi
        for _ in $(seq 1 30); do ollama_up && break; sleep 1; done
    fi
    if ! ollama_up; then
        warn "Ollama server did not start"
        PENDING+=("Start Ollama (open the app or run 'ollama serve') and re-run this script")
    elif ollama list | awk 'NR > 1 { print $1 }' | grep -qx -e "$LLM_MODEL" -e "$LLM_MODEL:latest"; then
        ok "Ollama running, model $LLM_MODEL already pulled"
    else
        echo "  pulling $LLM_MODEL (one-time download)"
        ollama pull "$LLM_MODEL"
        ok "Ollama running, model $LLM_MODEL pulled"
    fi
fi

# ---------------------------------------------------------------- 5. Check
step "Check"
uv run python -c "import rdkit, pyscf, chemprop, selfies, langgraph, langchain_openai, tblite, opi, molcurator" \
    && ok "Python packages import" \
    || PENDING+=("Python imports failed: see the error above")

# No calculations are launched here; ORCA must be installed/licensed separately.
step "Chemistry tool preflight"
uv run --no-sync python scripts/check_property_tools.py --backend all \
    || PENDING+=("Chemistry preflight failed: set ORCA_BIN in .env or load cluster modules, then re-run uv run --no-sync python scripts/check_property_tools.py")

if [ "${#PENDING[@]}" -eq 0 ]; then
    printf '\n\033[32mSetup complete.\033[0m Activate the environment with: source .venv/bin/activate\n'
else
    printf '\n\033[33mSetup finished with %d step(s) left:\033[0m\n' "${#PENDING[@]}"
    for p in "${PENDING[@]}"; do echo "  - $p"; done
    exit 1
fi
