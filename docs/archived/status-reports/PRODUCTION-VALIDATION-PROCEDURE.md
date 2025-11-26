# Production Validation Procedure

**Purpose**: Document step-by-step procedure for first production validation restore  
**Status**: Ready for execution  
**Target**: Complete 10 successful production restores to meet exit criterion  
**Created**: Nov 5, 2025  
**Owner**: [Technical Lead]

---

## Overview

This document provides the complete procedure for executing production validation restores during the release freeze period. Each restore must be fully documented in `PRODUCTION-RESTORE-LOG.md` to track progress toward the 10-restore exit criterion.

---

## Prerequisites

### Required Access
- [ ] AWS profile configured: `PULLDB_AWS_PROFILE=default` (or appropriate profile)
- [ ] MySQL coordination database credentials accessible via AWS Secrets Manager
- [ ] Target database host credentials accessible via AWS Secrets Manager
- [ ] S3 bucket read access: `s3://pestroutesrdsdbs/daily/stg/` (staging backups)
- [ ] SSH access to pullDB service host (development environment)

### Required Components
- [ ] pullDB CLI installed and accessible
- [ ] pullDB worker service running: `systemctl status pulldb-worker`
- [ ] MySQL coordination database schema deployed (6 tables, 1 view, 1 trigger)
- [ ] Post-SQL scripts present: `customers_after_sql/` (12 scripts) and `qa_template_after_sql/`
- [ ] Target database host registered in `db_hosts` table
- [ ] User registered in `auth_users` table

### Verification Commands
```bash
# Verify pullDB CLI
pulldb --version

# Verify worker service
systemctl status pulldb-worker

# Verify AWS access
aws s3 ls s3://pestroutesrdsdbs/daily/stg/ --profile default

# Verify coordination DB access
pulldb status  # Should return empty queue or existing jobs
```

---

## Restore Selection Strategy

### Phase 1: Low-Risk Validation (Restores 1-3)

**Target Type**: Small QA templates  
**Rationale**: Minimize impact, quick validation, predictable duration

**Recommended Targets**:
1. **qatemplate** (smallest available QA template)
2. **qatemplate** (re-restore to verify staging cleanup)
3. **qatemplate** (third restore to confirm repeatability)

**Success Criteria**:
- Restore completes without errors
- Post-SQL scripts execute successfully (if any for QA templates)
- Staging database cleaned up after completion
- Target database accessible and contains expected tables
- Duration < 30 minutes

---

### Phase 2: Medium-Risk Validation (Restores 4-7)

**Target Type**: Small customer databases  
**Rationale**: Validate customer restore workflow with PII sanitization

**Recommended Targets**:
- Select 4 small customer databases (< 5 GB recommended)
- Prefer customers with known stable schema
- Avoid critical production customers

**Success Criteria**:
- All Phase 1 criteria met
- All 12 customer post-SQL scripts execute successfully
- PII removed and verified spot-check
- No unhandled exceptions in logs

---

### Phase 3: High-Confidence Validation (Restores 8-10)

**Target Type**: Varied sizes and types  
**Rationale**: Demonstrate stability across workload spectrum

**Recommended Targets**:
- Mix of customer databases and QA templates
- Include at least one medium-sized database (5-15 GB)
- Repeat one previous target to verify consistency

**Success Criteria**:
- All previous criteria met
- Average duration across all 10 restores < 30 minutes
- Zero unhandled exceptions across all restores

---

## Pre-Restore Checklist

Before initiating each restore, verify:

### Environment Checks
- [ ] Worker service running: `systemctl status pulldb-worker`
- [ ] No stuck jobs in queue: `pulldb status`
- [ ] Sufficient disk space on target host: `df -h /var/lib/mysql`
- [ ] Target database does not exist (or overwrite flag ready)
- [ ] AWS credentials active: `aws sts get-caller-identity`

### Monitoring Setup
- [ ] Terminal window open for live log tailing: `journalctl -u pulldb-worker -f`
- [ ] Stopwatch or timer ready to record duration
- [ ] Notepad or log file ready for observations

### Rollback Preparation
- [ ] Target database backed up (if exists): `mysqldump` or snapshot
- [ ] Rollback procedure documented and ready
- [ ] Emergency contact available if critical issues arise

---

## Restore Execution Steps

### Step 1: Initiate Restore

**Command**:
```bash
pulldb user=<username> customer=<customer_id> dbhost=<target_host>
# OR for QA template:
pulldb user=<username> qatemplate dbhost=<target_host>
```

**Example**:
```bash
pulldb user=validator customer=testcust01 dbhost=dev-db-01
```

**Record**:
- Start time: `__:__:__ UTC`
- Command executed: `<exact command>`
- Job ID returned: `<uuid>`

---

### Step 2: Monitor Job Progress

**Status Check**:
```bash
pulldb status  # Check queue position
pulldb status --json | jq '.[] | select(.job_id=="<job_id>")'  # Detailed JSON
```

**Live Logs**:
```bash
journalctl -u pulldb-worker -f | grep '<job_id>'
```

**Watch for Key Events**:
- Job transitions: `queued` → `running` → `complete`
- S3 backup discovery
- Download progress
- Disk capacity check
- myloader execution
- Post-SQL script execution (each script logged individually)
- Staging database cleanup
- Atomic rename to target

**Alert Conditions**:
- Status stuck in `running` > 30 minutes
- Error messages in logs
- Unexpected exceptions
- Disk space warnings

---

### Step 3: Validate Completion

#### 3.1 Check Job Status
```bash
pulldb status --wide | grep '<job_id>'
```

**Expected**: `status=complete`, `completed_at` timestamp present

#### 3.2 Verify Target Database Exists
```bash
mysql -h <target_host> -e "SHOW DATABASES LIKE '<target_db>';"
```

**Expected**: One row returned with target database name

#### 3.3 Verify Table Count
```bash
mysql -h <target_host> <target_db> -e "SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema='<target_db>';"
```

**Expected**: Non-zero table count matching backup source

#### 3.4 Verify Metadata Table
```bash
mysql -h <target_host> <target_db> -e "SELECT * FROM pullDB;"
```

**Expected Output**:
- `restored_by`: Username who initiated restore
- `restored_at`: Timestamp of restore completion
- `backup_filename`: S3 backup file used
- `post_sql_report`: JSON with script execution results

#### 3.5 Verify Post-SQL Execution (Customer Only)
```bash
mysql -h <target_host> <target_db> -e "SELECT * FROM pullDB;" | jq -r '.post_sql_report'
```

**Expected**: All 12 scripts executed successfully with timing data

#### 3.6 Verify Staging Database Cleaned Up
```bash
mysql -h <target_host> -e "SHOW DATABASES LIKE '<target>_%';"
```

**Expected**: Empty result (no staging databases remaining)

#### 3.7 Spot-Check Data Sanitization (Customer Only)
```bash
# Check PII removal (should return 0 or NULL values)
mysql -h <target_host> <target_db> -e "SELECT COUNT(*) FROM Customers WHERE Email LIKE '%@%';"
mysql -h <target_host> <target_db> -e "SELECT COUNT(*) FROM BillTo WHERE CreditCardNumber IS NOT NULL;"
```

**Expected**: PII fields cleared or anonymized per post-SQL scripts

---

### Step 4: Record Results

**Update `PRODUCTION-RESTORE-LOG.md`** with:
- Job ID
- Target database
- User code
- Start time
- End time
- Duration (minutes)
- Status (success/failed)
- Observations
- Issues encountered (if any)
- Metrics captured

**Example Entry**:
```markdown
| 10 | 2025-11-05 14:30 UTC | validqatemplate | validator | dev-db-01 | success | 8m 23s | Small QA template, clean execution, no issues |
```

---

## Post-Restore Verification

### Metrics Collection

Record the following for exit criteria tracking:

**From Job Events Table**:
```sql
SELECT 
    event_type,
    created_at,
    detail
FROM job_events
WHERE job_id = '<job_id>'
ORDER BY created_at;
```

**Key Metrics**:
- Queue time: `queued` → `running` transition
- Download duration: Extract from S3 download event
- myloader duration: Extract from myloader complete event
- Post-SQL duration: Extract from post-SQL complete event
- Total duration: `running` → `complete` transition

**From Worker Logs**:
```bash
journalctl -u pulldb-worker --since "1 hour ago" | grep '<job_id>' > restore-<job_id>.log
```

**Structured Metrics**:
```bash
# Extract metrics from JSON logs
cat restore-<job_id>.log | jq -r 'select(.job_id=="<job_id>") | select(.metric != null) | "\(.metric): \(.value)"'
```

**Expected Metrics**:
- `pulldb.queue.depth`: Current queue size
- `pulldb.restore.duration`: Total restore time
- `pulldb.disk.check`: Disk capacity validation
- `pulldb.postsql.duration`: Per-script execution time

---

## Rollback Procedure

### Scenario 1: Restore Failed Mid-Process

**Symptoms**:
- Job status stuck in `running`
- Error messages in logs
- Staging database exists but incomplete

**Actions**:
1. Check worker logs for specific error: `journalctl -u pulldb-worker | grep '<job_id>'`
2. Verify staging database state: `mysql -e "SHOW DATABASES LIKE '<target>_%';"'`
3. If staging exists: `mysql -e "DROP DATABASE <staging_db>;"` (manual cleanup)
4. Document error in `PRODUCTION-RESTORE-LOG.md`
5. Investigate root cause before retry

**Do NOT**:
- Restart worker service without documenting state
- Drop target database if it existed before restore
- Retry immediately without understanding failure

---

### Scenario 2: Post-SQL Scripts Failed

**Symptoms**:
- Staging database exists with data
- Post-SQL error in logs
- Target database not renamed

**Actions**:
1. Review post-SQL error: Check which script failed and why
2. Staging database contains partial restore - inspect if needed
3. Manual cleanup: `DROP DATABASE <staging_db>;`
4. Fix post-SQL script bug if applicable
5. Retry restore after validation

---

### Scenario 3: Target Database Corrupted

**Symptoms**:
- Restore completed but target database inaccessible
- Missing tables or schema issues
- Data validation failed

**Actions**:
1. Backup current state: `mysqldump <target_db> > corrupt-backup.sql`
2. Drop corrupted database: `DROP DATABASE <target_db>;`
3. Restore from pre-restore backup (if exists)
4. Document corruption details
5. Investigate before retry

---

## Success Criteria Per Restore

### Required (MUST PASS)
- [ ] Job status: `complete`
- [ ] Target database exists and accessible
- [ ] Metadata table (`pullDB`) present with correct values
- [ ] All post-SQL scripts executed successfully (customer restores)
- [ ] No staging database remains after completion
- [ ] No unhandled exceptions in logs
- [ ] Duration < 30 minutes

### Optional (SHOULD PASS)
- [ ] Disk capacity check passed
- [ ] All metrics emitted correctly
- [ ] Logs contain structured JSON events
- [ ] Backup filename recorded in metadata

### Nice-to-Have (MAY PASS)
- [ ] Performance within expected range for database size
- [ ] No warnings in logs

---

## Failure Handling

### Critical Failures (STOP VALIDATION)
- Worker service crashes or becomes unresponsive
- MySQL coordination database unavailable
- AWS credentials expired or inaccessible
- Disk space exhausted on target host
- Data corruption detected in target database

**Action**: Document failure, fix root cause, restart validation process

---

### Non-Critical Failures (RETRY ALLOWED)
- Specific restore fails due to temporary network issue
- Post-SQL script fails due to schema edge case
- Target database already exists (forgot overwrite flag)

**Action**: Document failure, fix issue, retry same target

---

### Monitoring Failures (INVESTIGATE)
- Metrics not appearing in logs
- Structured logging format incorrect
- Job events not recorded in database

**Action**: Document, continue validation, fix before declaring Criterion 7 met

---

## Exit Criteria Validation

After completing 10 successful restores, verify:

### Criterion 2: Successful Production Restores
- [ ] 10 restores completed successfully
- [ ] All documented in `PRODUCTION-RESTORE-LOG.md`
- [ ] Mix of customer and QA template restores
- [ ] At least 3 re-restores to same target (verify staging cleanup)

### Criterion 4: Average Restore Duration
- [ ] Calculate average: `SUM(durations) / 10`
- [ ] Result < 30 minutes
- [ ] Document range (min, max, median)

### Criterion 7: Metrics Accuracy
- [ ] All restores emitted expected metrics
- [ ] Structured JSON logging present in all logs
- [ ] Queue depth tracked correctly
- [ ] Disk capacity checks logged
- [ ] Restore durations recorded

### Criterion 3: Begin Exception Monitoring
- [ ] All 10 restores completed without unhandled exceptions
- [ ] Start 14-day monitoring period
- [ ] Set up daily log review process

---

## Troubleshooting

### Common Issues

**Issue**: Job stuck in `queued` status  
**Cause**: Worker service not running  
**Solution**: `systemctl start pulldb-worker`

**Issue**: S3 backup not found  
**Cause**: Customer/template name typo or backup missing  
**Solution**: Verify customer ID, check S3 bucket listing

**Issue**: Disk space insufficient  
**Cause**: Target host low on disk space  
**Solution**: Free space or select different target host

**Issue**: myloader binary not found  
**Cause**: myloader not installed on target host  
**Solution**: Install myloader: `apt-get install mydumper`

**Issue**: Post-SQL script fails  
**Cause**: Schema mismatch or script bug  
**Solution**: Review script, fix if needed, retry

**Issue**: Staging database not cleaned up  
**Cause**: Cleanup logic bug or incomplete restore  
**Solution**: Manual cleanup: `DROP DATABASE <staging_db>;`

---

## Documentation Requirements

### During Each Restore

Document in real-time:
- Start time (UTC)
- Command executed
- Job ID returned
- Key events observed
- Any errors or warnings
- End time (UTC)
- Duration calculated
- Final status

### After Validation Complete

Update documentation:
- `PRODUCTION-RESTORE-LOG.md`: All 10 restore entries
- `STABILITY-EXIT-CRITERIA.md`: Mark Criterion 2, 4, 7 as met
- `STATUS-REPORT-*.md`: Update with validation results
- `RELEASE-NOTES-v0.0.1.md`: Add production validation summary

---

## Safety Guidelines

### DO
- Always verify worker service is running before restore
- Monitor logs actively during first 3 restores
- Document every observation, even if minor
- Take breaks between restores to review logs
- Use low-risk targets for initial validation

### DON'T
- Rush through validation without monitoring
- Skip documentation steps
- Restore to critical production databases
- Ignore warnings or errors in logs
- Retry failed restores without understanding cause
- Run multiple restores in parallel (queue sequentially)

---

## Post-Validation Next Steps

After completing 10 successful restores:

1. **Calculate Metrics**:
   - Average restore duration
   - Success rate (should be 100%)
   - Metrics emission coverage

2. **Update Tracking**:
   - Mark Criterion 2 as MET in `STABILITY-EXIT-CRITERIA.md`
   - Mark Criterion 4 as MET if average < 30 minutes
   - Mark Criterion 7 as MET if all metrics validated

3. **Begin Monitoring Period**:
   - Start 14-day exception monitoring (Criterion 3)
   - Set up daily log review
   - Configure alerting if not already done

4. **Progress Check**:
   - Review exit criteria: Should be 6/7 or 7/7 met
   - Only Criterion 3 (14-day monitoring) remains
   - Estimated release date: Start date + 14 days

---

## Contact & Escalation

**For Technical Issues**:
- Technical Lead: [Contact]
- Ops Lead: [Contact]

**For Access Issues**:
- AWS Admin: [Contact]
- MySQL DBA: [Contact]

**For Critical Failures**:
- Emergency contact: [Contact]
- Escalation path: [Process]

---

**Version**: 1.0.0  
**Status**: Ready for execution  
**Next Review**: After completing first 3 restores

