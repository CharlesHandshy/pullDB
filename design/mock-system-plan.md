# Project Plan: pullDB Simulation Engine (Mock System Replacement)

> **Status**: Planning Phase
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

### 2.1 New Directory Structure
We will establish a new domain for simulation to avoid polluting production code.

```
pulldb/
├── simulation/                 # [NEW] Simulation Domain
│   ├── __init__.py
│   ├── core/                   # Core Engine Logic
│   │   ├── engine.py           # Central State Machine
│   │   ├── state.py            # In-memory Database (Dict/SQLite)
│   │   └── clock.py            # Virtual Time Management
│   ├── adapters/               # Mock Implementations of Infra
│   │   ├── mock_mysql.py       # Replaces infra/mysql.py
│   │   ├── mock_s3.py          # Replaces infra/s3.py
│   │   └── mock_exec.py        # Replaces infra/exec.py (myloader)
│   ├── scenarios/              # Chaos & Scenario Definitions
│   │   ├── profiles.py         # "Slow Network", "Corrupt Data"
│   │   └── generator.py        # Automated scenario generation
│   └── api/                    # Simulation Control API (for Web UI/Tests)
│       └── router.py           # Endpoints to control the simulation
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

### 4.1 Scenario Management
The engine will support "Scenario Profiles" to validate system resilience.

| Scenario | Description | Implementation |
| :--- | :--- | :--- |
| **Happy Path** | Standard fast restore. | No delays, 100% success rate. |
| **Slow S3** | S3 listing/download takes 30s+. | `SimulatedS3` injects `time.sleep()`. |
| **Network Flap** | Connections drop randomly. | Adapters raise `ConnectionError` randomly. |
| **OOM Kill** | Worker dies mid-restore. | `SimulatedExecutor` raises `SystemExit` or simulates crash. |
| **Corrupt Backup** | `myloader` fails validation. | `SimulatedExecutor` returns non-zero exit code + stderr. |
| **Race Condition** | Double submission. | `SimulatedRepository` enforces constraints strictly. |

### 4.2 Tracing & Observability
A `SimulationEventBus` will capture every interaction.

- **Events**: `API_REQUEST`, `DB_QUERY`, `S3_CALL`, `WORKER_STATE_CHANGE`.
- **Output**:
    - **Console**: Real-time log stream.
    - **Web UI**: A "Debug Panel" in the frontend to visualize the state.
    - **Test Assertions**: Tests can subscribe to the bus to assert sequences (e.g., "Ensure S3 download started AFTER DB status update").

## 5. Implementation Plan (Phased)

### Phase 1: Foundation & Refactoring
1.  **Define Interfaces**: Formalize `JobRepository`, `S3Client`, `ProcessExecutor` protocols in `pulldb/domain/interfaces.py`.
2.  **Refactor Infra**: Update `pulldb/infra/` to implement these interfaces.
3.  **Refactor Admin CLI**: Switch `pulldb-admin` to use `JobRepository` instead of raw SQL.
4.  **Create Factory**: Implement `InfraFactory` to switch implementations.

### Phase 2: The Simulation Core
5.  **Scaffold Simulation Domain**: Create `pulldb/simulation/` structure (HCA).
6.  **Implement Mock DB**: Create `InMemoryJobRepository` (Dict-based, thread-safe).
7.  **Implement Mock S3**: Create `MockS3Client` with fixture support.
8.  **Implement Mock Executor**: Create `MockProcessExecutor` with delay/failure injection.

### Phase 3: Integration & Scenarios
9.  **Wire Up API**: Update `main.py` to use `InfraFactory`.
10. **Wire Up Worker**: Update `worker/service.py` to use `InfraFactory`.
11. **Scenario Engine**: Build the `ScenarioManager` to inject faults.
12. **Trace Bus**: Implement the event bus and hook it into all mock adapters.

### Phase 4: Web UI & Validation
13. **Simulation Control API**: Add endpoints to `POST /simulation/scenario` to switch profiles at runtime.
14. **Web UI Integration**: Add a "Simulation Mode" indicator and controls to the frontend.
15. **Audit & Coverage**: Verify 100% trace coverage of all endpoints and flows.

## 6. Research & References
- **Service Virtualization**: Concepts from *Mountebank* and *WireMock*.
- **Chaos Engineering**: Principles from *Netflix Simian Army*.
- **Hexagonal Architecture**: The "Ports and Adapters" pattern is the theoretical basis for this design.

## 7. Next Steps
1.  Approve this plan.
2.  Begin Phase 1 (Refactoring interfaces).
