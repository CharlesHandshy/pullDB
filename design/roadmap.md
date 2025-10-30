# Roadmap (Documentation-First)

> **Governance**: All feature additions must align with principles in `../.github/copilot-instructions.md` and `../constitution.md`. Update those documents first if architectural changes are needed.

This roadmap records deferred features and the documentation prerequisites before implementation begins. Always update this file before expanding scope.

## Phase 0 – Prototype (Current)

- CLI enqueue + status command.
- Daemon polling, download, restore, post-restore SQL execution, logging, metrics.
- MySQL schema as defined in `../docs/mysql-schema.md`.
- Authentication via trusted wrapper (sudo context).

## Phase 1 – Operational Enhancements

- **Cancellation Support**
  - Documentation: update README, schema notes, runbooks, security considerations.
  - Design work: sequence diagram covering cancel lifecycle, failure handling.
- **History Endpoint**
  - Documentation: define API output, retention policy, and new diagrams.
  - Schema: enable `history_cache` materialization; document migration steps.
- **Job Logs Table**
  - Document expected volume, log format, and pruning approach.
- **Scheduled Staging Database Cleanup**
  - Background task to clean up truly abandoned staging databases (7+ days old).
  - Query failed jobs and scan each dbhost for orphaned staging databases.
  - Configurable age threshold (default 7 days) via `settings` table.
  - Safety checks: verify no active jobs for that target before deletion.
  - Audit logging: track all automatic deletions in job_events or dedicated cleanup_log table.
  - Metrics: count of staging databases cleaned, total size reclaimed.
  - Documentation: cron schedule, safety guarantees, manual override procedures.
  - Rationale: Catches edge cases where user doesn't re-restore same target (no auto-cleanup trigger).

## Phase 2 – Concurrency Controls & Usability

- Introduce per-user/per-host/global active caps.
- Document configuration additions and failure scenarios.
- Extend security model and runbooks for throttling alerts.
- **Short Hostname Aliases**
  - Support `dbhost=db3-dev`, `dbhost=db4-dev`, `dbhost=db5-dev` as aliases for full FQDNs.
  - Document alias-to-FQDN resolution logic in CLI.
  - Add `host_alias` column to `db_hosts` table or maintain alias mapping in `settings` table.
  - Update README with shortened syntax examples.

## Phase 3 – Multi-Daemon & Distributed Locks

- Evaluate distributed locking (e.g., Consul, DynamoDB, or MySQL advisory locks).
- Document deployment topology, failover behaviour, audit adjustments.
- Update diagrams to reflect new components.

## Phase 4 – Web Interface & Enhanced Authentication

- **Web Interface**
  - Browser-based job submission, status monitoring, and history viewing.
  - Real-time job progress updates via WebSockets or polling.
  - Document UI/UX patterns, accessibility requirements, and browser support.
- **Enhanced Authentication System**
  - User login with username/password storage (bcrypt/argon2).
  - Two-factor authentication (2FA) via TOTP or SMS.
  - Session management with secure token handling.
  - Password reset and account recovery flows.
  - Document security model updates, credential storage, and audit logging.
  - **Role-Based Access Control (RBAC)**
  - **Admin Role**: Full system access
    - Manage users (add, remove, change roles, enable/disable)
    - View all jobs across all users
    - Cancel any job (including others' jobs)
    - Adjust job priority/queue order
    - Submit jobs on behalf of other users
    - Access system configuration and settings
    - View and manage staging database cleanup
  - **Manager Role**: Operational oversight
    - View all jobs across all users (read-only job list)
    - Cancel jobs (any user's jobs)
    - Adjust job priority/queue order
    - Submit jobs for other users (with proper audit logging)
    - View system metrics and queue health
    - Cannot manage users or change system configuration
  - **User Role** (default): Self-service access
    - Submit own restore jobs
    - View own jobs only (filtered by owner_user_id)
    - Cancel own jobs only
    - View own job history
    - No access to other users' jobs or system operations
  - **Hierarchical Manager-User Relationships (Phase 5)**
    - Add `manager_id` column to `auth_users` table (nullable foreign key to auth_users)
    - Users can be assigned to a specific manager
    - Managers can only manage jobs for their assigned users (not all jobs)
    - Manager permissions scoped to their team:
      - View jobs for assigned users only
      - Cancel jobs for assigned users
      - Adjust priority for assigned users' jobs
      - Submit jobs on behalf of assigned users
    - **Manager-of-Managers** hierarchy:
      - Add `manager_of_managers` table: `(manager_id, subordinate_manager_id, assigned_at)`
      - Senior managers can oversee other managers
      - Inherit visibility of subordinate managers' users
      - Example: Manager A oversees Users 1-5, Manager B oversees Users 6-10, Senior Manager C oversees both Manager A and Manager B → sees Users 1-10
    - **Universal Job Visibility**:
      - All users can view all jobs (read-only)
      - Job list shows: job_id, target, status, owner_username, submitted_at
      - Sensitive details (error_detail, options_json) filtered by permission
      - Manager permissions only control what they can ACTION (cancel, modify), not what they can VIEW
    - **Authorization Rules**:
      - Admin: full access to all users and jobs
      - Manager with team: can action (cancel/modify) only assigned users' jobs, view all jobs
      - Manager without team: same as admin for backwards compatibility (transition period)
      - User: can action only own jobs, view all jobs
    - **Audit Trail**:
      - Track manager assignment changes in job_events
      - Log all manager actions on users' jobs with manager_id context
      - Record manager-of-managers hierarchy changes
  - **Schema Changes**:
    - Add `role` ENUM('user','manager','admin') to `auth_users` table
    - Add `manager_id` CHAR(36) NULL to `auth_users` (foreign key to auth_users.user_id)
    - Add `manager_of_managers` table for hierarchy
    - Default role: 'user'
    - Track role changes in job_events (audit trail)
  - **Authorization Logic**:
    - CLI validates role permissions before job submission
    - Daemon enforces role checks for job cancellation
    - Web interface renders UI based on role capabilities
    - Query filtering for actions: users see own jobs, managers see assigned users' jobs, admins see all
    - Query filtering for viewing: all roles see all jobs (read-only)
  - **Documentation Requirements**:
    - Update security model with RBAC permissions matrix
    - Document role promotion/demotion procedures
    - Add role-based command examples to README
    - Update runbooks with manager troubleshooting workflows
    - Document manager assignment and hierarchy management
    - Explain universal job visibility vs action permissions
- **Migration Strategy**
  - Maintain CLI trusted wrapper authentication for backwards compatibility.
  - Add `auth_credentials` table for web users (hashed passwords, 2FA secrets).
  - Document authentication flow differences between CLI and web interfaces.
  - Migrate existing users to 'user' role by default; manually promote admins/managers.

## Phase 5 – Automation & APIs

- REST/GraphQL API for programmatic job submission and monitoring.
- API token authentication for service accounts.
- Document onboarding flows, rate limits, and security posture.

## Continuous Tasks

- Review backlog items quarterly.
- Keep this roadmap synchronized with `../constitution.md` and product decisions.
- Ensure every phase has clear exit criteria and testing expectations before coding.
