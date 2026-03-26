# pullDB 1.2.0 → 1.3.0 Upgrade Package

## What's in this package

```
upgrade-1.2.0-to-1.3.0/
├── upgrade.sh                   # Main upgrade orchestration
├── rollback.sh                  # Rollback to 1.2.0 if needed
├── migrations/
│   ├── 010_overlord_tracking_subdomain.sql   # ADD COLUMN current_subdomain
│   ├── 011_fix_settings_keys.sql             # Rename 3 settings keys
│   ├── 012_add_origin_column.sql             # ADD COLUMN jobs.origin
│   └── 013_overlord_tracking_idx_user.sql    # ADD INDEX idx_user
├── Dockerfile                   # 1.3.0 image build file   (copy from docker/)
├── pulldb_1.3.0_amd64.deb       # 1.3.0 package            (copy from build output)
├── entrypoint.sh                # Container entrypoint      (copy from docker/)
├── wait-for-mysql.sh            # Healthcheck helper        (copy from docker/)
└── pulldb-mysql.cnf             # MySQL socket config       (copy from docker/)
```

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

## Prerequisites on the target server

- Running pullDB 1.2.0 container (any name, auto-detected)
- Docker installed
- `sudo` access
- ~4× the MySQL data directory size in free disk space
- The 1.3.0 Docker image **or** the `.deb` file + Dockerfile

## Step 1: Transfer this package to the target server

```bash
# On this dev machine — build the .deb and Docker files into the package
make server        # builds pulldb_1.3.0_amd64.deb
cp pulldb_1.3.0_amd64.deb packaging/upgrade-1.2.0-to-1.3.0/
cp docker/Dockerfile docker/entrypoint.sh docker/wait-for-mysql.sh \
   docker/pulldb-mysql.cnf packaging/upgrade-1.2.0-to-1.3.0/

# Package it up
tar -czf pulldb-upgrade-1.2.0-to-1.3.0.tar.gz \
    -C packaging upgrade-1.2.0-to-1.3.0/

# Transfer to target
scp pulldb-upgrade-1.2.0-to-1.3.0.tar.gz user@target-server:/tmp/
```

Alternatively, save the 1.3.0 Docker image as a tar to avoid building on the target:

```bash
docker save pulldb:1.3.0 | gzip > pulldb-1.3.0-image.tar.gz
# Then transfer and pass --image-tar /tmp/pulldb-1.3.0-image.tar.gz
```

## Step 2: Run the upgrade

```bash
# On the target server
cd /tmp
tar -xzf pulldb-upgrade-1.2.0-to-1.3.0.tar.gz
cd upgrade-1.2.0-to-1.3.0/
chmod +x upgrade.sh rollback.sh

# Default — auto-detects blue container name and ports
sudo ./upgrade.sh

# If your blue container has a non-default name:
sudo ./upgrade.sh --blue-container pulldb-prod

# If using a pre-built image tar:
sudo ./upgrade.sh --image-tar /tmp/pulldb-1.3.0-image.tar.gz

# Test green first, cut over manually:
sudo ./upgrade.sh --skip-cutover
# ... verify green on ports 8002/8082 ...
sudo ./upgrade.sh --blue-container pulldb-blue --green-container pulldb-green
# (re-running without --skip-cutover will do the cutover)
```

## Step 3: Verify

After the cutover, verify the upgrade succeeded:

```bash
# Health check on original ports (default 8001/8081)
curl -fsk https://localhost:8001/api/health | python3 -m json.tool

# Check version in UI footer or API
curl -fsk https://localhost:8081/api/health | python3 -m json.tool

# Check migration columns exist
docker exec pulldb-green mysql -u root -S /tmp/mysql.sock -N \
  -e "DESCRIBE pulldb_service.jobs;" | grep origin

docker exec pulldb-green mysql -u root -S /tmp/mysql.sock -N \
  -e "DESCRIBE pulldb_service.overlord_tracking;" | grep current_subdomain
```

## Step 4: Clean up (after 24h verification window)

```bash
# Remove old blue container and its MySQL volume
docker rm pulldb-blue
docker volume rm $(docker volume ls -q | grep blue-mysql)

# Remove the upgrade dump (keep for 7 days in case of issues)
# ls /mnt/data/upgrade-dumps/
```

## Rollback procedure

If 1.3.0 is broken and you need to go back:

```bash
sudo ./rollback.sh
```

This stops the green container and restarts the original blue container on the
original ports. The blue container was stopped but not removed during the upgrade.

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
  └── Applies migrations/ in order (all guarded with IF NOT EXISTS)
      010 → overlord_tracking.current_subdomain
      011 → settings key renames
      012 → jobs.origin
      013 → overlord_tracking idx_user

Step 6: Final checks
  ├── API health
  ├── Web UI HTTP 200/302
  └── Row count parity (auth_users, jobs, db_hosts, settings)

Step 7: Cutover  ← ~5 second downtime window
  ├── Write rollback-state.env
  ├── docker stop blue
  ├── docker stop green + restart on blue's original ports
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
