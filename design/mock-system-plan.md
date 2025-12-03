# Project Plan: pullDB Simulation Engine (Mock System Replacement)

> **Status**: Phase 4 Complete ✅ (Core Engine + Tests)
> **Branch**: `feature/mock-system-phase3`
> **Goal**: Replace current ad-hoc mocks with a 100% high-fidelity Simulation Engine for development, testing, and demos.
> **Architecture**: HCA Compliant

## 1. Executive Summary

The current testing infrastructure relies on partial mocks and requires live dependencies (MySQL, AWS) for full system verification. This project will introduce a **Simulation Engine** that provides a high-fidelity, in-memory replica of the entire backend stack.

This engine will support:
- **100% Offline Development**: Run the full stack (CLI, API, Worker, Web UI) without AWS or MySQL.
- **Deterministic Testing**: Reproducible scenarios for complex failure modes (network partitions, timeouts, corruption).
- **Observability**: Full tracing of internal state transitions.
- **Chaos Engineering**: Injectable faults (latency, errors) to validate FAIL HARD protocols.

## 2. Architecture & HCA Alignment

This project will follow **Hierarchical Containment Architecture (HCA)**.

### 2.1 Directory Structure (Implemented)

```
pulldb/
├── simulation/                 # ✅ Simulation Domain
│   ├── __init__.py             # ✅ Exports all public components
│   ├── core/                   # ✅ Core Engine Logic
│   │   ├── state.py            # ✅ SimulationState (thread-safe in-memory DB)
│   │   ├── bus.py              # ✅ SimulationEventBus (pub/sub + history)
│   │   └── scenarios.py        # ✅ ScenarioManager + ChaosConfig
│   └── adapters/               # ✅ Mock Implementations of Infra
│       ├── mock_mysql.py       # ✅ SimulatedJobRepository, UserRepo, HostRepo, SettingsRepo
│       ├── mock_s3.py          # ✅ MockS3Client with fixture loading
│       └── mock_exec.py        # ✅ MockProcessExecutor with command config
├── tests/
│   └── simulation/             # ✅ Test Suite
│       └── test_simulation.py  # ✅ 34 tests covering all components
```

### 2.2 Dependency Injection Strategy
To switch between Real and Simulated modes without code duplication, we will introduce a lightweight **Service Locator** or **Factory Pattern** in `pulldb/infra/factory.py`.

- **Real Mode**: Returns `MySQLRepository`, `Boto3S3Client`.
- **Simulation Mode**: Returns `SimulatedRepository`, `SimulatedS3Client`.
- **Trigger**: Controlled via `PULLDB_MODE=SIMULATION` environment variable.

## 3. Component Analysis & Simulation Strategy

### 3.1 API & Web UI
- **Current**: FastAPI routes interacting with `JobRepository`.
- **Simulation**: The API will remain *unchanged*. It will simply be injected with a `SimulatedRepository`.
- **Benefit**: The Web UI and CLI will interact with the "real" API logic, ensuring 100% coverage of the application layer.

### 3.2 Admin CLI (`pulldb-admin`)
- **Current**: Connects directly to MySQL.
- **Simulation**: The `SimulatedRepository` must implement the exact interface used by the Admin CLI.
- **Challenge**: If Admin CLI uses raw SQL, we must either:
    1.  Refactor Admin CLI to use Repository pattern (Recommended).
    2.  Implement an in-memory SQL parser (Too complex/brittle).
    *Decision*: **Refactor Admin CLI to use Repository Pattern** as part of this project.

### 3.3 Worker Service
- **Current**: Polls MySQL, calls S3, runs subprocesses.
- **Simulation**:
    - **Queue**: `SimulatedRepository` handles `SKIP LOCKED` logic in memory.
    - **S3**: `SimulatedS3Client` returns fixtures from `pulldb/simulation/fixtures/`.
    - **Execution**: `SimulatedExecutor` "sleeps" to simulate restore time and updates progress via callbacks.

## 4. Features & Capabilities

### 4.1 Scenario Management (Implemented)
The engine supports "Scenario Profiles" via `ScenarioManager`.

| Scenario | Description | Status |
| :--- | :--- | :--- |
| **happy_path** | All operations succeed with minimal delay. | ✅ Implemented |
| **single_job_success** | One job runs to completion successfully. | ✅ Implemented |
| **s3_not_found** | Backup files are missing from S3. | ✅ Implemented |
| **s3_permission_denied** | S3 access is denied. | ✅ Implemented |
| **myloader_failure** | myloader command fails with non-zero exit code. | ✅ Implemented |
| **myloader_timeout** | myloader takes too long and times out. | ✅ Implemented |
| **post_sql_failure** | Post-restore SQL script fails. | ✅ Implemented |
| **random_failures** | Random 20% failure rate on all operations. | ✅ Implemented |
| **slow_operations** | All operations have significant delays. | ✅ Implemented |
| **intermittent_failures** | Flaky operations that occasionally fail. | ✅ Implemented |

### 4.2 Tracing & Observability (Implemented)
The `SimulationEventBus` captures every interaction.

- **Event Types** (15 total):
    - Job: `JOB_CREATED`, `JOB_CLAIMED`, `JOB_COMPLETED`, `JOB_FAILED`, `JOB_CANCELED`
    - S3: `S3_LIST_KEYS`, `S3_HEAD_OBJECT`, `S3_GET_OBJECT`, `S3_ERROR`
    - Exec: `EXEC_START`, `EXEC_COMPLETE`, `EXEC_ERROR`
    - System: `DB_QUERY`, `DB_INSERT`, `DB_UPDATE`, `STATE_RESET`, `SCENARIO_CHANGED`
- **Features**:
    - `emit()` - Publish events with source, data, and optional job_id
    - `subscribe()` - Register callbacks for specific event types
    - `get_history()` - Query event history with filters (event_type, job_id, limit)
    - `wait_for_event()` - Block until event occurs (for test synchronization)
    - `clear_history()` / `clear_subscribers()` - Reset for test isolation

## 5. Implementation Plan (Phased)

### Phase 1: Foundation & Refactoring ✅
1.  **Define Interfaces**: Formalized `JobRepository`, `S3Client`, `ProcessExecutor` protocols in `pulldb/domain/interfaces.py`.
2.  **Refactor Infra**: Updated `pulldb/infra/` to implement these interfaces.
3.  **Refactor Admin CLI**: Switched `pulldb-admin` to use `JobRepository` instead of raw SQL.
4.  **Create Factory**: Implemented `InfraFactory` with `is_simulation_mode()` check.

### Phase 2: The Simulation Core ✅
5.  **Scaffold Simulation Domain**: Created `pulldb/simulation/` structure (HCA compliant).
6.  **Implement Mock DB**: Created `SimulatedJobRepository` + User/Host/Settings repos (Dict-based, thread-safe).
7.  **Implement Mock S3**: Created `MockS3Client` with `load_fixtures()` support.
8.  **Implement Mock Executor**: Created `MockProcessExecutor` with `MockCommandConfig` for delay/failure injection.

### Phase 3: Integration & Scenarios ✅
9.  **Wire Up API**: Updated `main.py` with `_initialize_simulation_state()`.
10. **Wire Up Worker**: Updated `worker/service.py` with simulation dispatching.
11. **Scenario Engine**: Built `ScenarioManager` with 10 scenarios + `ChaosConfig`.
12. **Event Bus**: Implemented `SimulationEventBus` and wired into all mock adapters.

### Phase 4: Validation ✅ / Web UI (Future)
13. **Test Suite**: Created 34 comprehensive tests in `pulldb/tests/simulation/`.
14. **Simulation Control API**: (Future) Add REST endpoints to control simulation.
15. **Web UI Integration**: (Future) Add "Simulation Mode" indicator and debug panel.

## 6. Research & References
- **Service Virtualization**: Concepts from *Mountebank* and *WireMock*.
- **Chaos Engineering**: Principles from *Netflix Simian Army*.
- **Hexagonal Architecture**: The "Ports and Adapters" pattern is the theoretical basis for this design.

## 7. Next Steps
1.  Approve this plan.
2.  Begin Phase 1 (Refactoring interfaces).
