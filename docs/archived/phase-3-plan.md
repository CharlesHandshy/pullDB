# Phase 3: Multi-Daemon & Distributed Locks

> **Status**: Planning
> **Prerequisites**: Phase 2 complete (v0.0.4)
> **Duration**: 1-2 weeks
> **Target**: Enable multiple worker instances to safely process jobs concurrently

## Problem Statement

Currently, pullDB runs a **single worker instance**. If we scale to multiple workers:

1. **Race Condition**: Two workers could both call `get_next_queued_job()` and receive the same job
2. **Double Processing**: Both workers would attempt to restore the same database
3. **Corruption Risk**: Concurrent restores to the same target could corrupt data

## Current Implementation Analysis

### Job Acquisition (Current - UNSAFE for Multi-Worker)

```python
# pulldb/infra/mysql.py - JobRepository.get_next_queued_job()
cursor.execute("""
    SELECT id, ...
    FROM jobs
    WHERE status = 'queued'
    ORDER BY submitted_at ASC
    LIMIT 1
""")
row = cursor.fetchone()
return self._row_to_job(row) if row else None
```

**Problem**: No locking between SELECT and subsequent `mark_job_running()` UPDATE.

### Worker Loop (Current)

```python
# pulldb/worker/loop.py
job = job_repo.get_next_queued_job()  # SELECT without lock
if job:
    job_repo.mark_job_running(job.id)  # UPDATE - race window!
    job_executor(job)
```

**Problem**: Between `get_next_queued_job()` and `mark_job_running()`, another worker could claim the same job.

## Solution Options

### Option 1: MySQL Row-Level Locking (SELECT FOR UPDATE) ✅ RECOMMENDED

**How it works**:
```sql
START TRANSACTION;
SELECT id, ... FROM jobs 
WHERE status = 'queued' 
ORDER BY submitted_at ASC 
LIMIT 1 
FOR UPDATE SKIP LOCKED;

-- If row found, update it within same transaction
UPDATE jobs SET status = 'running', started_at = NOW() WHERE id = ?;
COMMIT;
```

**Pros**:
- ✅ No additional infrastructure (uses existing MySQL)
- ✅ Proven pattern for job queues
- ✅ `SKIP LOCKED` prevents workers from blocking each other
- ✅ Atomic claim within single transaction
- ✅ InnoDB row-level locking is efficient

**Cons**:
- ❌ Requires transaction management (currently using auto-commit)
- ❌ Lock held during network round-trip to worker

**Implementation Effort**: ~4 hours

### Option 2: MySQL Advisory Locks (GET_LOCK)

**How it works**:
```sql
SELECT GET_LOCK('pulldb_worker_claim', 0) AS acquired;
-- If acquired = 1, proceed with job claim
-- Release with RELEASE_LOCK('pulldb_worker_claim')
```

**Pros**:
- ✅ Simple API
- ✅ Named locks can be per-worker or global

**Cons**:
- ❌ Only one worker can claim at a time (serialized)
- ❌ Lock is per-connection, not per-transaction
- ❌ Must manually release (risk of orphaned locks)

**Implementation Effort**: ~2 hours

### Option 3: Optimistic Locking with Version Column

**How it works**:
```sql
-- Add version column to jobs table
UPDATE jobs 
SET status = 'running', version = version + 1, started_at = NOW()
WHERE id = ? AND status = 'queued' AND version = ?;
-- Check affected rows: if 0, another worker claimed it
```

**Pros**:
- ✅ No blocking
- ✅ Simple retry logic

**Cons**:
- ❌ Requires schema change
- ❌ Workers may spin retrying on high contention
- ❌ Not truly FIFO under contention

**Implementation Effort**: ~6 hours

### Option 4: External Distributed Lock (Redis/Consul/DynamoDB)

**Pros**:
- ✅ Cross-service coordination
- ✅ TTL-based lock expiry

**Cons**:
- ❌ Additional infrastructure dependency
- ❌ Network latency to lock service
- ❌ Overkill for current scale

**Implementation Effort**: ~2-3 days

## Recommended Approach: Option 1 (SELECT FOR UPDATE SKIP LOCKED)

### Why This Option

1. **Zero new dependencies** - Uses MySQL we already have
2. **Battle-tested** - This is THE pattern for database job queues
3. **SKIP LOCKED** - MySQL 8.0+ feature that prevents worker blocking
4. **Atomic claim** - Transaction ensures claim and status update are atomic

### Implementation Plan

#### Task 1: Add Transaction Support to MySQLPool (~1 hour)

```python
# pulldb/infra/mysql.py

class MySQLPool:
    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Get connection with explicit transaction control."""
        conn = mysql.connector.connect(**self._kwargs)
        conn.autocommit = False  # Enable manual transaction control
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
```

#### Task 2: Implement Atomic Job Claim (~2 hours)

```python
# pulldb/infra/mysql.py - JobRepository

def claim_next_job(self) -> Job | None:
    """Atomically claim next queued job.
    
    Uses SELECT FOR UPDATE SKIP LOCKED to safely claim jobs
    when multiple workers are running.
    
    Returns:
        Claimed job (now in 'running' status) or None if queue empty.
    """
    with self.pool.transaction() as conn:
        cursor = conn.cursor(dictionary=True)
        
        # SELECT with lock - SKIP LOCKED prevents blocking
        cursor.execute("""
            SELECT id, owner_user_id, owner_username, owner_user_code, target,
                   staging_name, dbhost, status, submitted_at, started_at,
                   completed_at, options_json, retry_count, error_detail
            FROM jobs
            WHERE status = 'queued'
            ORDER BY submitted_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        row = cursor.fetchone()
        
        if not row:
            return None
        
        job_id = row['id']
        
        # Update to running within same transaction
        cursor.execute("""
            UPDATE jobs 
            SET status = 'running', started_at = NOW(6)
            WHERE id = %s
        """, (job_id,))
        
        # Commit happens automatically when context manager exits
        return self._row_to_job(row)
```

#### Task 3: Update Worker Loop (~30 min)

```python
# pulldb/worker/loop.py

# Replace:
job = job_repo.get_next_queued_job()
if job:
    job_repo.mark_job_running(job.id)
    job_executor(job)

# With:
job = job_repo.claim_next_job()  # Atomic claim
if job:
    # Job is already marked 'running' - just execute
    job_executor(job)
```

#### Task 4: Add Worker Instance Identification (~1 hour)

Track which worker claimed a job for debugging:

```sql
-- Add worker_id column to jobs table
ALTER TABLE jobs ADD COLUMN claimed_by VARCHAR(64) NULL;
```

```python
# Worker registers itself on startup
import socket
import os

def get_worker_id() -> str:
    hostname = socket.gethostname()
    pid = os.getpid()
    return f"{hostname}:{pid}"
```

#### Task 5: Write Tests (~2 hours)

```python
# tests/test_concurrent_workers.py

def test_concurrent_job_claim():
    """Two workers claiming jobs should not get the same job."""
    # Create 2 queued jobs
    # Simulate concurrent claim from 2 connections
    # Assert each job claimed by exactly one worker

def test_skip_locked_behavior():
    """SKIP LOCKED should not block when job already locked."""
    # Start transaction, lock a job with FOR UPDATE
    # In separate connection, claim should skip locked job
    # Assert second claim returns different job or None

def test_empty_queue_no_block():
    """Empty queue should return immediately, not block."""
    # Measure time for claim_next_job on empty queue
    # Assert completes in < 100ms
```

### Migration Steps

1. **Schema**: No changes required (existing jobs table sufficient)
2. **Code**: 
   - Add `transaction()` method to MySQLPool
   - Add `claim_next_job()` method to JobRepository
   - Update worker loop to use `claim_next_job()`
   - Keep `get_next_queued_job()` for backward compatibility (tests, status queries)
3. **Deployment**: 
   - Deploy updated code
   - Can now safely run multiple `pulldb-worker` instances

### Rollout Strategy

**Phase 3a** (Single Worker - Validation):
1. Deploy new code with `claim_next_job()`
2. Run single worker, verify behavior unchanged
3. Monitor for transaction issues

**Phase 3b** (Dual Worker - Testing):
1. Start second worker on same host
2. Submit burst of test jobs
3. Verify no duplicate processing
4. Monitor queue drain rate

**Phase 3c** (Production Scale):
1. Add workers based on restore demand
2. Document recommended worker count per host
3. Add worker_id to logs for debugging

## Success Criteria

- [ ] Multiple workers can run concurrently without claiming same job
- [ ] `SKIP LOCKED` prevents worker blocking
- [ ] Queue FIFO order maintained (first-submitted processed first)
- [ ] Worker logs identify which instance processed each job
- [ ] No additional infrastructure dependencies
- [ ] Tests cover concurrent claim scenarios
- [ ] Documentation updated for multi-worker deployment

## Testing Matrix

| Scenario | Expected Behavior |
|----------|------------------|
| 1 worker, 1 job | Job claimed and processed normally |
| 2 workers, 1 job | Only one worker claims job, other gets None |
| 2 workers, 2 jobs | Each worker claims different job |
| Worker crashes mid-job | Job stays 'running' (orphan cleanup handles this) |
| DB connection lost during claim | Transaction rolls back, no partial state |
| Empty queue | `claim_next_job()` returns None immediately |

## Future Considerations (Phase 4+)

- **Heartbeats**: Workers could periodically update `last_heartbeat` to detect dead workers
- **Stale Job Recovery**: Background process to reset 'running' jobs with no heartbeat
- **Worker Registration Table**: Track active workers for monitoring dashboard
- **Priority Lanes**: High-priority queue for urgent restores

## References

- MySQL 8.0 `FOR UPDATE SKIP LOCKED`: https://dev.mysql.com/doc/refman/8.0/en/innodb-locking-reads.html
- Job Queue Pattern: https://www.2ndquadrant.com/en/blog/what-is-select-skip-locked-for-in-postgresql-9-5/
- Current schema: `docs/mysql-schema.md`
