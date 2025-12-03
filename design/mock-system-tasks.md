# Task List: pullDB Simulation Engine

> **Parent Project**: [Mock System Plan](mock-system-plan.md)
> **Status**: **ALL PHASES COMPLETE** ✅ (Phase 1-4)
> **Branch**: `feature/mock-system-phase3`

## Phase 1: Foundation & Refactoring (Interfaces)

- [x] **1.1 Define Domain Interfaces**
    - [x] Create `pulldb/domain/interfaces.py`.
    - [x] Define `JobRepository` Protocol (add, get, list, update_status).
    - [x] Define `S3Client` Protocol (list_backups, download_backup).
    - [x] Define `ProcessExecutor` Protocol (run_command).
- [x] **1.2 Refactor MySQL Infra**
    - [x] Modify `pulldb/infra/mysql.py` to implement `JobRepository`.
    - [x] Ensure all SQL logic is encapsulated within the repository methods.
- [x] **1.3 Refactor S3 Infra**
    - [x] Modify `pulldb/infra/s3.py` to implement `S3Client`.
- [x] **1.4 Refactor Admin CLI**
    - [x] Audit `pulldb/cli/admin.py` for direct SQL usage.
    - [x] Replace direct SQL with calls to `JobRepository`.
- [x] **1.5 Implement Infra Factory**
    - [x] Create `pulldb/infra/factory.py`.
    - [x] Implement `get_repository()`, `get_s3_client()`, `get_executor()`.
    - [x] Add logic to read `PULLDB_MODE` env var.

## Phase 2: Simulation Core (The Engine)

- [x] **2.1 Scaffold Simulation Domain**
    - [x] Create `pulldb/simulation/` directory structure.
    - [x] Create `pulldb/simulation/__init__.py`.
- [x] **2.2 Implement In-Memory Repository**
    - [x] Create `pulldb/simulation/adapters/mock_mysql.py`.
    - [x] Implement `SimulatedJobRepository` using a thread-safe dictionary.
    - [x] Implement `SKIP LOCKED` logic for queue polling using locks.
    - [x] Implement `SimulatedUserRepository`, `SimulatedHostRepository`, `SimulatedSettingsRepository`.
- [x] **2.3 Implement Mock S3**
    - [x] Create `pulldb/simulation/adapters/mock_s3.py`.
    - [x] Implement `MockS3Client`.
    - [x] Create fixture loader via `load_fixtures()` method.
- [x] **2.4 Implement Mock Executor**
    - [x] Create `pulldb/simulation/adapters/mock_exec.py`.
    - [x] Implement `MockProcessExecutor`.
    - [x] Add support for simulated delays (`time.sleep`).
    - [x] Add `MockCommandConfig` for configurable command behavior.

## Phase 3: Integration & Scenarios

- [x] **3.1 Wire Up API Service**
    - [x] Update `pulldb/api/main.py` to use `InfraFactory`.
    - [x] Add `_initialize_simulation_state()` for simulation mode.
    - [x] Verify API works with `PULLDB_MODE=SIMULATION`.
- [x] **3.2 Wire Up Worker Service**
    - [x] Update `pulldb/worker/service.py` to use `InfraFactory`.
    - [x] Add `_build_job_repository()` and `_build_job_executor()` dispatching.
    - [x] Verify Worker picks up jobs from in-memory queue.
- [x] **3.3 Implement Event Bus**
    - [x] Create `pulldb/simulation/core/bus.py`.
    - [x] Define `EventType` enum with 15 event types:
        - Job: `JOB_CREATED`, `JOB_CLAIMED`, `JOB_COMPLETED`, `JOB_FAILED`, `JOB_CANCELED`
        - S3: `S3_LIST_KEYS`, `S3_HEAD_OBJECT`, `S3_GET_OBJECT`, `S3_ERROR`
        - Exec: `EXEC_START`, `EXEC_COMPLETE`, `EXEC_ERROR`
        - System: `DB_QUERY`, `STATE_RESET`, `SCENARIO_CHANGED`
    - [x] Implement `SimulationEventBus` with pub/sub, history, and `wait_for_event()`.
    - [x] Wire event emissions into `MockS3Client`.
    - [x] Wire event emissions into `MockProcessExecutor`.
    - [x] Wire event emissions into `SimulatedJobRepository`.
- [x] **3.4 Implement Scenario Manager**
    - [x] Create `pulldb/simulation/core/scenarios.py`.
    - [x] Define `Scenario`, `ScenarioType`, `ChaosConfig` dataclasses.
    - [x] Implement `ScenarioManager` with 10 built-in scenarios:
        - `happy_path`, `single_job_success`, `multiple_jobs_success`
        - `s3_not_found`, `s3_permission_denied`
        - `myloader_failure`, `myloader_timeout`, `post_sql_failure`
        - `random_failures`, `slow_operations`, `intermittent_failures`
    - [x] Implement chaos injection via `inject_chaos()` method.

## Phase 4: Web UI & Validation

- [x] **4.1 Simulation Control API**
    - [x] Create `pulldb/simulation/api/router.py`.
    - [x] Add `POST /simulation/reset` endpoint.
    - [x] Add `POST /simulation/scenarios/activate` endpoint.
    - [x] Add `GET /simulation/status` endpoint.
    - [x] Add `GET /simulation/events` endpoint.
    - [x] Add `GET /simulation/scenarios` endpoint.
    - [x] Add `POST /simulation/chaos` endpoint.
    - [x] Add `GET /simulation/state` endpoint.
    - [x] Add `DELETE /simulation/events` endpoint.
    - [x] Add `GET /simulation/event-types`, `GET /simulation/scenario-types` endpoints.
    - [x] Mount router in `pulldb/api/main.py` (only if in SIMULATION mode).
- [x] **4.2 Web UI Integration**
    - [x] Add visual indicator "SIMULATION MODE" banner to base.html.
    - [x] Add "Debug Panel" modal with:
        - [x] Current state display
        - [x] Scenario selector dropdown
        - [x] Event history log (latest 20 events)
    - [x] Wire `simulation_mode()` and `simulation_scenario_name()` Jinja2 globals.
    - [x] Add CSS styles for `.simulation-banner`, `.simulation-panel`, etc.
    - [x] Add JavaScript for panel open/close and API interactions.
- [x] **4.3 Comprehensive Testing**
    - [x] Create `pulldb/tests/simulation/test_simulation.py` with 34 tests.
    - [x] Test `SimulationState` singleton and reset behavior.
    - [x] Test `EventBus` emit, subscribe, filter, and wait_for_event.
    - [x] Test `SimulatedJobRepository` full lifecycle (enqueue, claim, complete, fail).
    - [x] Test `MockS3Client` fixtures and operations.
    - [x] Test `MockProcessExecutor` command configuration.
    - [x] Test `ScenarioManager` scenario activation and chaos injection.
    - [x] Integration tests for full job lifecycle scenarios.
