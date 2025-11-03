CHANGELOG
=========

Unreleased
---------

v0.0.1 - 2025-11-03
-------------------
- Initial release baseline
  - mypy fixes for `pulldb/infra/s3.py`
  - Exposed `MyLoaderSpec.binary_path` + `build_myloader_command` helper
  - Installer help/docs: clarified `--aws-profile` & `--secret` flags
  - Added `docs/aws-quickstart.md`; expanded Debian README AWS flag guidance
  - Added `scripts/setup_test_env.sh` for reproducible test env provisioning
  - Added tests: installer help reference + test env dry-run script
  - Debian packaging: version bump to 0.0.1 / release branch created

