# Archived Scripts

These scripts are retained for historical reference and should not be used for new setups. Modern workflows rely on `schema/pulldb.sql` for database provisioning and direct `pip install -e .[dev]` commands for Python environment setup.

| Script | Status | Replacement |
| --- | --- | --- |
| `setup-pulldb-schema.sh` | Archived Nov 2025 | Apply `schema/pulldb.sql` directly via `mysql` |
| `setup-python-project.sh` | Archived Nov 2025 | Activate a virtual environment and run `python -m pip install -e .[dev]` |
