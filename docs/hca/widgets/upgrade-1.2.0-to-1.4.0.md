# Upgrade Procedure: 1.2.0 → 1.3.0 → 1.4.0

[← Upgrade Runbook](upgrade.md) · [← Widgets](README.md)

> **Written**: 2026-03-25 | **Based on**: Live upgrade test + 1.2.0 production after-action report

This procedure covers the full two-hop upgrade path on dev-util-dev and production. It was developed by running the complete upgrade test on the upgrade-test environment (ports 8002/8082) and fixing three bugs in `upgrade.sh` before writing this guide.

---

## What Changes

### 1.2.0 → 1.3.0

**Code changes only — no schema changes.**

| Component | Change |
|-----------|--------|
| `pulldb-worker` | Maintenance mode: worker stops accepting jobs on signal; restores on disable |
| `upgrade.sh` | New script: full 6-phase blue/green orchestrator (replaces manual procedure) |
| `validate.sh` | New script: 3-tier post-upgrade validation |
| `rollback.sh` | New script: instant rollback to previous container |
| `entrypoint.sh` | Volume-copy boot scenario: detects copied MySQL data, applies migrations, skips fresh init |
| `docker-compose.yml` | Compose-managed deployment replaces ad-hoc docker run invocations |

Both the 1.2.0 and 1.3.0 Docker images contain **identical schema files**. The entrypoint's `apply_schema()` is idempotent — it runs `IF NOT EXISTS` DDL and silently skips tables that already exist. No data is altered.

### 1.3.0 → 1.4.0

**Code changes only — no schema changes.**

| Component | Change | Why |
|-----------|--------|-----|
| `pulldb/infra/factory.py` | `_get_real_mysql_pool()` now passes `unix_socket` when `PULLDB_MYSQL_SOCKET` is set | BUG-1 from 1.2.0 after-action: API pool was using TCP while worker used socket; credentials could drift between them |
| `pulldb/worker/service.py` | `_validate_history_connectivity()` runs at startup; worker exits with code 1 if history pool is unreachable | BUG-2: history write failures were silent for ~8 min; now fail-fast |
| `scripts/upgrade.sh` | Three bug fixes found during upgrade test (see below) | Required for reliable blue/green upgrades |

**upgrade.sh fixes in 1.4.0:**
1. Skip `docker pull` when image already exists locally (locally-built images fail pull)
2. Detect mysql UID from the new image dynamically instead of hardcoding 999 — was the root cause of MySQL crashing in candidate containers
3. Fix Phase 6 summary showing wrong rollback container name

---

## Data Preserved vs Planned Loss

### Fully Preserved

All of the following survive both upgrades intact:

| Table | Contents | Notes |
|-------|----------|-------|
| `auth_users` | User accounts, roles, manager hierarchy | Credentials file on MySQL volume preserves admin password |
| `auth_credentials` | bcrypt hashes, TOTP secrets | |
| `api_keys` | CLI auth keys, approval status | |
| `db_hosts` | Configured target hosts | |
| `user_hosts` | User-to-host assignments | |
| `jobs` | All job records (all statuses) | Including history of completed/failed jobs |
| `job_events` | Per-job event logs | |
| `job_history_summary` | Aggregated restore metrics | The pool that failed in 1.2.0 production — fixed in 1.4.0 |
| `settings` | Runtime configuration | |
| `admin_tasks` | Pending admin tasks | |
| `audit_logs` | Admin/manager action trail | |
| `procedure_deployments` | Per-host stored procedure state | |
| `disallowed_users` | Blocked username list | |
| `feature_requests` | User feedback and votes | |

### Planned Loss

| Table | Contents | Reason |
|-------|----------|--------|
| `sessions` | Web session tokens | Acceptable: sessions expire naturally; users re-login after upgrade |
| `locks` | Advisory lock rows | Transient by design: always recreated when needed |

Sessions and locks do not contain user data. Losing them causes a one-time re-login for all users after upgrade — this is expected and documented in the maintenance window communication.

---

## Prerequisites

### Before Starting

```bash
# 1. Verify current active container and version
sudo docker ps --filter name=pulldb --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
cat /etc/pulldb/.active-color

# 2. Verify state files are in place
ls -la /etc/pulldb/.env.active /etc/pulldb/.env.blue /etc/pulldb/.active-color /etc/pulldb/docker-compose.yml

# 3. Check available images
sudo docker images pulldb --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# 4. Confirm Secrets Manager credentials are correct (BUG-1 root cause)
#    The username in the secret MUST be 'pulldb_api' (not 'pulldb_app')
aws secretsmanager get-secret-value \
  --secret-id /pulldb/mysql/coordination-db \
  --query SecretString --output text | python3 -m json.tool | grep username
# Expected: "username": "pulldb_api"

# 5. Test the dry run
sudo ./scripts/upgrade.sh --dry-run pulldb:1.3.0
```

### Upgrade-Test Environment (dev-util-dev)

The upgrade-test environment runs on ports 8002/8082 with all AWS credentials removed (air-gapped). State directory: `/etc/pulldb-upgrade-test/`. Container prefix: `pulldb-upgrade-test`.

```bash
# Check upgrade-test state
sudo docker ps --filter name=pulldb-upgrade-test
cat /etc/pulldb-upgrade-test/.active-color
```

---

## Step 1 — Build the 1.4.0 Image

The `pulldb:1.4.0` image does not yet exist. It must be built from the `dev/v1.4.0` branch.

```bash
# 1a. Merge dev/v1.4.0 to main (via PR — do not push directly)
#     PR must pass CI before merge.
#     After merge, main contains: factory.py socket fix, worker history validation,
#     upgrade.sh 3 bug fixes, upgrade runbook.

# 1b. On the build host, pull latest main
git checkout main && git pull origin main

# 1c. Build and tag the image
# (Exact build command depends on your CI / build script — adapt as needed)
sudo docker build -t pulldb:1.4.0 -t pulldb:latest .

# 1d. Verify the image contains the socket fix
sudo docker run --rm --entrypoint bash pulldb:1.4.0 -c \
  "grep -A3 'unix_socket = os.getenv' /opt/pulldb.service/pulldb/infra/factory.py"
# Expected output:
#   unix_socket = os.getenv("PULLDB_MYSQL_SOCKET")
#   if unix_socket:
#       kwargs["unix_socket"] = unix_socket

# 1e. Verify history validation is present
sudo docker run --rm --entrypoint bash pulldb:1.4.0 -c \
  "grep '_validate_history_connectivity' /opt/pulldb.service/pulldb/worker/service.py"
# Expected: two lines (function definition and call site)
```

**Do not proceed until both verification commands succeed.** These are the two AAR fixes — if they're missing, the upgrade addresses nothing.

---

## Step 2 — Upgrade-Test: 1.2.0 → 1.3.0

Run this first on the upgrade-test environment to confirm the path before touching production.

```bash
# Current state: pulldb-upgrade-test-blue running 1.2.0 (or re-establish if needed)
sudo docker ps --filter name=pulldb-upgrade-test

# If the upgrade-test environment is already on 1.3.0 (green), you may skip to Step 3.
# If blue is running 1.2.0, proceed:

sudo ./scripts/upgrade.sh \
  --state-dir /etc/pulldb-upgrade-test \
  --compose-file /home/charleshandshy/Projects/pullDB/compose/docker-compose.yml \
  --prefix pulldb-upgrade-test \
  --port-web 8002 --port-api 8082 \
  --skip-ecr --skip-drain \
  --yes \
  pulldb:1.3.0
```

**Expected outcome:**
- Phase 5 (validate) passes all tiers (Tier 3 QA skipped — air-gapped, no S3)
- Active color becomes `green`
- `pulldb-upgrade-test-green` running 1.3.0 on 8002/8082
- `pulldb-upgrade-test-blue` stopped (available for rollback)

**Verify:**
```bash
curl -fsk https://localhost:8082/api/health
# {"status":"ok"}

cat /etc/pulldb-upgrade-test/.active-color
# green
```

---

## Step 3 — Upgrade-Test: 1.3.0 → 1.4.0

```bash
# Prerequisite: 1.4.0 image built (Step 1 complete)
# Current state: upgrade-test-green running 1.3.0

sudo ./scripts/upgrade.sh \
  --state-dir /etc/pulldb-upgrade-test \
  --compose-file /home/charleshandshy/Projects/pullDB/compose/docker-compose.yml \
  --prefix pulldb-upgrade-test \
  --port-web 8002 --port-api 8082 \
  --skip-ecr --skip-drain \
  --yes \
  pulldb:1.4.0
```

**Expected outcome:**
- Phase 5 passes
- Active color becomes `blue` (alternates each upgrade)
- `pulldb-upgrade-test-blue` running 1.4.0 on 8002/8082

**Verify socket fix is active:**
```bash
# Worker should log the history pool validation at startup
sudo docker logs pulldb-upgrade-test-blue 2>&1 | grep -i "history pool"
# Expected: [pulldb-worker] History pool connectivity validated
```

**Verify data integrity:**
```bash
sudo docker exec pulldb-upgrade-test-blue mysql pulldb_service -e "
  SELECT 'users' as tbl, COUNT(*) as cnt FROM auth_users
  UNION SELECT 'hosts', COUNT(*) FROM db_hosts
  UNION SELECT 'settings', COUNT(*) FROM settings
  UNION SELECT 'history', COUNT(*) FROM job_history_summary;"
```

All counts must match what was present before the upgrade. If any count is 0 that should not be 0, stop and investigate before proceeding.

---

## Step 4 — Production Pre-Flight

Before touching production, complete this checklist. All items must pass.

```bash
# P1. Current production state
sudo docker ps --filter name=pulldb-blue --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
sudo docker ps --filter name=pulldb-green --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
cat /etc/pulldb/.active-color

# P2. State directory integrity
ls -la /etc/pulldb/.active-color \
        /etc/pulldb/.env.active \
        /etc/pulldb/.env.blue \
        /etc/pulldb/docker-compose.yml \
        /etc/pulldb/service.env
# All must exist. Missing files = stop and re-establish state dir.

# P3. Active container is healthy
ACTIVE=$(cat /etc/pulldb/.active-color)
curl -fsk https://localhost:8080/api/health
# {"status":"ok"}

# P4. No jobs currently running (if possible — otherwise schedule during low-traffic)
sudo docker exec pulldb-${ACTIVE} mysql pulldb_service -N \
  -e "SELECT COUNT(*) FROM jobs WHERE status IN ('running','canceling')"
# Ideally 0. If > 0, wait or accept that those jobs will be interrupted.

# P5. Secrets Manager credentials are correct
aws secretsmanager get-secret-value \
  --secret-id /pulldb/mysql/coordination-db \
  --query SecretString --output text | python3 -m json.tool | grep username
# MUST be "pulldb_api" — not "pulldb_app"
# If wrong: aws secretsmanager update-secret --secret-id /pulldb/mysql/coordination-db \
#             --secret-string '{"host":"...","port":3306,"username":"pulldb_api","password":"..."}'

# P6. MySQL data is bind-mounted (not a named volume)
sudo docker inspect pulldb-${ACTIVE} \
  --format '{{range .Mounts}}{{.Type}} {{.Source}} → {{.Destination}}{{"\n"}}{{end}}'
# Must show 'bind /mnt/data/mysql-<color> → /var/lib/mysql'
# If it shows 'volume ...' (Docker-managed named volume): do NOT proceed.
# Named volume means docker cp works but mysql data path is unpredictable after promote.
# Resolve by: docker stop active → docker cp data out → recreate with bind mount.

# P7. Disk space for data snapshot
df -h /mnt/data /tmp
# /mnt/data should have >= 2x the current MySQL data size
# /tmp should have >= 1x the MySQL data size (used for snapshot copy)
sudo docker exec pulldb-${ACTIVE} du -sh /var/lib/mysql
```

---

## Step 5 — Production: 1.2.0 → 1.3.0

Schedule during the maintenance window (18:00–07:00). The system goes offline during Phase 3 (snapshot) through Phase 6 (promote) — typically 3–8 minutes depending on MySQL data size.

```bash
# Dry run first
sudo ./scripts/upgrade.sh --dry-run pulldb:1.3.0

# Confirm the plan looks correct, then proceed:
sudo ./scripts/upgrade.sh --yes pulldb:1.3.0
```

**Upgrade.sh will:**
1. Wait for maintenance window (or prompt if outside window)
2. Enable maintenance mode
3. Wait for running jobs to drain (until 7 AM deadline)
4. Stop active container (system offline)
5. Snapshot MySQL data
6. Start candidate on ports 18000/18080
7. Run 3-tier validation
8. Promote candidate to real ports 8000/8080
9. Disable maintenance mode

**Phase 5 validation tiers:**

| Tier | What it checks | Must pass? |
|------|---------------|------------|
| 1 | `GET /api/health` → `{"status":"ok"}` | Yes — hard failure |
| 2 | 17 tables + admin user present | Yes — hard failure |
| 3 | Real S3 restore of most recent backup | If `PULLDB_VALIDATE_S3_PATH` is set |

To enable Tier 3, add to `/etc/pulldb/.env.active` before upgrading:
```bash
PULLDB_VALIDATE_S3_PATH=s3://pestroutes-rds-backup-prod-vpc-us-east-1-s3/daily/prod/
PULLDB_VALIDATE_AWS_PROFILE=pr-prod
```

**Post-upgrade verification:**
```bash
# Service is up
curl -fsk https://localhost:8080/api/health

# Active is now green (or whichever color the candidate was)
cat /etc/pulldb/.active-color

# Maintenance mode is disabled (workers accepting jobs)
sudo docker exec pulldb-$(cat /etc/pulldb/.active-color) \
  mysql pulldb_service -N -e "SELECT setting_value FROM settings WHERE setting_key='maintenance_mode'"
# Expected: false

# Data counts — compare with pre-upgrade baseline
ACTIVE=$(cat /etc/pulldb/.active-color)
sudo docker exec pulldb-${ACTIVE} mysql pulldb_service -e "
  SELECT 'users' as tbl, COUNT(*) FROM auth_users
  UNION SELECT 'api_keys', COUNT(*) FROM api_keys
  UNION SELECT 'hosts', COUNT(*) FROM db_hosts
  UNION SELECT 'jobs', COUNT(*) FROM jobs
  UNION SELECT 'job_events', COUNT(*) FROM job_events
  UNION SELECT 'history', COUNT(*) FROM job_history_summary
  UNION SELECT 'audit', COUNT(*) FROM audit_logs
  UNION SELECT 'settings', COUNT(*) FROM settings;"
```

Allow production traffic to run for at least 30 minutes and confirm:
- Jobs can be queued and processed
- Web UI accessible
- CLI authentication works (existing API keys still valid)

---

## Step 6 — Production: 1.3.0 → 1.4.0

After Step 5 is stable (minimum 24 hours recommended), upgrade to 1.4.0.

```bash
# Dry run
sudo ./scripts/upgrade.sh --dry-run pulldb:1.4.0

# Proceed
sudo ./scripts/upgrade.sh --yes pulldb:1.4.0
```

**Critical verification for 1.4.0 specifically:**

```bash
ACTIVE=$(cat /etc/pulldb/.active-color)

# 1. Socket passthrough is working — API pool uses socket, not TCP
sudo docker exec pulldb-${ACTIVE} mysql pulldb_service -e "SELECT 1" 2>/dev/null \
  && echo "MySQL accessible"

# 2. History connectivity validation ran at startup — check worker logs
sudo docker logs pulldb-${ACTIVE} 2>&1 | grep -i "history pool"
# Expected: History pool connectivity validated  phase=startup

# 3. Worker is running (failed history check causes worker exit code 1)
sudo docker exec pulldb-${ACTIVE} supervisorctl status pulldb-worker
# Expected: pulldb-worker    RUNNING

# 4. Data integrity — full count comparison
sudo docker exec pulldb-${ACTIVE} mysql pulldb_service -e "
  SELECT 'users' as tbl, COUNT(*) FROM auth_users
  UNION SELECT 'api_keys', COUNT(*) FROM api_keys
  UNION SELECT 'hosts', COUNT(*) FROM db_hosts
  UNION SELECT 'jobs_total', COUNT(*) FROM jobs
  UNION SELECT 'jobs_active', COUNT(*) FROM jobs WHERE status NOT IN ('deleted','expired')
  UNION SELECT 'job_events', COUNT(*) FROM job_events
  UNION SELECT 'history', COUNT(*) FROM job_history_summary
  UNION SELECT 'audit', COUNT(*) FROM audit_logs
  UNION SELECT 'procedure_deploys', COUNT(*) FROM procedure_deployments
  UNION SELECT 'feature_requests', COUNT(*) FROM feature_requests;"
```

All counts must be >= the pre-upgrade baseline. The history count may increase slightly (worker will have written new entries during the upgrade window drain).

---

## Rollback

### Immediate Rollback (within upgrade window)

If `upgrade.sh` itself detects a validation failure, it automatically restores the previous container. No manual action needed.

### Manual Rollback (after promotion)

If problems emerge after promotion, the previous container is stopped but available:

```bash
sudo ./scripts/rollback.sh
```

> **Note:** `rollback.sh` only works with the default container prefix (`pulldb-blue` / `pulldb-green`). For the upgrade-test environment (prefix `pulldb-upgrade-test`), rollback must be done manually:
>
> ```bash
> # Upgrade-test manual rollback
> PREV_COLOR=blue   # whichever is the previous
> sudo docker stop pulldb-upgrade-test-green
> sudo docker compose \
>   -p pulldb-upgrade-test-${PREV_COLOR} \
>   --env-file /etc/pulldb-upgrade-test/.env.${PREV_COLOR} \
>   -f /home/charleshandshy/Projects/pullDB/compose/docker-compose.yml \
>   up -d
> echo "${PREV_COLOR}" | sudo tee /etc/pulldb-upgrade-test/.active-color
> sudo cp /etc/pulldb-upgrade-test/.env.${PREV_COLOR} /etc/pulldb-upgrade-test/.env.active
> ```

### Rollback Window

The previous container remains available until explicitly removed. Do not run `docker rm pulldb-<color>` until you are confident the new version is stable.

| Action | Effect |
|--------|--------|
| `docker rm pulldb-blue` | Closes rollback window — previous version gone |
| Data at `/mnt/data/mysql-blue` | Still on disk even after container removal |

If you need to roll back after removing the container, the data is still there. You can recreate the container using the env file:
```bash
sudo docker compose \
  -p pulldb-blue \
  --env-file /etc/pulldb/.env.blue \
  -f /etc/pulldb/docker-compose.yml \
  up -d
```

---

## Known Issues and Mitigations

### Secrets Manager credential drift

The 1.2.0 production incident was caused by `/pulldb/mysql/coordination-db` having `username: pulldb_app` (non-existent user). The correct username is `pulldb_api`.

**Mitigation for this upgrade:** verify Step P5 passes before upgrading. 1.4.0's `_validate_history_connectivity()` will fail fast at worker startup if credentials are wrong, making future incidents immediately visible rather than silent for 8 minutes.

### MySQL data ownership

`upgrade.sh` Phase 3 now dynamically detects the mysql UID from the new image (`id -u mysql` inside the candidate image). This handles any UID change between image versions. The value for both 1.3.0 and 1.4.0 is UID 101 / GID 102.

### Named volume vs bind mount

If the production MySQL data is in a Docker-managed named volume (not a bind mount at a known path), upgrade.sh still works via `docker cp`. However, the promoted data path (`/mnt/data/mysql-<color>`) changes from the volume, making future data management harder. Resolve by migrating to a bind mount before the next upgrade cycle.

### rollback.sh prefix limitation

`rollback.sh` hardcodes `pulldb-${COLOR}`. It will NOT work for non-default prefixes. A `--prefix` flag should be added in a future version. For now, use the manual rollback commands shown above.

---

## Data Integrity Baseline Capture

Before any production upgrade, record baseline counts:

```bash
ACTIVE=$(cat /etc/pulldb/.active-color)
echo "=== BASELINE: $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" \
  | sudo tee -a /etc/pulldb/upgrade-baseline.log

sudo docker exec pulldb-${ACTIVE} mysql pulldb_service -e "
  SELECT 'auth_users'           , COUNT(*) FROM auth_users
  UNION SELECT 'auth_credentials', COUNT(*) FROM auth_credentials
  UNION SELECT 'api_keys'        , COUNT(*) FROM api_keys
  UNION SELECT 'db_hosts'        , COUNT(*) FROM db_hosts
  UNION SELECT 'user_hosts'      , COUNT(*) FROM user_hosts
  UNION SELECT 'jobs'            , COUNT(*) FROM jobs
  UNION SELECT 'job_events'      , COUNT(*) FROM job_events
  UNION SELECT 'job_history_summary', COUNT(*) FROM job_history_summary
  UNION SELECT 'settings'        , COUNT(*) FROM settings
  UNION SELECT 'admin_tasks'     , COUNT(*) FROM admin_tasks
  UNION SELECT 'audit_logs'      , COUNT(*) FROM audit_logs
  UNION SELECT 'procedure_deployments', COUNT(*) FROM procedure_deployments
  UNION SELECT 'disallowed_users', COUNT(*) FROM disallowed_users
  UNION SELECT 'feature_requests', COUNT(*) FROM feature_requests;" \
  | sudo tee -a /etc/pulldb/upgrade-baseline.log
```

Run this before each hop (before 1.2.0→1.3.0 and before 1.3.0→1.4.0). Compare counts after each upgrade.

---

## Summary Checklist

```
□ Step 1   — Build pulldb:1.4.0 image from merged dev/v1.4.0
             Verify: socket fix present, history validation present

□ Step 2   — Upgrade-test: 1.2.0 → 1.3.0
             Verify: green healthy on 8002/8082, data counts match

□ Step 3   — Upgrade-test: 1.3.0 → 1.4.0
             Verify: blue healthy, worker logs "History pool connectivity validated"

□ Step P5  — Production pre-flight (all 7 checks pass)
             Especially: Secrets Manager username = pulldb_api

□ Step 5   — Capture baseline counts
□ Step 5   — Production: 1.2.0 → 1.3.0
             Verify: health ok, counts match baseline, jobs processing

□ Step 5   — Monitor production for 24h minimum

□ Step 6   — Capture new baseline counts
□ Step 6   — Production: 1.3.0 → 1.4.0
             Verify: health ok, worker socket validation logged, counts match

□ Final    — Monitor 24h, then remove previous container to close rollback window
```

---

[← Upgrade Runbook](upgrade.md) · [Deployment →](deployment.md)
