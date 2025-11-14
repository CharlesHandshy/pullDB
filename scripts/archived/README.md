# Archived Scripts

These scripts are retained for historical reference and should not be used for new setups. Modern workflows rely on the numbered files under `schema/pulldb/` for database provisioning and direct `pip install -e .[dev]` commands for Python environment setup.

| Script | Status | Replacement |
| --- | --- | --- |
| `setup-pulldb-schema.sh` | Archived Nov 2025 | Apply `cat schema/pulldb/*.sql | mysql` |
| `setup-python-project.sh` | Archived Nov 2025 | Activate a virtual environment and run `python -m pip install -e .[dev]` |
