# Upgrade Runbook

[← Deployment](deployment.md) · [← Widgets](README.md)

> **Version**: 1.3.0 | **Last Updated**: 2026-03-25

pullDB uses a **blue/green** upgrade strategy. The active container is never modified in place — a new container runs alongside it, gets validated, and is then promoted to the real ports. The previous container stays stopped and available for instant rollback.

---

## Overview

```
Blue (1.2.0, active)          Green (1.3.0, candidate)
──────────────────────         ──────────────────────────
  ports 8000/8080               ports 18000/18080
  /mnt/data/mysql-blue          /tmp/pulldb-upgrade/mysql-data
                                (data snapshot from blue)
```

After validation, the green container is relaunched on ports 8000/8080 with data moved to `/mnt/data/mysql-green`. Blue is stopped but not removed.

**Zero-data-loss guarantee:** data is `docker cp`'d from the stopped active container before the candidate starts. No in-place mutation. The active container can be restarted immediately if anything fails.

---

## Prerequisites

- Docker with Compose plugin
- `sudo` access on the host
- State directory initialised (done by the installer — see [State Directory](#state-directory))

```bash
# Verify prerequisites
docker compose version
cat /etc/pulldb/.active-color     # should print: blue  (or green)
sudo docker ps --filter name=pulldb
```

---

## Standard Upgrade (Production)

```bash
# All defaults — state dir /etc/pulldb, ports 8000/8080
sudo ./scripts/upgrade.sh pulldb:1.3.0
```

This runs six phases interactively. You will be prompted once before any destructive action.

### Non-interactive (CI / automated)

```bash
sudo ./scripts/upgrade.sh --yes pulldb:1.3.0
```

### Hotfix — skip drain

```bash
sudo ./scripts/upgrade.sh --skip-drain --yes pulldb:1.3.1
```

---

## All Options

```
Usage: sudo ./scripts/upgrade.sh [options] <new-image>

Options:
  --state-dir DIR            State directory (default: /etc/pulldb)
  --compose-file FILE        Docker Compose file
                             (default: <state-dir>/docker-compose.yml)
  --prefix NAME              Container name prefix; containers are
                             <prefix>-blue / <prefix>-green  (default: pulldb)
  --mysql-data-base DIR      Base path for permanent MySQL data
                             (default: /mnt/data/mysql)
  --port-web N               Active web port (default: 8000)
  --port-api N               Active API port (default: 8080)
  --port-web-candidate N     Validation web port (default: 18000)
  --port-api-candidate N     Validation API port (default: 18080)
  --skip-ecr                 Skip ECR login (auto-set for non-ECR images)
  --skip-drain               Skip maintenance window / job drain
  --skip-qa                  Skip Tier 3 QA restore; run Tiers 1+2 only
  --yes                      Non-interactive
  --dry-run                  Print plan only; make no changes
```

---

## The Six Phases

### Phase 1 — Cleanup

Removes a stopped candidate container left from a previous upgrade attempt. Safe to run on a clean system (no-op).

### Phase 2 — Drain

Enables **maintenance mode** on the active container (worker stops accepting new jobs). Waits for in-flight jobs to finish, with a hard deadline of 7 AM.

Skipped with `--skip-drain`. The drain window is 6 PM–7 AM; outside that window you are prompted to confirm.

### Phase 3 — Snapshot

**System goes offline here.** The active container is stopped via `docker compose stop`, then `docker cp /var/lib/mysql` copies the data to `/tmp/pulldb-upgrade/mysql-data`. Ownership is set to the `mysql` UID/GID detected from the new image. Stale `.pid` files are removed.

The active container remains in `exited` state and can be restarted immediately for rollback.

### Phase 4 — Candidate Spin-up

The new image is pulled (skipped if it already exists locally). A candidate compose env file (`.env.green`) is written to the state directory and the candidate container is started on the validation ports with the copied data.

`PULLDB_CONFIG_DIR` and `HOST_IP` are carried from the active env so the candidate mounts the same config volume.

Boot scenario: `VOLUME COPY` — entrypoint detects the `.pulldb-credentials` file in the data copy, skips re-initialisation, and applies any schema migrations.

### Phase 5 — Validate

`scripts/validate.sh` runs three tiers:

| Tier | Check | Pass condition |
|------|-------|----------------|
| 1 | API health (`/api/health`) | `{"status":"ok"}` within 120 s |
| 2 | Schema integrity | All 17 expected tables + `admin` user present |
| 3 | QA restore (optional) | `myloader` restore of most recent S3 backup into a throwaway DB |

Tier 3 runs only when `PULLDB_VALIDATE_S3_PATH` is set in the candidate env file. It is skipped (with a warning) if unset. See [Enabling QA Restore](#enabling-qa-restore).

If any tier fails, the upgrade is aborted: the active container is restarted, maintenance mode is disabled, and the candidate is stopped (not removed, so logs can be inspected).

### Phase 6 — Promote

The candidate is stopped from the validation ports. The temp data directory is moved to the permanent host path (`/mnt/data/mysql-<candidate-color>`). The candidate env file is updated with the real ports. The candidate is relaunched on the real ports. `.active-color` and `.env.active` are updated. Maintenance mode is disabled.

---

## Enabling QA Restore

Add to the active env file (`.env.active` / `.env.blue`) before upgrading:

```bash
# S3 path containing backups to use for QA validation restore
PULLDB_VALIDATE_S3_PATH=s3://my-bucket/daily/prod/

# Optional: AWS profile for the S3 access (leave blank for instance role)
PULLDB_VALIDATE_AWS_PROFILE=pr-prod
```

This setting is carried forward to the candidate env file automatically by Phase 4.

---

## Rollback

The previous container is kept stopped after every successful upgrade. To roll back:

```bash
sudo ./scripts/rollback.sh
```

This prompts for confirmation, then:
1. Starts the previous container temporarily to disable maintenance mode via direct MySQL
2. Stops the current active container
3. Relaunches the previous container on the real ports
4. Updates `.active-color` and `.env.active`

The failed container is left stopped (not removed) for investigation.

> **Rollback window:** the previous container is available until it is explicitly removed with `docker rm pulldb-<color>`. Once removed, rollback is not possible without restoring the MySQL data from backup.

To clean up after confirming stability:

```bash
docker rm pulldb-blue        # remove previous after green is confirmed stable
```

---

## State Directory

The state directory (default: `/etc/pulldb`) holds all upgrade state. Do not delete these files.

```
/etc/pulldb/
├── .active-color          # "blue" or "green" — current active
├── .env.active            # copy of the active container's compose env
├── .env.blue              # compose env for the blue container
├── .env.green             # compose env for the green container (exists after first upgrade)
├── docker-compose.yml     # Docker Compose service definition
└── service.env            # pullDB runtime config (mounted read-only into container)
```

### Compose env file format

```bash
PULLDB_IMAGE=pulldb:1.3.0
CONTAINER_NAME=pulldb-blue
PORT_WEB=8000
PORT_API=8080
HOST_IP=10.40.10.117
PULLDB_CONFIG_DIR=/etc/pulldb
PULLDB_IMPORT_DUMP=
PULLDB_MYSQL_DATA_DIR=/mnt/data/mysql-blue
```

---

## Upgrade-Test Environment

For testing upgrades before running them on production, a parallel environment runs on alternate ports. It has all AWS credentials removed and S3 access disabled.

```bash
sudo ./scripts/upgrade.sh \
  --state-dir /etc/pulldb-upgrade-test \
  --compose-file /home/user/Projects/pullDB/compose/docker-compose.yml \
  --prefix pulldb-upgrade-test \
  --port-web 8002 --port-api 8082 \
  --skip-ecr --skip-drain \
  --yes \
  pulldb:1.3.0
```

The upgrade-test environment uses:

| Setting | Value |
|---------|-------|
| State dir | `/etc/pulldb-upgrade-test/` |
| Container prefix | `pulldb-upgrade-test` |
| Active container | `pulldb-upgrade-test-blue` |
| Web port | 8002 |
| API port | 8082 |
| MySQL data | `/mnt/data/mysql-green` (after first upgrade) |

---

## Dry Run

Print the full upgrade plan without making any changes:

```bash
sudo ./scripts/upgrade.sh --dry-run pulldb:1.3.0
```

Use this to verify that all state files are in place and the plan is correct before a production upgrade.

---

## Troubleshooting

### Candidate MySQL fails to start

The most common causes:

**Permission denied on `/var/lib/mysql`**
The data snapshot was owned by the wrong UID. This is handled automatically by Phase 3 (detects mysql UID from the new image). If you see this on an older version of upgrade.sh, check:
```bash
sudo docker exec pulldb-green bash -c "id mysql"
sudo stat /tmp/pulldb-upgrade/mysql-data
```
The UIDs must match.

**Stale `.pid` file crash**
Phase 3 removes `*.pid` files from the data snapshot. If running an older upgrade.sh:
```bash
sudo rm -f /tmp/pulldb-upgrade/mysql-data/*.pid
```

**View MySQL startup errors:**
```bash
sudo docker start pulldb-green   # restart after rollback
sudo docker exec pulldb-green bash -c "mysqld --user=mysql 2>&1 | head -20"
```

### Validation fails — tables missing

The candidate MySQL started but the schema was not applied. Check:
```bash
sudo docker logs pulldb-green | grep -E '\[entrypoint\]|ERROR'
```

Look for the boot scenario line:
- `VOLUME COPY` — correct for upgrades
- `RESTART` — data found but entrypoint skipped schema application (possible if credentials file present)
- `FRESH INSTALL` — data snapshot was not mounted (check `PULLDB_MYSQL_DATA_DIR` in `.env.green`)

### Candidate started on wrong ports

Check that `PORT_WEB` and `PORT_API` in `.env.green` match the `--port-web-candidate` / `--port-api-candidate` values used.

### "Could not disable maintenance mode" after promote

This is a warning, not a failure. The upgrade completed. Run manually:
```bash
sudo docker exec pulldb-green pulldb-admin maintenance disable
```

If the admin session is not initialised (air-gapped / credential-purged environment), connect directly:
```bash
sudo docker exec pulldb-green mysql pulldb_service \
  -e "UPDATE settings SET setting_value='false' WHERE setting_key='maintenance_mode'"
```

### Active container missing after failed upgrade

If upgrade.sh aborted after Phase 3 (snapshot) but the active container was not restarted:
```bash
sudo docker start pulldb-blue
# verify health
curl -fsk https://localhost:8080/api/health
```

---

## Data Location Reference

| Stage | MySQL data path |
|-------|----------------|
| Active blue container | `/mnt/data/mysql-blue` (bind mount) |
| Active green container | `/mnt/data/mysql-green` (bind mount) |
| During upgrade (temp) | `/tmp/pulldb-upgrade/mysql-data` |
| After upgrade (permanent) | `/mnt/data/mysql-<candidate-color>` |

The temp path under `/tmp` is wiped at the start of each upgrade run. The permanent paths under `/mnt/data` persist across container restarts and reboots.

---

[← Deployment](deployment.md) · [Troubleshooting →](troubleshooting.md)
