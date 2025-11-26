# pullDB Truth-Energy Matrix

**Protocol:** Sherlock
**Scale:** -1.0 (False) to +1.0 (True)
**Default Weight:** 0.0 (Neutral)

## Active Hypotheses

### 1. Worker Implementation Robustness
**Hypothesis:** The worker system is a robust, production-ready engine that strictly adheres to "FAIL HARD" architecture.
**Current Weight:** +0.90 (Unquestionable)

#### Evidence Chain
| ID | Evidence | Source | Weight Impact | Status |
|:---|:---|:---|:---|:---|
| W-01 | Signal Interception & Graceful Shutdown | `pulldb/worker/service.py` | +0.10 | Verified |
| W-02 | Config Fallback & Error Containment | `pulldb/worker/service.py` | +0.10 | Verified |
| W-03 | Loop Backoff & External Control | `pulldb/worker/loop.py` | +0.10 | Verified |
| W-04 | Path Traversal Guards (Zip Slip) | `pulldb/worker/executor.py` | +0.15 | Verified |
| W-05 | Disk Capacity Pre-flight (1.8x Rule) | `pulldb/worker/downloader.py` | +0.05 | Verified |
| W-06 | FAIL HARD Orchestration (No Retries) | `pulldb/worker/restore.py` | +0.20 | Verified |
| W-07 | Subprocess Timeout & Output Truncation | `pulldb/infra/exec.py` | +0.15 | Verified |
| W-08 | Hardcoded Disk Multiplier (Brittle) | `pulldb/worker/downloader.py` | -0.05 | Verified |
| W-09 | Heuristic Target Derivation (Loose Contract) | `pulldb/worker/executor.py` | -0.05 | Verified |
| W-10 | Staging Orphan Cleanup (Strict Isolation) | `pulldb/worker/staging.py` | +0.10 | Verified |
| W-11 | Post-SQL Sequential Execution (FAIL HARD) | `pulldb/worker/post_sql.py` | +0.10 | Verified |
| W-12 | Atomic Rename Procedure Verification | `pulldb/worker/atomic_rename.py` | +0.10 | Verified |
| W-13 | Metadata Injection (Audit Trail) | `pulldb/worker/metadata.py` | +0.05 | Verified |

#### Deduction
The core machinery is defensive and paranoid about resources. The restore workflow is fully implemented with strict isolation (staging cleanup), atomic cutover (rename procedure), and comprehensive audit trails (metadata). Minor brittleness in constants does not undermine the architectural stability. The system is effectively feature-complete for Phase 0.

---

### 2. Truth Matrix Methodology
**Hypothesis:** The Truth-Energy Matrix provides significant value and is feasible for the pullDB project.
**Current Weight:** +0.80 (High Confidence)

#### Evidence Chain
| ID | Evidence | Source | Weight Impact | Status |
|:---|:---|:---|:---|:---|
| M-01 | Hallucination Prevention (Citation Requirement) | Analysis | +0.30 | Theoretical |
| M-02 | Nuance Capture (Code vs Tested) | Analysis | +0.20 | Theoretical |
| M-03 | Drift Detection Capability | Analysis | +0.20 | Theoretical |
| M-04 | Existing Storage Infrastructure (`docs/`) | Workspace | +0.20 | Verified |
| M-05 | Manual Maintenance Overhead | Analysis | -0.10 | Risk |

#### Deduction
Value is high for a high-reliability project. Feasibility is confirmed via existing doc structures, though automation is recommended for long-term sustainability.

---

### 3. CLI Component Robustness
**Hypothesis:** The CLI provides a user-friendly, fail-hard interface that strictly validates inputs before API submission.
**Current Weight:** +0.85 (Very Strong)

#### Evidence Chain
| ID | Evidence | Source | Weight Impact | Status |
|:---|:---|:---|:---|:---|
| C-01 | Strict Regex Validation (User/Customer) | `pulldb/cli/parse.py` | +0.20 | Verified |
| C-02 | Length Constraint Enforcement (51 chars) | `pulldb/cli/parse.py` | +0.15 | Verified |
| C-03 | FAIL HARD Config Loading (Timeout) | `pulldb/cli/main.py` | +0.10 | Verified |
| C-04 | API Error Formatting & Propagation | `pulldb/cli/main.py` | +0.15 | Verified |
| C-05 | Mutually Exclusive Args (Customer/QA) | `pulldb/cli/parse.py` | +0.15 | Verified |
| C-06 | JSON Output Support (Machine Readable) | `pulldb/cli/main.py` | +0.10 | Verified |

#### Deduction
The CLI acts as a strong gatekeeper, preventing invalid requests from ever reaching the API. Error handling is explicit and actionable.

---

### 4. API Service Robustness
**Hypothesis:** The API service is a stable, async-aware gateway that correctly manages state and enforces business rules.
**Current Weight:** +0.80 (High Confidence)

#### Evidence Chain
| ID | Evidence | Source | Weight Impact | Status |
|:---|:---|:---|:---|:---|
| A-01 | FastAPI + Pydantic Validation | `pulldb/api/main.py` | +0.20 | Verified |
| A-02 | Threadpool Offloading for DB Ops | `pulldb/api/main.py` | +0.15 | Verified |
| A-03 | State Initialization FAIL HARD | `pulldb/api/main.py` | +0.15 | Verified |
| A-04 | HTTP Status Code Mapping (409 Conflict) | `pulldb/api/main.py` | +0.15 | Verified |
| A-05 | Dependency Injection (get_api_state) | `pulldb/api/main.py` | +0.15 | Verified |

#### Deduction
The API service follows modern Python web standards. It correctly handles the impedance mismatch between async HTTP and sync DB drivers using threadpools.

---

### 5. Infrastructure Layer Integrity
**Hypothesis:** The infrastructure layer provides secure, reliable abstractions for external services (MySQL, S3, AWS).
**Current Weight:** +0.90 (Unquestionable)

#### Evidence Chain
| ID | Evidence | Source | Weight Impact | Status |
|:---|:---|:---|:---|:---|
| I-01 | Repository Pattern Implementation | `pulldb/infra/mysql.py` | +0.20 | Verified |
| I-02 | Dual Secret Resolution (SecretsMgr/SSM) | `pulldb/infra/secrets.py` | +0.20 | Verified |
| I-03 | S3 Discovery Validation (Regex/TS) | `pulldb/infra/s3.py` | +0.20 | Verified |
| I-04 | View Fallback Logic (Active Jobs) | `pulldb/infra/mysql.py` | +0.10 | Verified |
| I-05 | Connection Pooling Wrapper | `pulldb/infra/mysql.py` | +0.10 | Verified |
| I-06 | User Code Collision Handling | `pulldb/infra/mysql.py` | +0.10 | Verified |

#### Deduction
The infrastructure layer is the strongest part of the system. It handles external failures gracefully and provides clean interfaces for the domain logic.

---

### 6. Domain & Packaging Standards
**Hypothesis:** The project structure and domain models adhere to strict engineering standards.
**Current Weight:** +0.85 (Very Strong)

#### Evidence Chain
| ID | Evidence | Source | Weight Impact | Status |
|:---|:---|:---|:---|:---|
| D-01 | Immutable Models (Frozen Dataclasses) | `pulldb/domain/models.py` | +0.20 | Verified |
| D-02 | Strict Config Parsing (Positive Ints) | `pulldb/domain/config.py` | +0.15 | Verified |
| D-03 | Modern Packaging (pyproject.toml) | `pyproject.toml` | +0.20 | Verified |
| D-04 | Comprehensive Linter Config (Ruff/Mypy) | `pyproject.toml` | +0.15 | Verified |
| D-05 | Two-Phase Config Loading (Env+DB) | `pulldb/domain/config.py` | +0.15 | Verified |

#### Deduction
The codebase is modern, type-safe, and well-configured. The use of immutable models prevents a whole class of state-related bugs.
