"""Domain-level job enqueue service.

Extracted from ``pulldb/api/logic.py`` to allow both the API and Web
pages-layer packages to share enqueue logic without violating HCA
Law 4 (Layer Isolation).  HTTP-specific concerns (``HTTPException``)
are replaced by :class:`~pulldb.domain.errors.EnqueueError`; the
calling pages-layer code converts those to the appropriate HTTP response.

HCA Layer: features (pulldb/worker/)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from pulldb.domain.errors import (
    DatabaseProtectionError,
    DuplicateJobError,
    EnqueueBackupNotFoundError,
    EnqueueError,
    EnqueueValidationError,
    HostUnavailableError,
    HostUnauthorizedError,
    JobLockedError,
    JobNotFoundError,
    RateLimitError,
    StagingError,
    UserDisabledError,
)
from pulldb.domain.models import Job, JobStatus, User
from pulldb.domain.naming import generate_staging_name, normalize_customer_name
from pulldb.domain.schemas import JobRequest
from pulldb.infra.factory import is_simulation_mode
from pulldb.infra.metrics import MetricLabels, emit_counter, emit_event

if TYPE_CHECKING:
    from pulldb.domain.config import Config
    from pulldb.domain.interfaces import (
        AuditRepository,
        HostRepository,
        JobRepository,
        SettingsRepository,
        UserRepository,
    )

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol — what the enqueue service needs from its caller
# ---------------------------------------------------------------------------

class EnqueueDeps(Protocol):
    """Dependencies required by the enqueue service.

    ``APIState`` (a NamedTuple built from domain interfaces) satisfies
    this protocol through structural subtyping.
    """

    @property
    def config(self) -> Config: ...  # type: ignore[override]

    @property
    def user_repo(self) -> UserRepository: ...  # type: ignore[override]

    @property
    def job_repo(self) -> JobRepository: ...  # type: ignore[override]

    @property
    def settings_repo(self) -> SettingsRepository: ...  # type: ignore[override]

    @property
    def host_repo(self) -> HostRepository: ...  # type: ignore[override]

    @property
    def audit_repo(self) -> AuditRepository | None: ...  # type: ignore[override]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TargetResult:
    """Result of target database name construction.

    Tracks whether customer name normalization was applied.

    Attributes:
        target: Final resolved target database name.
        original_customer: Customer name before normalization, if provided.
        normalized_customer: Customer name after normalization, if applied.
        was_normalized: True if normalization changed the customer name.
        normalization_message: Human-readable message about normalization.
        custom_target_used: True if user provided explicit target name.
    """

    target: str
    original_customer: str | None
    normalized_customer: str | None
    was_normalized: bool
    normalization_message: str
    custom_target_used: bool = False


@dataclass(frozen=True)
class EnqueueResult:
    """Result of a successful ``enqueue_job`` call.

    Pages-layer code uses this to construct HTTP responses.
    """

    job: Job
    target_result: TargetResult


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _letters_only(value: str) -> str:
    """Return lowercase letters-only subset of *value*."""
    return "".join(ch for ch in value.lower() if ch.isalpha())


def _is_known_customer_name(name: str) -> bool:
    """Check if a name matches a known customer in S3.

    Used to prevent users from accidentally using customer names
    as custom targets, which could cause confusion.
    """
    try:
        from pulldb.worker.discovery import DiscoveryService

        service = DiscoveryService()
        results = service.search_customers(name, limit=10)
        name_lower = name.lower()
        return any(r.lower() == name_lower for r in results)
    except Exception:
        logger.debug("Customer search failed for '%s', allowing name", name, exc_info=True)
        return False


def _select_dbhost(state: EnqueueDeps, req: JobRequest, user: User) -> str:
    """Select database host for job, with alias resolution."""
    if req.dbhost:
        resolved = state.host_repo.resolve_hostname(req.dbhost)
        if resolved:
            return str(resolved)
        return req.dbhost
    if user.default_host:
        return user.default_host
    if state.config.default_dbhost:
        return state.config.default_dbhost
    return state.config.mysql_host


def _construct_target(user: User, req: JobRequest) -> TargetResult:
    """Construct target database name from user code and customer/qatemplate.

    Target names MUST be lowercase letters only (a-z).
    """
    if req.custom_target:
        custom = req.custom_target.lower()

        if not custom.isalpha():
            raise EnqueueValidationError(
                "Custom target database name must contain only lowercase letters (a-z).",
            )

        if len(custom) < 1:
            raise EnqueueValidationError(
                "Custom target database name must be at least 1 character.",
            )

        if len(custom) > 51:
            raise EnqueueValidationError(
                "Custom target database name exceeds maximum length of 51 characters.",
            )

        if _is_known_customer_name(custom):
            raise EnqueueValidationError(
                f"Cannot use '{custom}' as a custom target name because it matches "
                f"a known customer. Choose a different name to avoid confusion.",
            )

        return TargetResult(
            target=custom,
            original_customer=None,
            normalized_customer=None,
            was_normalized=False,
            normalization_message="",
            custom_target_used=True,
        )

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
        raise EnqueueValidationError(
            f"Customer identifier must include at least one alphabetic character. "
            f"Received '{customer_value}'.",
        )

    norm_result = normalize_customer_name(sanitized)
    customer_for_target = norm_result.normalized

    target = f"{user.user_code}{customer_for_target}"

    if req.suffix:
        target = f"{target}{req.suffix}"

    if not target.isalpha() or not target.islower():
        raise EnqueueValidationError(
            f"Target database name must contain only lowercase letters (a-z). "
            f"Generated target '{target}' contains invalid characters.",
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
    state: EnqueueDeps,
    dbhost: str,
) -> dict[str, str]:
    """Create options snapshot with all job parameters for self-contained execution."""
    from pulldb.domain.config import find_location_for_backup_path, parse_backup_path
    from pulldb.worker.discovery import DiscoveryService

    opts: dict[str, str] = {
        "customer_id": req.customer or "",
        "is_qatemplate": str(req.qatemplate).lower(),
        "overwrite": str(req.overwrite).lower(),
        "api_version": "v2",
    }
    if req.date:
        opts["date"] = req.date
    if req.env:
        opts["env"] = req.env

    if req.custom_target:
        opts["custom_target_used"] = "true"

    # Resolve backup_path: use provided or auto-discover
    backup_path = req.backup_path
    if not backup_path:
        customer_to_search = req.customer if req.customer else "qatemplate"
        env_to_search = req.env if req.env else "both"

        date_from = None
        if req.date:
            date_from = req.date.replace("-", "")

        try:
            service = DiscoveryService()
            result = service.search_backups(
                customer=customer_to_search,
                environment=env_to_search,
                date_from=date_from,
                limit=100,
                offset=0,
            )

            if not result.backups:
                raise EnqueueBackupNotFoundError(
                    f"No backups found for '{customer_to_search}'. "
                    f"Use 'pulldb list {customer_to_search}' to see available backups.",
                )

            selected_backup = None
            if req.date:
                date_str = req.date.replace("-", "")
                for backup in result.backups:
                    if backup.date == date_str:
                        selected_backup = backup
                        break
                if not selected_backup:
                    available_dates = sorted(set(b.date for b in result.backups), reverse=True)[:5]
                    raise EnqueueBackupNotFoundError(
                        f"No backup found for '{customer_to_search}' on date {req.date}. "
                        f"Available dates: {', '.join(available_dates)}. "
                        f"Use 'pulldb list {customer_to_search}' to see all available backups.",
                    )
            else:
                selected_backup = result.backups[0]

            backup_path = f"s3://{selected_backup.bucket}/{selected_backup.key}"

        except EnqueueError:
            raise
        except Exception as exc:
            raise EnqueueBackupNotFoundError(
                f"Failed to discover backup for '{customer_to_search}': {exc}",
            ) from exc

    if backup_path:
        opts["backup_path"] = backup_path

        parsed = parse_backup_path(backup_path)
        if parsed:
            bucket, key = parsed
            opts["s3_bucket"] = bucket
            opts["s3_key"] = key

        location = find_location_for_backup_path(
            backup_path,
            state.config.s3_backup_locations,
        )
        if location:
            opts["s3_location_name"] = location.name
            opts["s3_prefix"] = location.prefix
            if location.profile:
                opts["s3_profile"] = location.profile

    if state.host_repo and dbhost:
        try:
            creds = state.host_repo.get_host_credentials(dbhost)
            if creds:
                opts["resolved_mysql_host"] = creds.host
                if creds.port and creds.port != 3306:
                    opts["resolved_mysql_port"] = str(creds.port)
        except Exception:
            logger.debug("Failed to resolve MySQL host for '%s'", dbhost, exc_info=True)

    if state.config:
        opts["myloader_path"] = state.config.myloader_binary

        if req.qatemplate:
            opts["post_sql_dir"] = str(state.config.qa_template_after_sql_dir)
        else:
            opts["post_sql_dir"] = str(state.config.customers_after_sql_dir)

    return opts


# ---------------------------------------------------------------------------
# Public validation / capacity helpers
# ---------------------------------------------------------------------------

def validate_job_request(req: JobRequest) -> None:
    """Validate that exactly one of customer or qatemplate is specified."""
    if bool(req.customer) == bool(req.qatemplate):
        raise EnqueueValidationError(
            "Must specify exactly one of customer or qatemplate for restore request.",
        )


def check_host_active_capacity(state: EnqueueDeps, hostname: str) -> None:
    """Check if host has capacity for more active jobs.

    Raises:
        EnqueueError: 429 if host at capacity.
    """
    if not state.host_repo.check_host_active_capacity(hostname):
        host = state.host_repo.get_host_by_hostname(hostname)
        max_active = host.max_active_jobs if host else 0

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
            raise RateLimitError(
                f"Host '{hostname}' is frozen (queue disabled). No new jobs accepted.",
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
        raise RateLimitError(
            f"Host '{hostname}' has {active_count} active jobs (limit: {max_active}). "
            "Please wait for a job to finish or choose another host.",
        )


def check_concurrency_limits(state: EnqueueDeps, user: User) -> None:
    """Check concurrency limits before enqueueing a job.

    Raises:
        EnqueueError: 429 if limit exceeded.
    """
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
            raise RateLimitError(
                f"System at capacity: {global_active} active jobs "
                f"(limit: {global_limit}). Please try again later.",
            )

    if user.max_active_jobs is not None:
        per_user_limit = user.max_active_jobs
    else:
        per_user_limit = state.settings_repo.get_max_active_jobs_per_user()

    if per_user_limit > 0:
        user_active = state.job_repo.count_active_jobs_for_user(user.user_id)
        if user_active >= per_user_limit:
            emit_event(
                "job_enqueue_rejected",
                f"User limit reached for {user.username}: {user_active}/{per_user_limit}",
                labels=MetricLabels(
                    target="",
                    phase="enqueue",
                    status="rate_limited",
                ),
            )
            raise RateLimitError(
                f"You have {user_active} active jobs (limit: {per_user_limit}). "
                "Please wait for a job to finish.",
            )


# ---------------------------------------------------------------------------
# Main enqueue entry point
# ---------------------------------------------------------------------------

def enqueue_job(state: EnqueueDeps, req: JobRequest) -> EnqueueResult:
    """Enqueue a new restore job.

    This is the **domain-level** enqueue function.  It raises
    :class:`~pulldb.domain.errors.EnqueueError` on all failure modes.
    Pages-layer code (API routes, web routes) should catch ``EnqueueError``
    and translate to the appropriate HTTP response.

    Args:
        state: Dependency container (satisfied by ``APIState``).
        req: Job submission request.

    Returns:
        An :class:`EnqueueResult` with the stored job and target metadata.

    Raises:
        EnqueueError: On any validation, conflict, or system failure.
    """
    validate_job_request(req)

    # Get user — do NOT auto-create, user must register first
    user = state.user_repo.get_user_by_username(username=req.user)
    if not user:
        raise JobNotFoundError(
            f"User '{req.user}' not found. Use 'pulldb register' to create an account.",
        )

    if user.disabled:
        raise UserDisabledError(
            "Your account is pending approval. Contact an administrator to enable your account.",
        )

    target_result = _construct_target(user, req)
    target = target_result.target
    dbhost = _select_dbhost(state, req, user)

    if not user.can_use_host(dbhost):
        raise HostUnauthorizedError(
            f"You are not authorized to use database host '{dbhost}'. "
            f"Contact an administrator to request access.",
        )

    # Proactive duplicate check
    if state.job_repo.has_active_jobs_for_target(target, dbhost):
        raise DuplicateJobError(
            f"A restore for '{target}' on '{dbhost}' is already in progress. "
            f"This may be a queued, running, or recently-canceled job. "
            f"Please wait for it to complete.",
        )

    # Check if target is locked
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
        raise JobLockedError(
            f"Target '{target}' on '{dbhost}' is locked. "
            f"The database from job {locked_job.id[:8]} is protected from overwrites. "
            f"Unlock it first or use a different target name.",
        )

    # Check deployed database owned by this user
    if hasattr(state.job_repo, "get_deployed_job_for_target"):
        existing_deployed = state.job_repo.get_deployed_job_for_target(target, dbhost, user.user_id)
        if existing_deployed:
            # Claimed/assigned databases cannot be superseded by a restore.
            # They represent externally-managed databases that pullDB tracks
            # but does NOT own. Superseding would orphan the tracking record
            # because the downstream DatabaseProtectionError (no pullDB
            # metadata table) would block the new restore anyway.
            if getattr(existing_deployed, "origin", "restore") in ("claim", "assign"):
                origin_label = "claimed" if existing_deployed.origin == "claim" else "assigned"
                emit_event(
                    "job_enqueue_blocked",
                    f"Restore blocked: database '{target}' on '{dbhost}' is "
                    f"{origin_label} (job {existing_deployed.id[:8]})",
                    labels=MetricLabels(
                        target=target,
                        phase="enqueue",
                        status="blocked_claimed",
                    ),
                )
                raise DatabaseProtectionError(
                    f"Database '{target}' on '{dbhost}' is {origin_label} and tracked "
                    f"by pullDB (job {existing_deployed.id[:8]}). Remove the {origin_label} "
                    f"database from Database Discovery before restoring to this target.",
                )
            if not req.overwrite:
                emit_event(
                    "job_enqueue_blocked",
                    f"Restore blocked: database '{target}' on '{dbhost}' already exists "
                    f"(job {existing_deployed.id[:8]})",
                    labels=MetricLabels(
                        target=target,
                        phase="enqueue",
                        status="blocked",
                    ),
                )
                raise DuplicateJobError(
                    f"Database '{target}' already exists on '{dbhost}' "
                    f"(job {existing_deployed.id[:8]}). "
                    f"Enable 'Allow Overwrite' to replace it, or use a different target name.",
                )
            if not existing_deployed.locked_at:
                state.job_repo.supersede_job(existing_deployed.id, "pending-" + target)
                emit_event(
                    "job_superseded",
                    f"Job {existing_deployed.id[:8]} superseded for target {target} "
                    f"(overwrite enabled)",
                    labels=MetricLabels(
                        job_id=existing_deployed.id,
                        target=target,
                        phase="enqueue",
                        status="superseded",
                    ),
                )

    # ==========================================================================
    # CRITICAL DATABASE PROTECTION — NON-NEGOTIABLE
    # Per .pulldb/standards/database-protection.md
    # ==========================================================================
    db_exists = False
    if is_simulation_mode():
        logger.debug(
            "Simulation mode: skipping database existence check for '%s' on '%s'",
            target, dbhost,
        )
    else:
        try:
            db_exists = state.host_repo.database_exists(dbhost, target)
        except Exception as e:
            logger.error(
                "Database existence check failed for '%s' on '%s': %s",
                target, dbhost, e,
                exc_info=True,
            )
            raise HostUnavailableError(
                f"Cannot verify database safety on '{dbhost}'. "
                f"The target host may be unreachable. Please try again later.",
            ) from e

    if db_exists:
        try:
            has_pulldb, owner_id, owner_code = state.host_repo.get_pulldb_metadata_owner(dbhost, target)
        except Exception:
            logger.debug("Metadata owner check failed for '%s' on '%s'", target, dbhost, exc_info=True)
            has_pulldb, owner_id, owner_code = False, None, None

        if not has_pulldb:
            emit_event(
                "job_enqueue_blocked",
                f"Restore blocked: EXTERNAL database '{target}' on '{dbhost}' detected "
                f"(no pullDB table)",
                labels=MetricLabels(
                    target=target,
                    phase="enqueue",
                    status="blocked_external_db",
                ),
            )
            raise DatabaseProtectionError(
                f"PROTECTED: Database '{target}' exists on '{dbhost}' but is NOT "
                f"pullDB-managed. This appears to be an external database that cannot "
                f"be overwritten. Choose a different target name or manually remove "
                f"the database before restoring.",
            )

        if owner_id and owner_id != user.user_id:
            emit_event(
                "job_enqueue_blocked",
                f"Restore blocked: database '{target}' on '{dbhost}' owned by "
                f"different user ({owner_code})",
                labels=MetricLabels(
                    target=target,
                    phase="enqueue",
                    status="blocked_cross_user",
                ),
            )
            raise DatabaseProtectionError(
                f"PROTECTED: Database '{target}' on '{dbhost}' is owned by user "
                f"'{owner_code}'. You cannot overwrite another user's database. "
                f"Choose a different target name.",
            )

        if not req.overwrite:
            emit_event(
                "job_enqueue_blocked",
                f"Restore blocked: database '{target}' on '{dbhost}' exists "
                f"(overwrite not enabled)",
                labels=MetricLabels(
                    target=target,
                    phase="enqueue",
                    status="blocked_no_overwrite",
                ),
            )
            raise DuplicateJobError(
                f"Database '{target}' already exists on '{dbhost}'. "
                f"Enable 'Allow Overwrite' to replace it, or use a different target name.",
            )

    # Phase 2: Concurrency controls
    check_concurrency_limits(state, user)

    # Phase 3: Per-host capacity check
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
            raise DuplicateJobError(message) from exc
        raise EnqueueValidationError(message) from exc
    except StagingError as exc:
        raise EnqueueValidationError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise EnqueueValidationError(
            f"Failed to enqueue job due to unexpected error: {exc}",
        ) from exc

    # Mark any previous completed job for this target as superseded
    if hasattr(state.job_repo, "get_latest_completed_job_for_target"):
        try:
            previous_job = state.job_repo.get_latest_completed_job_for_target(
                target, dbhost, user.user_id,
            )
            if previous_job and previous_job.id != job_id:
                if not previous_job.locked_at and not previous_job.db_dropped_at:
                    state.job_repo.supersede_job(previous_job.id, job_id)
                    emit_event(
                        "job_superseded",
                        f"Job {previous_job.id[:8]} superseded by {job_id[:8]} "
                        f"for target {target}",
                        labels=MetricLabels(
                            job_id=previous_job.id,
                            target=target,
                            phase="enqueue",
                            status="superseded",
                        ),
                    )
        except Exception:
            logger.debug("Job supersession failed for target '%s'", target, exc_info=True)

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

    return EnqueueResult(job=stored, target_result=target_result)
