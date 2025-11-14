#!/usr/bin/env bash
#
# ARCHIVED (Nov 2025): Replaced by explicit virtualenv activation plus
# `python -m pip install -e .[dev]`. Kept for reference only.
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[setup-python-project] Installing pulldb in editable mode..."
cd "$PROJECT_ROOT"

if [[ -f venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
elif [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "[setup-python-project][WARN] No virtual environment detected (venv/ or .venv/)."
  echo "[setup-python-project][WARN] Activate an environment before running pip install."
fi

python -m pip install --upgrade pip
python -m pip install -e .[dev]

echo "[setup-python-project] Running smoke import test..."
python - <<'PY'
import pulldb
from pulldb.cli import main as cli_main
print("pulldb version", getattr(pulldb, "__version__", "unknown"))
print("CLI main:", cli_main.__name__)
PY

echo "[setup-python-project] Done. Console scripts available: pulldb"
