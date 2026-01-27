# Release Notes v1.0.7

**Release Date**: January 24, 2026  
**Type**: Documentation & Maintenance Release

## Summary

This release removes the deprecated `is_admin` database column, making `role` the single source of truth for user permissions. The `is_admin` property on the User model remains as a computed property (`role == 'admin'`).

## 🔧 Schema Changes

### `is_admin` Column Removed

The `is_admin` column has been removed from the `auth_users` table. The `role` column is now the single source of truth for permissions.

**Files updated:**
- `pulldb/infra/mysql.py` - All SQL queries updated
- `schema/pulldb_service/00_tables/001_auth_users.sql` - Schema definition
- `schema/pulldb_service/02_seed/002_seed_admin_account.sql` - Admin seed
- `schema/pulldb_service/02_seed/003_seed_service_account.sql` - Service seed

## 📚 Documentation Improvements

### Schema Documentation
- **`schema_migrations` Table**: Added complete documentation for the schema migrations tracking table in [docs/mysql-schema.md](docs/mysql-schema.md)
  - Purpose: Tracks applied SQL migration files
  - Columns: `id`, `migration_name`, `applied_at`, `checksum`
  - Business rules and table relationships documented

### Knowledge Pool Updates
- Updated version references to v1.0.7
- Updated wheel package reference to `pulldb-1.0.7-py3-none-any.whl`
- Package size: ~16MB

### API Documentation
- Version headers updated across all API documentation:
  - [docs/api/REST-API.md](docs/api/REST-API.md)
  - [docs/api/WEB-API.md](docs/api/WEB-API.md)
  - [docs/api/README.md](docs/api/README.md)

### Help Center
- Updated version badge to v1.0.7
- Updated footer version reference

## 🔧 Maintenance

### Version Synchronization
All version references synchronized to v1.0.7:
- `pyproject.toml`
- `pulldb/__init__.py`
- Documentation files
- Help Center templates

### Audit Agent Package
- Documentation audit tools available via `python -m pulldb.audit`
- Drift detection capabilities for documentation-code synchronization
- Copilot context generation for AI-assisted development

### Schema & Documentation Updates
- Updated `auth_users` table documentation to remove `is_admin` column
- Updated API response examples to show `role` field
- Updated permission documentation to reference `role` instead of `is_admin`

## 📦 Package Information

| Component | Value |
|-----------|-------|
| Version | 1.0.7 |
| Package | `pulldb-1.0.7-py3-none-any.whl` |
| Size | ~16MB |
| Python | ≥3.8 |

## 🔄 Upgrade Path

Standard upgrade from v1.0.6:
```bash
pip install --upgrade pulldb
```

Or via debian package:
```bash
sudo apt update && sudo apt upgrade pulldb
```

## 📋 Files Changed

- `pyproject.toml` - Version bump
- `pulldb/__init__.py` - Version constant
- `docs/KNOWLEDGE-POOL.md` - Version references, wheel path
- `docs/KNOWLEDGE-POOL.json` - Machine-readable version data
- `docs/START-HERE.md` - Version header
- `docs/api/REST-API.md` - Version header
- `docs/api/WEB-API.md` - Version header
- `docs/api/README.md` - Version header
- `docs/mysql-schema.md` - Added `schema_migrations` table docs
- `pulldb/web/help/index.html` - Version badge and footer
