# pullDB Architecture Flowchart

This document visualizes the complete pullDB restore workflow from user request to database deployment.

> **Preview**: Open this file and press `Ctrl+Shift+V` (or `Cmd+Shift+V` on Mac) to see the rendered Mermaid diagrams.

---

## Complete System Flow

```mermaid
flowchart TB
    subgraph UserInterfaces["🖥️ User Interfaces (pages layer)"]
        CLI["pulldb CLI<br/>pulldb.cli.main"]
        WebUI["Web UI<br/>pulldb.web/"]
        API["REST API<br/>pulldb.api.main<br/>port 8080"]
    end

    subgraph Auth["🔐 Authentication"]
        HMAC["CLI HMAC Auth<br/>API Key + Signature"]
        Session["Web Session<br/>bcrypt + Cookie"]
    end

    subgraph Coordination["📊 MySQL Coordination Database"]
        Queue["jobs table<br/>status=QUEUED"]
        JobRepo["JobRepository<br/>claim_next_job()"]
        Events["job_events table<br/>Progress tracking"]
        Hosts["db_hosts table<br/>Target hosts config"]
    end

    subgraph Worker["⚙️ Worker Service (features layer)"]
        Service["pulldb-worker<br/>service.py"]
        Loop["Polling Loop<br/>loop.py<br/>SELECT FOR UPDATE SKIP LOCKED"]
        Executor["Job Executor<br/>executor.py"]
    end

    subgraph RestoreWorkflow["🔄 Restore Workflow"]
        Discovery["Backup Discovery<br/>S3 latest backup"]
        Download["Download Backup<br/>downloader.py"]
        Extract["Extract Archive<br/>tar.gz → files"]
        CreateStaging["Create Staging DB<br/>staging.py"]
        MyLoader["Run myloader<br/>restore.py"]
        PostSQL["Execute Post-SQL<br/>post_sql.py"]
        Metadata["Inject Metadata<br/>metadata.py"]
        AtomicRename["Atomic Rename<br/>atomic_rename.py"]
    end

    subgraph ExternalSystems["☁️ External Systems"]
        S3["AWS S3<br/>mydumper backups"]
        SecretsManager["AWS Secrets Manager<br/>MySQL credentials"]
        TargetMySQL["Target MySQL Host<br/>Restored database"]
    end

    subgraph Status["📈 Job Status Lifecycle"]
        direction LR
        QUEUED["QUEUED"]
        RUNNING["RUNNING"]
        DEPLOYED["DEPLOYED"]
        EXPIRED["EXPIRED"]
        COMPLETE["COMPLETE"]
        FAILED["FAILED"]
        CANCELED["CANCELED"]
    end

    %% User Interface Connections
    CLI -->|"submit job"| API
    WebUI -->|"HTTP requests"| API
    CLI -.->|"HMAC signature"| HMAC
    WebUI -.->|"session cookie"| Session
    HMAC --> API
    Session --> API

    %% API to Queue
    API -->|"INSERT job"| Queue
    API -->|"validate host"| Hosts

    %% Worker Polling
    Service --> Loop
    Loop -->|"poll every 1-30s<br/>exponential backoff"| JobRepo
    JobRepo -->|"claim job<br/>UPDATE status=RUNNING"| Queue
    Loop --> Executor

    %% Restore Workflow Steps
    Executor --> Discovery
    Discovery -->|"find latest backup"| S3
    Discovery --> Download
    Download -->|"download archive"| S3
    Download --> Extract
    Extract --> CreateStaging
    CreateStaging -->|"get credentials"| SecretsManager
    CreateStaging -->|"CREATE DATABASE"| TargetMySQL
    CreateStaging --> MyLoader
    MyLoader -->|"restore tables"| TargetMySQL
    MyLoader --> PostSQL
    PostSQL -->|"sanitize data"| TargetMySQL
    PostSQL --> Metadata
    Metadata -->|"inject pullDB table"| TargetMySQL
    Metadata --> AtomicRename
    AtomicRename -->|"RENAME staging → target"| TargetMySQL

    %% Event Logging
    Executor -.->|"emit events"| Events

    %% Status Transitions
    QUEUED -->|"worker claims"| RUNNING
    RUNNING -->|"success"| DEPLOYED
    RUNNING -->|"error"| FAILED
    RUNNING -->|"user cancels"| CANCELED
    DEPLOYED -->|"TTL expires"| EXPIRED
    DEPLOYED -->|"user marks done"| COMPLETE

    %% Styling
    classDef userInterface fill:#4CAF50,stroke:#2E7D32,color:white
    classDef auth fill:#FF9800,stroke:#F57C00,color:white
    classDef queue fill:#2196F3,stroke:#1565C0,color:white
    classDef worker fill:#9C27B0,stroke:#6A1B9A,color:white
    classDef workflow fill:#00BCD4,stroke:#00838F,color:white
    classDef external fill:#607D8B,stroke:#37474F,color:white
    classDef status fill:#FFC107,stroke:#FF8F00,color:black

    class CLI,WebUI,API userInterface
    class HMAC,Session auth
    class Queue,JobRepo,Events,Hosts queue
    class Service,Loop,Executor worker
    class Discovery,Download,Extract,CreateStaging,MyLoader,PostSQL,Metadata,AtomicRename workflow
    class S3,SecretsManager,TargetMySQL external
    class QUEUED,RUNNING,DEPLOYED,EXPIRED,COMPLETE,FAILED,CANCELED status
```

---

## HCA Layer Architecture

```mermaid
flowchart TB
    subgraph Plugins["plugins/ → pulldb/binaries/"]
        myloader["myloader binary<br/>External tool"]
    end

    subgraph Pages["pages/ → pulldb/cli/, web/, api/"]
        cli["CLI Commands"]
        web["Web Routes"]
        api["API Endpoints"]
    end

    subgraph Widgets["widgets/ → pulldb/worker/service.py"]
        service["Worker Service<br/>Job orchestration"]
    end

    subgraph Features["features/ → pulldb/worker/*.py"]
        executor["Job Executor"]
        restore["Restore Workflow"]
        downloader["Downloader"]
        staging["Staging Manager"]
        post_sql["Post-SQL Runner"]
    end

    subgraph Entities["entities/ → pulldb/domain/"]
        models["Job, User, Host<br/>Data models"]
        config["Config"]
        errors["Domain Errors"]
    end

    subgraph Shared["shared/ → pulldb/infra/"]
        mysql["MySQL Pool/Repos"]
        s3["S3 Client"]
        secrets["Secrets Manager"]
        logging["Logging"]
        exec["Command Executor"]
    end

    %% Layer dependencies (top-down only)
    Plugins --> Pages
    Pages --> Widgets
    Widgets --> Features
    Features --> Entities
    Entities --> Shared

    %% Internal dependencies
    cli --> service
    web --> service
    api --> service
    service --> executor
    executor --> restore
    executor --> downloader
    restore --> staging
    restore --> post_sql
    restore --> models
    staging --> mysql
    downloader --> s3
    executor --> secrets

    classDef plugins fill:#E91E63,stroke:#880E4F,color:white
    classDef pages fill:#4CAF50,stroke:#2E7D32,color:white
    classDef widgets fill:#2196F3,stroke:#1565C0,color:white
    classDef features fill:#9C27B0,stroke:#6A1B9A,color:white
    classDef entities fill:#FF9800,stroke:#F57C00,color:white
    classDef shared fill:#607D8B,stroke:#37474F,color:white

    class myloader plugins
    class cli,web,api pages
    class service widgets
    class executor,restore,downloader,staging,post_sql features
    class models,config,errors entities
    class mysql,s3,secrets,logging,exec shared
```

---

## Job Status State Machine

```mermaid
stateDiagram-v2
    [*] --> QUEUED: Job submitted

    QUEUED --> RUNNING: Worker claims job<br/>claim_next_job()

    RUNNING --> DEPLOYED: Restore successful<br/>Database live
    RUNNING --> FAILED: Error during restore
    RUNNING --> CANCELING: User requests cancel
    
    CANCELING --> CANCELED: Worker stops at checkpoint

    DEPLOYED --> EXPIRED: TTL expires<br/>(retention period)
    DEPLOYED --> COMPLETE: User marks "done"<br/>Moves to History
    DEPLOYED --> DELETING: User deletes database
    DEPLOYED --> SUPERSEDED: New restore to same target

    DELETING --> DELETED: Database dropped

    EXPIRED --> DELETED: Cleanup job runs

    FAILED --> [*]: Terminal state
    CANCELED --> [*]: Terminal state
    DELETED --> [*]: Terminal state
    COMPLETE --> [*]: Terminal state
    SUPERSEDED --> [*]: Terminal state
```

---

## Restore Workflow Sequence

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant API as API Service
    participant DB as MySQL Queue
    participant W as Worker
    participant S3 as AWS S3
    participant SM as Secrets Manager
    participant TH as Target Host

    U->>API: Submit restore job
    API->>API: Validate request
    API->>DB: INSERT job (QUEUED)
    API-->>U: Job ID returned

    loop Poll Loop (1-30s backoff)
        W->>DB: SELECT FOR UPDATE SKIP LOCKED
    end
    
    DB-->>W: Job claimed
    W->>DB: UPDATE status=RUNNING

    rect rgb(240, 248, 255)
        Note over W,TH: Restore Workflow
        
        W->>S3: Discover latest backup
        S3-->>W: Backup metadata
        
        W->>S3: Download archive
        S3-->>W: tar.gz file
        
        W->>W: Extract archive
        
        W->>SM: Get MySQL credentials
        SM-->>W: host/user/password
        
        W->>TH: CREATE DATABASE staging_xxx
        
        W->>TH: myloader (restore tables)
        Note right of TH: Progress events emitted
        
        W->>TH: Execute post-SQL scripts<br/>(sanitize, configure)
        
        W->>TH: Inject pullDB metadata table
        
        W->>TH: RENAME staging → target<br/>(atomic)
    end

    W->>DB: UPDATE status=DEPLOYED
    W->>DB: INSERT job_events (complete)
    
    U->>API: Check job status
    API->>DB: SELECT job
    DB-->>API: Job details
    API-->>U: Status: DEPLOYED ✓
```

---

## Data Flow Overview

```mermaid
flowchart LR
    subgraph Input["📥 Input"]
        Backup["mydumper backup<br/>S3 archive"]
        Request["User request<br/>customer + target"]
    end

    subgraph Processing["⚙️ Processing"]
        Download["Download<br/>& Extract"]
        Restore["myloader<br/>Restore"]
        PostProcess["Post-SQL<br/>Sanitize"]
    end

    subgraph Output["📤 Output"]
        StagingDB["Staging DB<br/>stg_xxx_timestamp"]
        TargetDB["Target DB<br/>usercode + customer"]
    end

    subgraph Tracking["📊 Tracking"]
        Events["Job Events"]
        Metrics["Prometheus<br/>Metrics"]
        Logs["Structured<br/>Logs"]
    end

    Backup --> Download
    Request --> Download
    Download --> Restore
    Restore --> StagingDB
    StagingDB --> PostProcess
    PostProcess --> TargetDB

    Download -.-> Events
    Restore -.-> Events
    PostProcess -.-> Events
    
    Download -.-> Metrics
    Restore -.-> Metrics
    
    Download -.-> Logs
    Restore -.-> Logs
    PostProcess -.-> Logs
```

---

## Quick Reference

| Component | Entry Point | Port | Purpose |
|-----------|-------------|------|---------|
| CLI | `pulldb` | - | User job management |
| Admin CLI | `pulldb-admin` | - | System operations |
| REST API | `pulldb-api` | 8080 | Programmatic access |
| Web UI | `pulldb-web` | 8000 | Browser interface |
| Worker | `pulldb-worker` | - | Background job processor |

### Key Files

| File | Layer | Role |
|------|-------|------|
| `pulldb/cli/main.py` | pages | CLI entry point |
| `pulldb/api/main.py` | pages | FastAPI application |
| `pulldb/worker/service.py` | widgets | Worker daemon |
| `pulldb/worker/executor.py` | features | Job execution |
| `pulldb/worker/restore.py` | features | myloader wrapper |
| `pulldb/domain/models.py` | entities | Core data models |
| `pulldb/infra/mysql.py` | shared | Database operations |
