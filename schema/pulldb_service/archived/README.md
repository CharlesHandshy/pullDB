# Archived Schema Files

**DO NOT USE** - These files have been consolidated into the main schema files.

Kept for historical reference only.

## Archived Files

| File | Archived | Consolidated Into |
|------|----------|-------------------|
| `022_job_events_offset_index.sql` | 2026-01-31 | `00_tables/021_job_events.sql` |

## Why Archive?

Per pullDB schema guidelines:
- All CREATE TABLE statements should be complete with all columns and indexes
- No separate ALTER or CREATE INDEX files for production tables
- Clean install scripts should be self-contained
