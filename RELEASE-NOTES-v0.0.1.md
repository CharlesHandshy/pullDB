pulldb v0.0.1
==============

Initial release baseline for the pullDB database restoration tool.

## Highlights

- **Test Coverage**: 183 tests passing (1 skipped, 1 xpassed)
- **Type Safety**: mypy clean across 27 source files
- **Packaging**: Debian package available (`pulldb_0.0.1_amd64.deb`)
- **Documentation**: Comprehensive AWS setup guides and installer help

## Changes

### Core Improvements
- mypy fixes for `pulldb/infra/s3.py` - proper type annotations for boto3 responses
- Exposed `MyLoaderSpec.binary_path` + `build_myloader_command` helper for flexible myloader invocation

### Documentation & Tooling
- Installer help/docs: clarified `--aws-profile` & `--secret` flags with examples
- Added `docs/aws-quickstart.md` - AWS CLI validation commands and IAM policy snippets
- Expanded Debian README with detailed AWS flag guidance and troubleshooting tips
- Added `scripts/setup_test_env.sh` for reproducible test environment provisioning

### Testing
- Added tests: installer help reference validation
- Added tests: test env setup script dry-run verification

### Packaging
- Debian package version bump to 0.0.1
- Release branch `release/v0.0.1` created
- Build script auto-extracts version from control file

## Installation

### Debian Package (Ubuntu/Debian)

```bash
# Download the .deb package from this release
sudo dpkg -i pulldb_0.0.1_amd64.deb

# Configure (interactive or with flags)
sudo /opt/pulldb/scripts/install_pulldb.sh --yes --validate \
  --aws-profile dev --secret /pulldb/mysql/coordination-db
```

### From Source

```bash
git clone https://github.com/PestRoutes/infra.devops.git
cd infra.devops/Tools/pullDB
git checkout v0.0.1

# Set up test environment
bash scripts/setup_test_env.sh
source .venv-test/bin/activate

# Run tests
pytest -q --disable-warnings
mypy pulldb
```

## Documentation

- [AWS Quickstart Guide](docs/aws-quickstart.md) - IAM setup and credential validation
- [Debian Package README](packaging/debian/README.debian) - Installation and configuration
- [Testing Guide](docs/testing.md) - Running the test suite

## Requirements

- Python 3.12+
- MySQL 8.0+
- AWS credentials with Secrets Manager access
- S3 access to backup buckets

## Release Freeze

**Note**: This project is under a release freeze as of November 3, 2025. Only bug fixes and security patches will be accepted until Phase 1 features are planned. See `RELEASE-FREEZE.md` for details.

## Checksums

```
# SHA256 checksums
sha256sum pulldb_0.0.1_amd64.deb
```

Run the above command on the downloaded .deb file to verify integrity.
