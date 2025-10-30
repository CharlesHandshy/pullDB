# Python Project Setup (pullDB)

This document explains the packaging, local installation, and development workflow for the Python implementation of pullDB.

## Packaging Approach

We use **setuptools with PEP 621** metadata in `pyproject.toml`. A minimal `setup.py` shim remains for legacy tooling but all configuration lives in `pyproject.toml`.

Rationale:
1. Existing `requirements.txt` manifests are already part of workflow
2. Simpler onboarding than Poetry while still supporting editable installs (`pip install -e .`)
3. Native PEP 621 metadata avoids duplication between setup.cfg/setup.py

## Editable Install

Use the helper script:

```bash
scripts/setup-python-project.sh
```

This will:
1. Activate `venv` or `.venv` if present
2. Upgrade `pip`
3. Install `pulldb` with dev extras (`pytest`, `mypy`, `ruff`)
4. Run a smoke import test

Console scripts exposed:
```bash
pulldb --version
pulldb-daemon
```

## Structure

```
pulldb/
  cli/            # CLI entrypoints (restore/status)
  daemon/         # Daemon entrypoint and future worker loop
  domain/         # Dataclasses (Config, Job, User, etc.)
  infra/          # Adapters (MySQL, S3, logging)
  tests/          # pytest tests
```

Refer to `design/implementation-notes.md` for planned future modules.

## Development Tasks

Run tests:
```bash
pytest -q
```

Static type checking:
```bash
mypy pulldb
```

Lint & format (Ruff):
```bash
ruff check .
```

## Next Milestones

- Implement configuration loader (`Config.from_env_and_mysql`)
- Repository layer in `infra/mysql.py`
- CLI validation logic in `cli/main.py`
- Daemon polling loop in `daemon/main.py`

## Notes

`requirements.txt` remains for quick dependency listing; authoritative runtime dependencies are also declared in `pyproject.toml` to support `pip install .` flows.
