# Archived Scripts

These scripts are retained for historical reference and should not be used for new setups.

| Script | Archived | Replacement |
| --- | --- | --- |
| `setup-pulldb-schema.sh` | Nov 2025 | Apply `cat schema/pulldb_service/*.sql \| mysql` |
| `setup-python-project.sh` | Nov 2025 | Run `python -m pip install -e .[dev]` |
| `setup-tests-dbdata.sh` | Nov 2025 | Use `tests/conftest.py` auto-provisioning |
| `validate-config.sh` | Nov 2025 | Use `scripts/validate/` pipeline |
| `run-quick-test.sh` | Nov 2025 | Use `scripts/pulldb-validate.sh --quick` |
| `run-e2e-restore.sh` | Nov 2025 | Use `scripts/pulldb-validate.sh --e2e` |

## Subdirectories

- `debug/` - One-off debugging scripts from development
- `manual-tests/` - Manual integration test scripts
