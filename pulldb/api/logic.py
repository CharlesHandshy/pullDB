"""Business logic for pullDB API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status

from pulldb.api.schemas import JobRequest, JobResponse
from pulldb.api.types import APIState
from pulldb.domain.errors import StagingError
from pulldb.domain.models import Job, JobStatus, User
from pulldb.domain.naming import normalize_customer_name
from pulldb.domain.services.discovery import DiscoveryService
from pulldb.infra.metrics import MetricLabels, emit_counter, emit_event
from pulldb.worker.staging import generate_staging_name


@dataclass(frozen=True)
class TargetResult:
    """Result of target database name construction.
    
    Tracks whether customer name normalization was applied.
    """
    target: str
    original_customer: str | None
    normalized_customer: str | None
    was_normalized: bool
    normalization_message: str
    custom_target_used: bool = False


def _letters_only(value: str) -> str:
    """Return lowercase letters-only subset of *value*."""
    return "".join(ch for ch in value.lower() if ch.isalpha())


def _is_known_customer_name(name: str) -> bool:
    """Check if a name matches a known customer in S3.
    
    Used to prevent users from accidentally using customer names
    as custom targets, which could cause confusion.
    
    Args:
        name: The proposed target name to check.
        
    Returns:
        True if the name exactly matches a known customer.
    """
    try:
        service = DiscoveryService()
        # Search for exact match - use the name as query
        results = service.search_customers(name, limit=10)
        # Check if any result is an exact match
        name_lower = name.lower()
        return any(r.lower() == name_lower for r in results)
    except Exception:
        # If search fails, allow the name (fail open for UX)
        return False


def _target_database_exists_on_host(
    state: APIState,
    target: str,
    dbhost: str,
) -> bool:
    """Check if a target database exists on the specified host.
    
    Uses host_repo to resolve credentials and queries SHOW DATABASES.
    
    Args:
        state: API state with host_repo.
        target: Target database name to check.
        dbhost: Hostname to query.
        
    Returns:
        True if database exists on host, False otherwise.
        Returns False on connection/query errors (fail safe for UX).
    """
    import mysql.connector
    
    try:
        creds = state.host_repo.get_host_credentials(dbhost)
        conn = mysql.connector.connect(
            host=creds.host,
            port=creds.port,
            user=creds.username,
            password=creds.password,
            connect_timeout=10,
        )
        cursor = conn.cursor()
        cursor.execute("SHOW DATABASES LIKE %s", (target,))
        exists = cursor.fetchone() is not None
        cursor.close()
        conn.close()
        return exists
    except Exception:
        # Fail safe - if we can't check, allow the operation
        return False


def _get_pulldb_metadata_owner(
    state: APIState,
    target: str,
    dbhost: str,
) -> tuple[bool, str | None, str | None]:
    """Check if target database has pullDB metadata table and get owner.
    
    Args:
        state: API state with host_repo.
        target: Target database name to check.
        dbhost: Hostname to query.
        
    Returns:
        Tuple of (has_pulldb_table, owner_user_id, owner_user_code).
        If no pullDB table exists: (False, None, None).
        If pullDB table exists but uses old schema (no owner columns): (True, None, None).
        On connection errors: (False, None, None) (fail safe).
    """
    import mysql.connector
    
    try:
        creds = state.host_repo.get_host_credentials(dbhost)
        conn = mysql.connector.connect(
            host=creds.host,
            port=creds.port,
            user=creds.username,
            password=creds.password,
            database=target,
            connect_timeout=10,
        )
        cursor = conn.cursor()
        
        # Check if pullDB table exists
        cursor.execute("SHOW TABLES LIKE 'pullDB'")
        if cursor.fetchone() is None:
            cursor.close()
            conn.close()
            return (False, None, None)
        
        # pullDB table exists - check if it has owner columns (new schema)
        cursor.execute("SHOW COLUMNS FROM `pullDB` LIKE 'owner_user_id'")
        has_owner_columns = cursor.fetchone() is not None
        
        if not has_owner_columns:
            # Old schema - table exists but no owner tracking
            # This is still a pullDB-managed database, just from before ownership feature
            cursor.close()
            conn.close()
            return (True, None, None)
        
        # Get owner info from the most recent entry
        cursor.execute(
            "SELECT owner_user_id, owner_user_code FROM `pullDB` "
            "ORDER BY restored_at DESC LIMIT 1"
        )
        row: tuple | None = cursor.fetchone()  # type: ignore[assignment]
        cursor.close()
        conn.close()
        
        if row:
            owner_user_id = str(row[0]) if row[0] else None
            owner_user_code = str(row[1]) if row[1] else None
            return (True, owner_user_id, owner_user_code)
        return (True, None, None)  # Table exists but empty
        
    except Exception:
        # Fail safe - if we can't check, assume no table (external DB)
        return (False, None, None)


def _select_dbhost(state: APIState, req: JobRequest, user: User) -> str:
    """Select database host for job, using user's default if not specified.

    Priority:
    1. Explicitly requested host (req.dbhost) - resolved via alias if needed
    2. User's configured default_host
    3. System default_dbhost from config
    4. mysql_host from config (fallback)
    
    Host resolution:
    - If a host alias is provided, it's resolved to the canonical hostname
    - If hostname is provided directly, it's used as-is
    """
    if req.dbhost:
        # Resolve alias to hostname if needed
        resolved = state.host_repo.resolve_hostname(req.dbhost)
        if resolved:
            return str(resolved)
        # Not found - return as-is, will fail later in validation
        return req.dbhost
    if user.default_host:
        return user.default_host
    if state.config.default_dbhost:
        return state.config.default_dbhost
    return state.config.mysql_host


def _construct_target(user: User, req: JobRequest) -> TargetResult:
    """Construct target database name from user code and customer/qatemplate.
    
    Target names MUST be lowercase letters only (a-z). No numbers, no special
    characters, no underscores. This is a hard requirement enforced at:
    - API level (this function)
    - CLI level (parse.py validation)
    - Web UI level (JavaScript validation + input filtering)
    
    If custom_target is provided, use it directly (user has FULL control).
    Auto-generated targets still use {user_code}{customer}{suffix} pattern.
    
    Long customer names (> 42 chars) are automatically normalized via
    truncation + hash suffix to ensure unique, reproducible targets.
    
    Returns:
        TargetResult with target name and normalization metadata.
    """
    # Handle custom target override - user has FULL control (1-51 lowercase letters)
    if req.custom_target:
        custom = req.custom_target.lower()
        
        # Validate format: lowercase letters only, 1-51 chars
        if not custom.isalpha():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Custom target database name must contain only lowercase letters (a-z).",
            )
        
        if len(custom) < 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Custom target database name must be at least 1 character.",
            )
        
        if len(custom) > 51:  # MAX_TARGET_LEN from staging.py constants
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Custom target database name exceeds maximum length of 51 characters.",
            )
        
        # Block customer names as custom targets to prevent confusion
        if _is_known_customer_name(custom):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot use '{custom}' as a custom target name because it matches "
                    f"a known customer. Choose a different name to avoid confusion."
                ),
            )
        
        return TargetResult(
            target=custom,
            original_customer=None,
            normalized_customer=None,
            was_normalized=False,
            normalization_message="",
            custom_target_used=True,
        )
    
    # Auto-generation: {user_code}{customer}{suffix} pattern
    if req.qatemplate:
        target = f"{user.user_code}qatemplate"
        if req.suffix:
            target = f"{target}{req.suffix}"
        return TargetResult(
            target=target,
            original_customer=None,
            normalized_customer=None,
            was_normalized=False,
            normalization_message="",
            custom_target_used=False,
        )

    customer_value = req.customer or ""
    sanitized = _letters_only(customer_value)
    if not sanitized:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Customer identifier must include at least one alphabetic character. "
                f"Received '{customer_value}'."
            ),
        )
    
    # Normalize long customer names
    norm_result = normalize_customer_name(sanitized)
    customer_for_target = norm_result.normalized
    
    target = f"{user.user_code}{customer_for_target}"
    
    # Append optional suffix if provided
    if req.suffix:
        target = f"{target}{req.suffix}"
    
    # Final validation: target must be lowercase letters only
    if not target.isalpha() or not target.islower():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Target database name must contain only lowercase letters (a-z). "
                f"Generated target '{target}' contains invalid characters."
            ),
        )
    
    return TargetResult(
        target=target,
        original_customer=norm_result.original if norm_result.was_normalized else None,
        normalized_customer=norm_result.normalized if norm_result.was_normalized else None,
        was_normalized=norm_result.was_normalized,
        normalization_message=norm_result.display_message,
        custom_target_used=False,
    )


def _options_snapshot(
    req: JobRequest,
    state: APIState,
    dbhost: str,
) -> dict[str, str]:
    """Create options snapshot with all job parameters for self-contained execution.

    Captures everything needed to execute the restore job:
    - Original request parameters (customer, qatemplate, overwrite, etc.)
    - Resolved backup path and S3 location info
    - Resolved MySQL host endpoint
    - Execution config (myloader path, post-SQL directory)

    This ensures jobs are self-contained and don't depend on external state
    that could change between submission and execution.

    Args:
        req: The job request with user inputs.
        state: API state with config and repositories.
        dbhost: Resolved database host for this job.

    Returns:
        Dictionary of options to store in job.options_json.
        
    Raises:
        HTTPException: If backup discovery fails when backup_path not provided.
    """
    from pulldb.domain.config import find_location_for_backup_path, parse_backup_path
    from pulldb.domain.services.discovery import DiscoveryService

    opts: dict[str, str] = {
        "customer_id": req.customer or "",
        "is_qatemplate": str(req.qatemplate).lower(),
        "overwrite": str(req.overwrite).lower(),
        "api_version": "v2",  # Bumped version for new self-contained format
    }
    if req.date:
        opts["date"] = req.date
    if req.env:
        opts["env"] = req.env
    
    # Track if custom target was used (for audit trail)
    if req.custom_target:
        opts["custom_target_used"] = "true"

    # Resolve backup_path: use provided or auto-discover
    backup_path = req.backup_path
    if not backup_path:
        # Auto-discover backup from customer/qatemplate + optional date
        customer_to_search = req.customer if req.customer else "qatemplate"
        env_to_search = req.env if req.env else "both"
        
        # Use date filter if provided (convert YYYY-MM-DD to YYYYMMDD)
        date_from = None
        if req.date:
            date_from = req.date.replace("-", "")
        
        try:
            service = DiscoveryService()
            # Search for backups, get only the most recent matching one
            result = service.search_backups(
                customer=customer_to_search,
                environment=env_to_search,
                date_from=date_from,
                limit=100,  # Get enough to find exact date match
                offset=0,
            )
            
            if not result.backups:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    detail=f"No backups found for '{customer_to_search}'. "
                           f"Use 'pulldb list {customer_to_search}' to see available backups."
                )
            
            # If date specified, find exact match; otherwise use latest
            selected_backup = None
            if req.date:
                # Find backup matching the requested date
                date_str = req.date.replace("-", "")
                for backup in result.backups:
                    if backup.date == date_str:
                        selected_backup = backup
                        break
                if not selected_backup:
                    available_dates = sorted(set(b.date for b in result.backups), reverse=True)[:5]
                    raise HTTPException(
                        status.HTTP_404_NOT_FOUND,
                        detail=f"No backup found for '{customer_to_search}' on date {req.date}. "
                               f"Available dates: {', '.join(available_dates)}. "
                               f"Use 'pulldb list {customer_to_search}' to see all available backups."
                    )
            else:
                # Use latest backup
                selected_backup = result.backups[0]
            
            # Construct full S3 path
            backup_path = f"s3://{selected_backup.bucket}/{selected_backup.key}"
            
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to discover backup for '{customer_to_search}': {exc}"
            ) from exc

    # Snapshot backup path and S3 location info
    if backup_path:
        opts["backup_path"] = backup_path

        # Parse backup path to extract bucket/key
        parsed = parse_backup_path(backup_path)
        if parsed:
            bucket, key = parsed
            opts["s3_bucket"] = bucket
            opts["s3_key"] = key

        # Find matching S3 location config
        location = find_location_for_backup_path(
            backup_path,
            state.config.s3_backup_locations,
        )
        if location:
            opts["s3_location_name"] = location.name
            opts["s3_prefix"] = location.prefix
            if location.profile:
                opts["s3_profile"] = location.profile

    # Snapshot resolved MySQL host endpoint
    if state.host_repo and dbhost:
        try:
            creds = state.host_repo.get_host_credentials(dbhost)
            if creds:
                opts["resolved_mysql_host"] = creds.host
                if creds.port and creds.port != 3306:
                    opts["resolved_mysql_port"] = str(creds.port)
        except Exception:
            pass  # Best effort - don't fail job submission if resolution fails

    # Snapshot execution config
    if state.config:
        opts["myloader_path"] = state.config.myloader_binary

        # Resolve post-SQL directory based on qatemplate flag
        if req.qatemplate:
            opts["post_sql_dir"] = str(state.config.qa_template_after_sql_dir)
        else:
            opts["post_sql_dir"] = str(state.config.customers_after_sql_dir)

    return opts


def validate_job_request(req: JobRequest) -> None:
    """Validate that exactly one of customer or qatemplate is specified."""
    if bool(req.customer) == bool(req.qatemplate):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "Must specify exactly one of customer or qatemplate for "
                "restore request."
            ),
        )


def check_host_active_capacity(state: APIState, hostname: str) -> None:
    """Check if host has capacity for more active jobs.

    Enforces per-host active job limit (queued + running).

    Args:
        state: API state with repositories.
        hostname: Database host to check.

    Raises:
        HTTPException: 429 Too Many Requests if host at capacity.
    """
    if not state.host_repo.check_host_active_capacity(hostname):
        host = state.host_repo.get_host_by_hostname(hostname)
        max_active = host.max_active_jobs if host else 0
        
        # Frozen host (max_active_jobs = 0) gets a specific message
        if max_active == 0:
            emit_event(
                "job_enqueue_rejected",
                f"Host frozen for {hostname}: queue disabled (max_active_jobs=0)",
                labels=MetricLabels(
                    target="",
                    phase="enqueue",
                    status="frozen",
                ),
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Host '{hostname}' is frozen (queue disabled). No new jobs accepted.",
            )
        
        active_count = state.job_repo.count_active_jobs_for_host(hostname)
        emit_event(
            "job_enqueue_rejected",
            f"Host capacity reached for {hostname}: {active_count}/{max_active} active jobs",
            labels=MetricLabels(
                target="",
                phase="enqueue",
                status="rate_limited",
            ),
        )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Host '{hostname}' has {active_count} active jobs (limit: {max_active}). "
                "Please wait for a job to finish or choose another host."
            ),
        )


def check_concurrency_limits(state: APIState, user: User) -> None:
    """Check concurrency limits before enqueueing a job.

    Enforces per-user and global active job limits. A limit of 0 means unlimited.

    Args:
        state: API state with repositories.
        user: User attempting to enqueue a job.

    Raises:
        HTTPException: 429 Too Many Requests if limit exceeded.
    """
    # Check global limit first (higher priority)
    global_limit = state.settings_repo.get_max_active_jobs_global()
    if global_limit > 0:
        global_active = state.job_repo.count_all_active_jobs()
        if global_active >= global_limit:
            emit_event(
                "job_enqueue_rejected",
                f"Global limit reached: {global_active}/{global_limit} active jobs",
                labels=MetricLabels(
                    target="",
                    phase="enqueue",
                    status="rate_limited",
                ),
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"System at capacity: {global_active} active jobs "
                    f"(limit: {global_limit}). Please try again later."
                ),
            )

    # Check per-user limit (user-specific overrides system default)
    # NULL = use system default, 0 = unlimited, N > 0 = specific limit
    if user.max_active_jobs is not None:
        per_user_limit = user.max_active_jobs
    else:
        per_user_limit = state.settings_repo.get_max_active_jobs_per_user()
    
    if per_user_limit > 0:
        user_active = state.job_repo.count_active_jobs_for_user(user.user_id)
        if user_active >= per_user_limit:
            emit_event(
                "job_enqueue_rejected",
                (
                    f"User limit reached for {user.username}: "
                    f"{user_active}/{per_user_limit}"
                ),
                labels=MetricLabels(
                    target="",
                    phase="enqueue",
                    status="rate_limited",
                ),
            )
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"You have {user_active} active jobs (limit: {per_user_limit}). "
                    "Please wait for a job to finish."
                ),
            )


def enqueue_job(state: APIState, req: JobRequest) -> JobResponse:
    """Enqueue a new restore job."""
    validate_job_request(req)

    # Get user - do NOT auto-create, user must register first
    user = state.user_repo.get_user_by_username(username=req.user)
    if not user:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"User '{req.user}' not found. Use 'pulldb register' to create an account.",
        )

    # Check if user is disabled (pending admin approval)
    if user.disabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Your account is pending approval. Contact an administrator to enable your account.",
        )

    target_result = _construct_target(user, req)
    target = target_result.target
    dbhost = _select_dbhost(state, req, user)  # Pass user for default_host

    # Validate user can use the selected host
    if not user.can_use_host(dbhost):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"You are not authorized to use database host '{dbhost}'. "
                   f"Contact an administrator to request access."
        )

    # Proactive duplicate check - fail fast with clear message
    # Also blocks if a recently-canceled job may still have myloader running
    if state.job_repo.has_active_jobs_for_target(target, dbhost):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"A restore for '{target}' on '{dbhost}' is already in progress. "
                   f"This may be a queued, running, or recently-canceled job. "
                   f"Please wait for it to complete."
        )

    # Check if target is locked (prevents overwrites until unlocked)
    locked_job = state.job_repo.get_locked_by_target(target, dbhost, user.user_id)
    if locked_job:
        emit_event(
            "job_enqueue_blocked",
            f"Restore blocked: target '{target}' on '{dbhost}' is locked (job {locked_job.id[:8]})",
            labels=MetricLabels(
                target=target,
                phase="enqueue",
                status="blocked",
            ),
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Target '{target}' on '{dbhost}' is locked. "
                   f"The database from job {locked_job.id[:8]} is protected from overwrites. "
                   f"Unlock it first or use a different target name."
        )

    # CRITICAL: Check if a deployed database already exists for this target
    # If overwrite is not explicitly enabled, block the restore to prevent data loss
    if hasattr(state.job_repo, "get_deployed_job_for_target"):
        existing_deployed = state.job_repo.get_deployed_job_for_target(target, dbhost, user.user_id)
        if existing_deployed:
            if not req.overwrite:
                emit_event(
                    "job_enqueue_blocked",
                    f"Restore blocked: database '{target}' on '{dbhost}' already exists (job {existing_deployed.id[:8]})",
                    labels=MetricLabels(
                        target=target,
                        phase="enqueue",
                        status="blocked",
                    ),
                )
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail=f"Database '{target}' already exists on '{dbhost}' (job {existing_deployed.id[:8]}). "
                           f"Enable 'Allow Overwrite' to replace it, or use a different target name."
                )
            # Overwrite is enabled - supersede the existing deployed job
            if not existing_deployed.locked_at:
                state.job_repo.supersede_job(existing_deployed.id, "pending-" + target)
                emit_event(
                    "job_superseded",
                    f"Job {existing_deployed.id[:8]} superseded for target {target} (overwrite enabled)",
                    labels=MetricLabels(
                        job_id=existing_deployed.id,
                        target=target,
                        phase="enqueue",
                        status="superseded",
                    ),
                )

    # CRITICAL: External database protection
    # If overwrite is enabled, verify the target is either:
    # 1. Non-existent (safe to create)
    # 2. pullDB-managed AND owned by this user (safe to overwrite)
    # External databases (no pullDB table) MUST NEVER be overwritten
    if req.overwrite and _target_database_exists_on_host(state, target, dbhost):
        has_pulldb, owner_id, owner_code = _get_pulldb_metadata_owner(state, target, dbhost)
        
        if not has_pulldb:
            # External database - NEVER overwrite
            emit_event(
                "job_enqueue_blocked",
                f"Restore blocked: external database '{target}' on '{dbhost}' detected (no pullDB table)",
                labels=MetricLabels(
                    target=target,
                    phase="enqueue",
                    status="blocked",
                ),
            )
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"Database '{target}' exists but is not pullDB-managed (no metadata table). "
                    f"Choose a different target name or manually remove the database before restoring."
                ),
            )
        
        # pullDB-managed but owned by different user
        if owner_id and owner_id != user.user_id:
            emit_event(
                "job_enqueue_blocked",
                f"Restore blocked: database '{target}' on '{dbhost}' owned by different user ({owner_code})",
                labels=MetricLabels(
                    target=target,
                    phase="enqueue",
                    status="blocked",
                ),
            )
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    f"Database '{target}' on '{dbhost}' is owned by user '{owner_code}'. "
                    f"You cannot overwrite another user's database. "
                    f"Choose a different target name."
                ),
            )

    # Phase 2: Concurrency controls - check limits before job creation
    check_concurrency_limits(state, user)
    
    # Phase 3: Per-host capacity check - ensure host can accept more jobs
    check_host_active_capacity(state, dbhost)

    job_id = str(uuid.uuid4())
    staging_name = generate_staging_name(target, job_id)

    job = Job(
        id=job_id,
        owner_user_id=user.user_id,
        owner_username=user.username,
        owner_user_code=user.user_code,
        target=target,
        staging_name=staging_name,
        dbhost=dbhost,
        status=JobStatus.QUEUED,
        submitted_at=datetime.now(UTC),
        options_json=_options_snapshot(req, state, dbhost),
        retry_count=0,
        custom_target=target_result.custom_target_used,
    )

    try:
        state.job_repo.enqueue_job(job)
    except ValueError as exc:
        message = str(exc)
        if "already has an active job" in message:
            emit_event(
                "job_enqueue_conflict",
                message,
                labels=MetricLabels(
                    job_id=job_id,
                    target=target,
                    phase="enqueue",
                    status="conflict",
                ),
            )
            raise HTTPException(status.HTTP_409_CONFLICT, detail=message) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=message) from exc
    except StagingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - MySQL errors surfaced as 500
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue job due to unexpected error: {exc}",
        ) from exc

    # Mark any previous completed job for this target as superseded
    # This allows retention cleanup to know which jobs have been replaced
    if hasattr(state.job_repo, "get_latest_completed_job_for_target"):
        try:
            previous_job = state.job_repo.get_latest_completed_job_for_target(
                target, dbhost, user.user_id
            )
            if previous_job and previous_job.id != job_id:
                # Only supersede if not locked and not already dropped
                if not previous_job.locked_at and not previous_job.db_dropped_at:
                    state.job_repo.supersede_job(previous_job.id, job_id)
                    emit_event(
                        "job_superseded",
                        f"Job {previous_job.id[:8]} superseded by {job_id[:8]} for target {target}",
                        labels=MetricLabels(
                            job_id=previous_job.id,
                            target=target,
                            phase="enqueue",
                            status="superseded",
                        ),
                    )
        except Exception:
            # Supersession is non-critical - don't fail job submission
            pass

    stored = state.job_repo.get_job_by_id(job_id) or job

    emit_counter(
        "jobs_enqueued_total",
        labels=MetricLabels(
            job_id=job_id,
            target=target,
            phase="enqueue",
            status="queued",
        ),
    )

    # Audit log job submission
    if hasattr(state, "audit_repo") and state.audit_repo:
        state.audit_repo.log_action(
            actor_user_id=user.user_id,
            action="job_submitted",
            target_user_id=user.user_id,
            detail=f"Submitted restore job for {target} on {dbhost}",
            context={
                "job_id": job_id,
                "target": target,
                "staging_name": staging_name,
                "dbhost": dbhost,
            },
        )

    return JobResponse(
        job_id=job_id,
        target=target,
        staging_name=stored.staging_name,
        status=stored.status.value,
        owner_username=stored.owner_username,
        owner_user_code=stored.owner_user_code,
        submitted_at=stored.submitted_at,
        original_customer=target_result.original_customer,
        customer_normalized=target_result.was_normalized,
        normalization_message=target_result.normalization_message if target_result.was_normalized else None,
        custom_target_used=target_result.custom_target_used,
    )
