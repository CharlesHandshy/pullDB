# pullDB 1.2.0 → 1.3.0 Upgrade Package

## What's in this package

```
upgrade-1.2.0-to-1.3.0/
├── upgrade.sh                   # Main upgrade orchestration
├── rollback.sh                  # Rollback to 1.2.0 if needed
├── inject-production-settings.sh  # Run migration 014 with dry-run support
├── migrations/
│   ├── 010_overlord_tracking_subdomain.sql   # ADD COLUMN current_subdomain
│   ├── 011_fix_settings_keys.sql             # Rename 3 settings keys
│   ├── 012_add_origin_column.sql             # ADD COLUMN jobs.origin
│   ├── 013_overlord_tracking_idx_user.sql    # ADD INDEX idx_user
│   └── 014_inject_production_settings.sql    # Seed 1.3.0 settings, clean up 1.2.0 data
├── Dockerfile                   # 1.3.0 image build file
├── entrypoint.sh                # Container entrypoint (baked into image)
├── supervisord.conf             # Process supervisor config (baked into image)
├── wait-for-mysql.sh            # MySQL readiness gate (baked into image)
└── pulldb-mysql.cnf             # MySQL socket config (baked into image)
```

> **Note**: `pulldb_1.3.0_amd64.deb` is not committed to git (too large).
> Transfer it separately or use a pre-built image tar — see Step 1 below.

## Schema changes from 1.2.0 → 1.3.0

All changes are **additive and backward-compatible**. No columns removed, no existing
data modified (except 3 settings key renames which are idempotent).

| Table | Change |
|---|---|
| `jobs` | Added `origin ENUM('restore','claim','assign') DEFAULT 'restore'` |
| `overlord_tracking` | Added `current_subdomain VARCHAR(30) NULL` |
| `overlord_tracking` | Added index `idx_user (created_by)` |
| `settings` (data) | `max_retention_months` → `max_retention_days` (×30) |
| `settings` (data) | `max_retention_increment` deleted |
| `settings` (data) | `expiring_notice_days` → `expiring_warning_days` |
| `settings` (data) | 14 new 1.3.0 myloader settings seeded (INSERT IGNORE) |
| `db_hosts` (data) | Spurious `localhost` placeholder removed |

## Prerequisites on the target server

- Running pullDB 1.2.0 container (any name, auto-detected)
- Docker installed
- `sudo` access
- ~4× the MySQL data directory size in free disk space
- The 1.3.0 Docker image **or** the `.deb` file

## Step 1: Publish the release and download on the target

On the dev machine:

```bash
make release
```

This builds the image, packages everything into `pulldb-upgrade-1.3.0.tar.gz`, creates
a GitHub release, and uploads the bundle as an asset. The download URL is printed at the
end.

On the target server (no git, ECR, or build tools required):

```bash
# Upgrade bundle (includes Docker image + scripts + migrations)
wget https://github.com/CharlesHandshy/pullDB/releases/download/v1.3.0/pulldb-upgrade-1.3.0.tar.gz
tar -xzf pulldb-upgrade-1.3.0.tar.gz
cd upgrade-1.2.0-to-1.3.0/

# Client CLI (optional — install on any machine that needs the pulldb CLI)
wget https://github.com/CharlesHandshy/pullDB/releases/download/v1.3.0/pulldb-client_1.3.0_amd64.deb
sudo dpkg -i pulldb-client_1.3.0_amd64.deb
```

## Step 2: Run the upgrade

```bash
cd /tmp/upgrade-1.2.0-to-1.3.0/

# Default — auto-detects the running 1.2.0 container name, ports, and image tar
sudo ./upgrade.sh

# Dry run first (shows what would happen, makes no changes)
sudo ./upgrade.sh --dry-run

# If your 1.2.0 container has a non-default name (default is 'pulldb'):
sudo ./upgrade.sh --blue-container pulldb-prod

# Test green on temporary ports first, cut over manually later:
sudo ./upgrade.sh --skip-cutover
# ... verify green on ports 8002/8082 ...
# Then re-run without --skip-cutover to complete the cutover
sudo ./upgrade.sh
```

> The image tar (`pulldb-1.3.0.tar.gz`) is auto-detected from the same directory.
> No `--image-tar` flag needed when using a bundle produced by `make bundle`.

## Step 3: Verify

After the cutover, the new container runs under the original container name (default: `pulldb`)
on the original ports. Verify:

```bash
# Health check (use the original API port — typically 8080 or 8084)
curl -fsk https://localhost:<api-port>/api/health | python3 -m json.tool

# Check migration columns exist in the new container
docker exec pulldb mysql -u root -S /tmp/mysql.sock -N \
  -e "DESCRIBE pulldb_service.jobs;" | grep origin

docker exec pulldb mysql -u root -S /tmp/mysql.sock -N \
  -e "DESCRIBE pulldb_service.overlord_tracking;" | grep current_subdomain

# Check new 1.3.0 settings were seeded
docker exec pulldb mysql -u root -S /tmp/mysql.sock \
  pulldb_service -e "SELECT setting_key, setting_value FROM settings ORDER BY setting_key;"
```

If you want to preview or re-run migration 014 (settings injection) independently:

```bash
# Preview (dry run)
sudo ./inject-production-settings.sh --dry-run

# Apply (idempotent — safe to run multiple times)
sudo ./inject-production-settings.sh
```

## Step 4: Clean up (after 24h verification window)

```bash
# The old blue container is stopped but not removed — check rollback-state.env for its name
cat rollback-state.env

# Remove old container and its MySQL volume
docker rm <old-container-name>
docker volume rm <old-mysql-volume>

# Remove the upgrade dump (keep for 7 days in case of issues)
ls /mnt/data/upgrade-dumps/
```

## Rollback procedure

If 1.3.0 is broken and you need to go back:

```bash
sudo ./rollback.sh
```

This stops the new container and restarts the original 1.2.0 container on the
original ports. The old container was stopped but not removed during the upgrade.

> **Note**: Rollback is only clean if no production writes have hit 1.3.0's
> new `origin` column with non-default values. Since the default is 'restore'
> and 1.2.0 doesn't know about this column, any jobs submitted via 1.3.0 before
> rollback will have `origin='restore'` which is safe — 1.2.0 ignores the column.

## Upgrade flow (what upgrade.sh does internally)

```
Pre-flight
  ├── Verify blue is running and healthy
  ├── Detect blue's ports and volumes (no manual config needed)
  └── Check disk space

Step 1: Dump
  └── mysqldump --single-transaction from blue's MySQL

Step 2: Load image
  ├── If pulldb:1.3.0 exists locally → skip
  ├── If --image-tar passed → docker load
  └── Else build from .deb + Dockerfile

Step 3: Start green
  └── docker run with PULLDB_IMPORT_DUMP=/mnt/data/import.sql
      (entrypoint imports dump, applies base schema, starts supervisord)

Step 4: Wait for health
  └── Poll /api/health every 10s, timeout 5 minutes

Step 5: Run migrations
  └── Applies migrations/ in order (all guarded with IF NOT EXISTS / INSERT IGNORE)
      010 → overlord_tracking.current_subdomain
      011 → settings key renames
      012 → jobs.origin
      013 → overlord_tracking idx_user
      014 → seed 1.3.0 myloader settings, remove localhost placeholder,
             update default_dbhost

Step 6: Final checks
  ├── API health
  ├── Web UI HTTP 200/302
  └── Row count parity (auth_users, jobs, db_hosts, settings)

Step 7: Cutover  ← ~5 second downtime window
  ├── Write rollback-state.env
  ├── Rename blue to <name>-prev (if green uses same container name)
  ├── docker stop blue
  ├── docker stop green + restart on blue's original ports under original name
  └── Wait for health on production ports
```

## Time estimate

| Stage | Typical time |
|---|---|
| Pre-flight | <5s |
| MySQL dump (small DB ~100MB) | ~30s |
| Image load / build | 1–3 min |
| Green container import | 1–3 min |
| Migrations | <5s |
| Cutover downtime | ~5s |
| **Total** | **~5–10 min** |
