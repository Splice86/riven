#!/bin/bash
# ─── Riven Core Install Script ────────────────────────────────────────────────
# Sets up the Python venv and secrets file. No DB needed.
#
# Usage:
#   ./install.sh          — interactive (prompts for LLM URL + API key)
#   ./install.sh -- unattended (uses sensible defaults)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { echo -e "${GREEN}[+]${RESET} $1"; }
warn()  { echo -e "${YELLOW}[!]${RESET} $1"; }
error() { echo -e "${RED}[X]${RESET} $1"; }
step()  { echo -e "${BOLD}[*] $1${RESET}"; }

# ─── Python check ─────────────────────────────────────────────────────────────
step "Checking Python version..."
PYTHON_CMD=""
for cmd in python3 python python; do
    if $cmd --version 2>/dev/null | grep -q "3\.\(10\|11\|12\|13\)"; then
        PYTHON_CMD="$cmd"
        break
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    error "Python 3.10+ is required. Found:"
    python3 --version 2>/dev/null || python --version 2>/dev/null || echo "  (no python found)"
    exit 1
fi

echo "  Using $($PYTHON_CMD --version)"
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)

# ─── venv ─────────────────────────────────────────────────────────────────────
step "Creating virtual environment..."
if [[ ! -d "venv" ]]; then
    $PYTHON_CMD -m venv venv
    info "venv/ created"
else
    info "venv/ already exists — skipping"
fi

# ─── Requirements ─────────────────────────────────────────────────────────────
step "Installing Python dependencies..."
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q
info "Dependencies installed"

# ─── Secrets ──────────────────────────────────────────────────────────────────
step "Setting up secrets..."

if [[ -f "secrets.yaml" ]]; then
    info "secrets.yaml already exists — skipping"
else
    if [[ "${1:-}" == "--unattended" ]]; then
        warn "Running unattended — copying secrets_template.yaml as-is"
        warn "You MUST edit secrets.yaml before running!"
        cp secrets_template.yaml secrets.yaml
    else
        echo ""
        echo "  secrets.yaml needs your LLM credentials."
        echo "  Press ENTER to open it in your editor, or Ctrl+C to abort."
        read -r _

        cp secrets_template.yaml secrets.yaml
        ${EDITOR:-vi} secrets.yaml

        echo ""
        info "secrets.yaml saved"
    fi
fi

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}──────────────────────────────────────${RESET}"
echo -e "  ${GREEN}Riven Core installed!${RESET}"
echo -e "${BOLD}──────────────────────────────────────${RESET}"
echo ""
echo "  Run the server:"
echo -e "    ${BOLD}./venv/bin/python api.py${RESET}"
echo ""
echo "  Or with LiveReload (auto-restarts on code changes):"
echo -e "    ${BOLD}./venv/bin/python -m uvicorn api:app --reload --host 0.0.0.0 --port 8080${RESET}"
echo ""
echo "  Or as a module:"
echo -e "    ${BOLD}./venv/bin/python -m riven_core${RESET}"
echo ""
