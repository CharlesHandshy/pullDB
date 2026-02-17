# Settings System — Remediation Plan

> Generated 2026-02-12 from the [SETTINGS-SYSTEM.md](SETTINGS-SYSTEM.md) Section 21 audit.
> Organized into independent work packages that can be executed in any order
> unless noted. Each part is designed to be a single focused PR.

---

## Guiding Principles

1. **Don't break production.** Every change is backward-compatible. No env var
   renames, no removed settings that could be referenced in `.env` files.
2. **Fix display before behavior.** Correct what the admin sees before changing
   runtime logic.
3. **Align sources of truth.** When Registry, Config field, and Seed SQL
   disagree, the production-tested value wins.
4. **Delete dead code immediately.** Dead imports, dead methods, stale defaults
   — remove them, don't mark them.
5. **Validators are cheap insurance.** Adding them prevents future foot-guns
   with no runtime risk.

---

## Part 1 — Fix the Priority Cascade Display (B1)

**Findings solved:** B1 (HIGH), M8 (LOW)
**Risk:** LOW — display-only change, zero runtime behavior change
**Files:** 2 modified

### Problem

The runtime loads settings as **env > DB > default** (correct — env vars are
deployment configuration). But `_get_setting_source()` in the web UI and CLI
display defaults as **DB > env > default**, so the admin sees the DB value
labeled "active" even when an env var is actually overriding it at runtime.

### Why fix the display, not the runtime

Changing the runtime (env > DB → DB > env) would mean any admin DB write
instantly overrides carefully-set env vars on production workers. That's far
more dangerous. The code comment at [config.py L317](pulldb/domain/config.py#L317)
confirms env-over-DB is the **intentional design**: *"Apply MySQL overrides
(environment takes precedence if set)"*.

### Plan

1. **`pulldb/web/features/admin/routes.py`** — `_get_setting_source()`:
   Swap priority to check `os.getenv(meta.env_var)` FIRST, then `db_value`.
   If both exist and differ, return the env value with source `"environment
   (overrides database)"` so the admin sees the conflict.

2. **`pulldb/cli/settings.py`** — the parallel display logic in `_format_setting_row()`:
   Same swap: show env value as active when it exists.

3. **`pulldb/infra/bootstrap.py`** — after Phase 5 (L118), add a log warning
   when a setting exists in both env and DB with different values:
   ```
   WARNING: Setting 'myloader_threads' has env=8 but database=16.
   Environment value takes precedence at runtime.
   ```
   This addresses M8 (startup warning for priority cascade conflict).

### Verification

- Unit tests for `_get_setting_source()`: pass DB value AND env value, assert
  env wins.
- Manual: set `PULLDB_MYLOADER_THREADS=8` in `.env`, set `myloader_threads=16`
  in DB, confirm the admin UI shows "8 (environment, overrides database)".

---

## Part 2 — Align Registry Defaults with Production Reality (B2, B6)

**Findings solved:** B2 (HIGH), B6 (LOW)
**Risk:** LOW — only changes what the UI shows as "default" and what tests get
**Files:** 2 modified

### Problem

The SETTING_REGISTRY says `myloader_threads` default is `"8"`, but the Config
dataclass field is `4` with an explicit comment: *"Reduced from 8 to prevent
OOM on memory-constrained systems."* The battle-tested value (4) is correct;
the registry never caught up.

Similarly, the Config field default tuple for `myloader_default_args` has stale
values (`--rows=100000`, `--queries-per-transaction=5000`) that differ from the
`_MYLOADER_DEFAULT_ARGS_BUILTIN` tuple (`50000`, `1000`).

### Why we update the registry, not the Config field

The Config `myloader_threads=4` comment says OOM was observed. Production runs
with 4. The registry default is what the admin UI shows as "reset to default" —
it should show 4, not 8.

For paths (`work_directory`, `customers_after_sql_dir`, `qa_template_after_sql_dir`):
the Config field defaults are dev-friendly paths (`/mnt/data/tmp/...`,
package-relative). The registry defaults (`/opt/pulldb.service/...`) match the
packaging and deployment docs. Both are valid for their use case. The registry
and env.example agree — that's the production truth. The Config field defaults
only matter for bare `Config()` construction in tests.

### Plan

1. **`pulldb/domain/settings.py`** — update `myloader_threads` default from
   `"8"` → `"4"`. Add comment: `# Reduced from 8 to prevent OOM`.

2. **`pulldb/domain/config.py`** — update the `myloader_default_args` field
   default tuple to match `_MYLOADER_DEFAULT_ARGS_BUILTIN`:
   - `--rows=100000` → `--rows=50000`
   - `--queries-per-transaction=5000` → `--queries-per-transaction=1000`
   - Add `--max-threads-for-index-creation=1`
   - Add `--throttle=Threads_running=6`

   This makes the field default and the builtin fallback identical, eliminating
   the "which default am I getting?" confusion.

### Why NOT change the path defaults

Three sources disagree on path defaults:
- Config field: `/mnt/data/tmp/{user}/pulldb-work` (dev)
- Registry: `/opt/pulldb.service/work` (production)
- Seed SQL: `/var/lib/pulldb/work/` (legacy)

The Config field is intentionally dev-friendly (works without root). The
registry is intentionally production-correct. These serve different audiences
and the priority cascade resolves it: production deployments set `.env` paths
explicitly. No change needed — but we fix the seed SQL in Part 3.

### Verification

- Grep for tests asserting `myloader_threads == 8` — update any that exist.
- Run `pulldb-admin settings list` — confirm `myloader_threads` shows default=4.

---

## Part 3 — Fix Seed SQL + Write Migration for Ghost Keys (B3, D4, M7)

**Findings solved:** B3 (MEDIUM), D4 (LOW), M7 (LOW)
**Risk:** LOW — seed only runs on fresh installs; migration uses safe UPDATE/DELETE
**Files:** 2 modified, 1 created

### Problem

The seed SQL inserts 3 keys that don't match the current registry:
`max_retention_months`, `max_retention_increment`, `expiring_notice_days`.
These sit as ghost data in production databases.

### Plan

1. **`schema/pulldb_service/02_seed/004_seed_settings.sql`** — update:
   - `max_retention_months` → `max_retention_days` (value: `180` instead of `6`)
   - Remove `max_retention_increment` entirely (no registry equivalent)
   - `expiring_notice_days` → `expiring_warning_days`
   - `work_directory` value: `/opt/pulldb.service/work` (match registry)

2. **`schema/migrations/011_fix_settings_keys.sql`** — new migration:
   ```sql
   -- Rename max_retention_months → max_retention_days (convert months to days)
   UPDATE settings
   SET setting_key = 'max_retention_days',
       setting_value = CAST(CAST(setting_value AS UNSIGNED) * 30 AS CHAR),
       description = 'Maximum retention period in days'
   WHERE setting_key = 'max_retention_months'
     AND NOT EXISTS (SELECT 1 FROM (SELECT 1 FROM settings WHERE setting_key = 'max_retention_days') t);

   -- Remove max_retention_increment (no longer used)
   DELETE FROM settings WHERE setting_key = 'max_retention_increment';

   -- Rename expiring_notice_days → expiring_warning_days
   UPDATE settings
   SET setting_key = 'expiring_warning_days'
   WHERE setting_key = 'expiring_notice_days'
     AND NOT EXISTS (SELECT 1 FROM (SELECT 1 FROM settings WHERE setting_key = 'expiring_warning_days') t);
   ```

   The `NOT EXISTS` guards prevent duplicate key errors if the new keys already
   exist (admin created them via UI). If both old and new keys exist, the old
   one is left as harmless dead data.

### Why UPDATE instead of DELETE + INSERT

`ON DUPLICATE KEY UPDATE` in the seed handles fresh installs. For existing
production databases, `UPDATE ... WHERE old_key AND NOT EXISTS new_key` is the
safest — it preserves admin-customized values and only renames the key.

### Verification

- Fresh install: run seed, verify correct keys appear.
- Existing DB: run migration, verify old keys gone, new keys preserved.

---

## Part 4 — Route `default_retention_days` Through Repository (B4, D3, BT6)

**Findings solved:** B4 (MEDIUM), D3 (DEAD), BT6 (BETTER)
**Risk:** LOW-MEDIUM — changes a SQL query in a critical path (job deployment)
**Files:** 1 modified

### Problem

`mysql_jobs.py` reads `default_retention_days` via raw SQL instead of calling
`SettingsRepository.get_default_retention_days()`. The typed method exists in
both MySQL and Simulation adapters but has zero callers. The raw SQL bypasses
validation (`max(1, ...)`) and won't work in simulation mode.

### Why not add `settings_repo` to `JobRepository`

Adding a constructor dependency would require updating the Protocol in
`interfaces.py`, the factory in API startup, the simulation adapter's
constructor, and test stubs. That's a wide blast radius for a one-line fix.

### Plan

Instead of injecting `settings_repo`, create a `SettingsRepository` locally
from the existing pool (both classes use `MySQLPool`):

```python
# In mysql_jobs.py, inside the method that currently has the raw SQL:
from pulldb.infra.mysql_settings import SettingsRepository as _SettingsRepo

settings_repo = _SettingsRepo(self.pool)
retention_days = settings_repo.get_default_retention_days()
```

This:
- Uses the validated accessor method (with `max(1, ...)`)
- Works with the existing `self.pool` — no constructor change
- The `get_default_retention_days()` method is no longer dead code (D3 solved)
- Keeps the import private (underscore alias)

Delete the raw SQL block entirely.

### Verification

- Existing tests for `mark_deployed()` should still pass.
- Set `default_retention_days=0` in DB → verify the accessor returns 1 (the
  `max(1, ...)` validation), not 0. The raw SQL had no such guard.

---

## Part 5 — Add Protocol Methods + Remove `hasattr` Guards (BT1)

**Findings solved:** BT1 (MEDIUM)
**Risk:** LOW — structural typing, no behavioral change
**Files:** 1 modified (interfaces.py), optionally clean up hasattr guards later

### Problem

5 methods exist in both MySQL and Simulation implementations but are missing
from the `SettingsRepository` Protocol. Web routes use `hasattr()` guards
instead of trusting the Protocol.

### Why it's safe

Python Protocols are structural — adding methods doesn't break existing
implementations that already have them. The MySQL and Simulation adapters
already implement all 5. Two test stubs (`FakeSettingsRepository` in
`test_api_jobs.py` and `test_smoke.py`) don't implement them, but they're
already non-compliant with the *current* Protocol (they only implement 2-3
methods). Adding 5 more doesn't change their type-safety status.

### Plan

1. **`pulldb/domain/interfaces.py`** — add the 5 methods to the
   `SettingsRepository` Protocol class:
   ```python
   def get_all_settings_with_metadata(self) -> list[dict[str, str | None]]: ...
   def get_default_retention_days(self) -> int: ...
   def get_max_retention_days(self) -> int: ...
   def get_job_log_retention_days(self) -> int: ...
   def get_jobs_refresh_interval(self) -> int: ...
   ```

2. **Do NOT remove the `hasattr()` guards yet.** They're redundant now but
   harmless, and removing 33 guards across 4 files is a large diff that should
   be its own PR after this lands and is verified.

### Verification

- `mypy` or `pyright` should not flag new errors.
- Grep for `hasattr.*settings_repo` — confirm guards are redundant (methods
  now in Protocol).

---

## Part 6 — Add Enum Validators for Myloader String Settings (BT2, M3)

**Findings solved:** BT2 (MEDIUM), M3 (LOW)
**Risk:** LOW — validation only runs on admin SAVE, never on read
**Files:** 2 modified

### Problem

Three myloader settings accept fixed enum values but have no validator:
`myloader_optimize_keys`, `myloader_checksum`, `myloader_drop_table_mode`.
Also `myloader_ignore_errors` accepts a comma-separated list with no format
check.

### Why parameterized validator names

The current validator dispatch uses string names (`"is_positive_integer"`,
`"file_exists"`, etc.) with `(value, key)` signatures. There's no mechanism
to pass allowed values. The simplest extension: use a `"is_one_of:val1,val2"`
convention where the colon-separated suffix carries the allowed values.

### Plan

1. **`pulldb/domain/validation.py`** — add a new branch in
   `validate_setting_value()`:
   ```python
   elif validator.startswith("is_one_of:"):
       allowed = validator.split(":", 1)[1].split(",")
       if value not in allowed:
           return ValidationResult(
               valid=False,
               error=f"'{key}' must be one of [{', '.join(allowed)}], got '{value}'",
           )
   ```
   Also add an `is_csv_integers` validator for `myloader_ignore_errors`:
   ```python
   elif validator == "is_csv_integers":
       for part in value.split(","):
           part = part.strip()
           if part and not part.isdigit():
               return ValidationResult(
                   valid=False,
                   error=f"'{key}' must be comma-separated integers, got '{part}'",
               )
   ```

2. **`pulldb/domain/settings.py`** — add validators to the 4 settings:
   ```python
   "myloader_optimize_keys": SettingMeta(
       ...
       validators=["is_one_of:AFTER_IMPORT_PER_TABLE,AFTER_IMPORT_ALL_TABLES,SKIP"],
   ),
   "myloader_checksum": SettingMeta(
       ...
       validators=["is_one_of:skip,fail,warn"],
   ),
   "myloader_drop_table_mode": SettingMeta(
       ...
       validators=["is_one_of:FAIL,NONE,DROP,TRUNCATE,DELETE"],
   ),
   "myloader_ignore_errors": SettingMeta(
       ...
       validators=["is_csv_integers"],
   ),
   ```

### Why not a SettingType.ENUM

Adding a new `SettingType` would require changes to every template, every
serializer, and the CLI display logic. Validators are orthogonal to types and
plug into the existing pipeline with zero template changes.

### Verification

- Test: `validate_setting_value("myloader_checksum", "invalid")` → fails.
- Test: `validate_setting_value("myloader_checksum", "warn")` → passes.
- Test: `validate_setting_value("myloader_ignore_errors", "1146,abc")` → fails.
- Test: `validate_setting_value("myloader_ignore_errors", "1146,1050")` → passes.

---

## Part 7 — Delete Dead Code (D1, D2, D5, D6)

**Findings solved:** D1 (LOW), D2 (MEDIUM), D5 (LOW), D6 (LOW — already done in Part 2)
**Risk:** LOW — removing unused code
**Files:** 4 modified

### Plan

1. **D5 — Unused CLI imports** — `pulldb/cli/settings.py`:
   Delete `import re` (line 22) and `from pathlib import Path` (line 23).
   Zero callers confirmed.

2. **D1 — `myloader_connection_timeout`** — `pulldb/domain/settings.py`:
   Add `deprecated=True` field to SettingMeta dataclass (with `default=False`).
   Mark the setting as `deprecated=True`. Update
   `build_myloader_args_from_settings()` to skip deprecated settings.
   **Don't remove the registry entry** — existing `.env` files and DB rows
   reference it. Removal would cause sync/diff to warn about "unknown setting".

   Actually, simpler approach: the setting already says `[DEPRECATED]` in its
   description and is already skipped in `build_myloader_args_from_settings()`.
   The only improvement is to **hide it from the admin UI**. Add a
   `hidden=True` field to SettingMeta, set it on this setting, and filter
   hidden settings from the web template. But that's scope creep for this PR.

   **Recommended: Leave D1 as-is.** It's already effectively dead. The
   description warns admins. The UI rendering is a cosmetic concern, not a
   correctness concern. Document it in SETTINGS-SYSTEM.md as "known deprecated,
   retained for backward compatibility."

3. **D2 — `job_log_retention_days`** — **Leave setting, remove dead method.**
   The setting is valid and should remain (the feature may be implemented
   later). But `get_job_log_retention_days()` in mysql_settings.py and
   mock_mysql.py has zero callers AND its Protocol entry (added in Part 5)
   would imply it's used.

   **Decision: Keep it.** It's 12 lines of code, it's tested via the Protocol,
   and when the pruning feature is implemented it'll be needed. Mark D2 as
   "intentional — placeholder for future job log pruning feature."

4. **D6** — Already resolved in Part 2 (aligning the field default tuple).

### Net action

Only D5 requires actual code deletion (2 lines). D1 and D2 are documented
as intentional. D6 is handled by Part 2.

---

## Part 8 — Register `s3_backup_locations` in SETTING_REGISTRY (M1)

**Findings solved:** M1 (MEDIUM)
**Risk:** LOW — adding metadata, not changing behavior
**Files:** 1 modified

### Problem

`Config.from_env_and_mysql()` reads `s3_backup_locations` from DB but it has
no `SettingMeta` registration — invisible in the admin UI, no validators, no
env var sync, no description.

### Why this is tricky

`s3_backup_locations` is a **JSON array of objects**, not a simple key=value.
The current settings UI has no JSON editor widget. Adding a SettingMeta with
`SettingType.STRING` would let admins paste JSON into a text input, which is
error-prone but better than invisible.

### Plan

1. **`pulldb/domain/settings.py`** — add:
   ```python
   "s3_backup_locations": SettingMeta(
       key="s3_backup_locations",
       env_var="PULLDB_S3_BACKUP_LOCATIONS",
       default="",
       description="S3 backup location configurations (JSON array). "
                   "Managed via environment variable or direct DB edit. "
                   "See docs/AWS-SETUP.md for format.",
       setting_type=SettingType.STRING,
       category=SettingCategory.S3_BACKUP,
       db_only=True,  # Complex JSON — don't sync to .env as a flat string
   ),
   ```

   Mark it `db_only=True` because JSON arrays don't belong in `.env` files
   (shell escaping issues). The env var `PULLDB_S3_BACKUP_LOCATIONS` is already
   handled separately in Config loading.

2. **Do NOT add a JSON validator yet** — that's a separate enhancement. The
   setting was already being written to DB without validation before this
   change. Making it visible is the priority.

### Verification

- `pulldb-admin settings list` should now show `s3_backup_locations`.
- Admin UI should show it under S3 Backup category (read-only text display).
- `pull`/`push`/`diff` skip it (db_only).

---

## Summary: Execution Order & Dependencies

```
Part 7 (dead imports)     ─── No dependencies, trivial ───────> Merge first
Part 2 (registry defaults) ── No dependencies ────────────────> Merge early
Part 3 (seed SQL + migration) ── No dependencies ────────────> Merge early
Part 6 (enum validators) ──── No dependencies ────────────────> Merge early
Part 8 (register s3_backup) ── No dependencies ───────────────> Merge early
Part 5 (protocol methods) ──── No dependencies ───────────────> Merge anytime
Part 1 (cascade display) ──── No dependencies ────────────────> Merge anytime
Part 4 (retention via repo) ── No dependencies ───────────────> Merge anytime
```

All 8 parts are independent. No part depends on another. They can be merged
in any order or parallelized across branches.

### What We're NOT Doing (and Why)

| Finding | Decision | Reasoning |
|---------|----------|-----------|
| B5 — Env var naming | **Skip** | `PULLDB_WORK_DIR` is in 7+ deployment files, postinst scripts, and production `.env` files. Renaming it breaks every deployment. Document as accepted exception. |
| BT3 — Boolean in generic template | **Defer** | All booleans currently use specialized partials. Only surfaces if a boolean is added to Cleanup/Paths categories. Add when that happens. |
| BT4 — Theme JSON validator | **Defer** | Theme schemas use a specialized partial with client-side handling. Server-side JSON validation is nice-to-have. |
| BT5 — CLI os.environ update | **Skip** | The CLI is a separate process from the web server. Updating its own `os.environ` is meaningless — the running services need a restart regardless. The CLI already warns about this. Not a bug. |
| M2 — Job log pruning feature | **Defer** | This is a new feature, not a bug fix. Requires design decisions (what to prune, retention policy, where to run). Out of scope for a remediation plan. |
| M4 — Hostname validator | **Defer** | Nice-to-have. False positives are risky (uncommon but valid hostname formats). |
| M5 — S3 path validator | **Defer** | `parse_s3_bucket_path()` already validates at load time. Adding UI validation duplicates logic. |
| M6 — Credential ref validator | **Defer** | Format may evolve. Premature validation. |
| D1 — Deprecated connection_timeout | **Accept** | Already documented as deprecated. Description warns admins. Code already skips it. No value in removal — existing DB rows and `.env` files reference it. |
| D2 — job_log_retention_days | **Accept** | Setting is valid — feature just isn't implemented yet. Keep as placeholder. |

### Effort Estimate

| Part | Lines Changed | Risk | Time |
|------|--------------|------|------|
| 1 — Cascade display | ~40 | LOW | 1 hour |
| 2 — Registry defaults | ~15 | LOW | 30 min |
| 3 — Seed SQL + migration | ~30 | LOW | 30 min |
| 4 — Retention via repo | ~15 | LOW-MED | 30 min |
| 5 — Protocol methods | ~10 | LOW | 15 min |
| 6 — Enum validators | ~40 | LOW | 1 hour |
| 7 — Dead imports | ~2 | NONE | 5 min |
| 8 — Register s3_backup | ~12 | LOW | 15 min |
| **Total** | **~164** | | **~4 hours** |
