#!/usr/bin/env bash
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
fi

python -m pip install --upgrade pip
python -m pip install -e .[dev]

echo "[setup-python-project] Running smoke import test..."
python - <<'PY'
import pulldb, pulldb.cli.main, pulldb.daemon.main
print("pulldb version", pulldb.__version__)
PY

echo "[setup-python-project] Done. Console scripts available: pulldb, pulldb-daemon"
