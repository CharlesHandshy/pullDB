# Task List: pullDB Simulation Engine

> **Parent Project**: [Mock System Plan](mock-system-plan.md)
> **Status**: Pending Approval

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

- [ ] **2.1 Scaffold Simulation Domain**
    - [ ] Create `pulldb/simulation/` directory structure.
    - [ ] Create `pulldb/simulation/__init__.py`.
- [ ] **2.2 Implement In-Memory Repository**
    - [ ] Create `pulldb/simulation/adapters/mock_mysql.py`.
    - [ ] Implement `InMemoryJobRepository` using a thread-safe dictionary.
    - [ ] Implement `SKIP LOCKED` logic for queue polling using locks.
- [ ] **2.3 Implement Mock S3**
    - [ ] Create `pulldb/simulation/adapters/mock_s3.py`.
    - [ ] Implement `MockS3Client`.
    - [ ] Create fixture loader to read fake backup lists from JSON.
- [ ] **2.4 Implement Mock Executor**
    - [ ] Create `pulldb/simulation/adapters/mock_exec.py`.
    - [ ] Implement `MockProcessExecutor`.
    - [ ] Add support for simulated delays (`time.sleep`).

## Phase 3: Integration & Scenarios

- [ ] **3.1 Wire Up API Service**
    - [ ] Update `pulldb/api/main.py` to use `InfraFactory`.
    - [ ] Verify API works with `PULLDB_MODE=SIMULATION`.
- [ ] **3.2 Wire Up Worker Service**
    - [ ] Update `pulldb/worker/service.py` to use `InfraFactory`.
    - [ ] Verify Worker picks up jobs from in-memory queue.
- [ ] **3.3 Implement Event Bus**
    - [ ] Create `pulldb/simulation/core/bus.py`.
    - [ ] Define event types (`JobCreated`, `S3DownloadStarted`, etc.).
    - [ ] Inject bus into all mock adapters.
- [ ] **3.4 Implement Scenario Manager**
    - [ ] Create `pulldb/simulation/scenarios/manager.py`.
    - [ ] Define `ScenarioProfile` dataclass.
    - [ ] Implement "Chaos Injectors" in adapters (e.g., if profile.s3_error_rate > 0, raise Error).

## Phase 4: Web UI & Validation

- [ ] **4.1 Simulation Control API**
    - [ ] Create `pulldb/simulation/api/router.py`.
    - [ ] Add `POST /simulation/reset` endpoint.
    - [ ] Add `POST /simulation/scenario` endpoint.
    - [ ] Mount router in `pulldb/api/main.py` (only if in SIMULATION mode).
- [ ] **4.2 Web UI Integration**
    - [ ] Add visual indicator "SIMULATION MODE" to Web UI.
    - [ ] Add "Debug Panel" to view Event Bus stream.
- [ ] **4.3 Comprehensive Testing**
    - [ ] Write integration tests using the Simulation Engine.
    - [ ] Verify 100% coverage of all API endpoints.
    - [ ] Verify "Fail Hard" scenarios (e.g., simulate S3 permission error and check job status).
