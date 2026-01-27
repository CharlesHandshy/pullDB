# pullDB Web UI User Guide

> **Complete guide to the pullDB web dashboard**
>
> The web UI provides a browser-based interface for managing database restores,
> monitoring job status, and performing administrative tasks.

## Table of Contents

- [Accessing the Web UI](#accessing-the-web-ui)
- [Login & Authentication](#login--authentication)
- [Dashboard Overview](#dashboard-overview)
- [Submitting Restore Jobs](#submitting-restore-jobs)
- [Monitoring Jobs](#monitoring-jobs)
- [Job Details & Events](#job-details--events)
- [Manager Features](#manager-features)
- [Admin Features](#admin-features)
- [Keyboard Navigation](#keyboard-navigation)

---

## Accessing the Web UI

The web UI is accessible at:

| Environment | URL |
|-------------|-----|
| Production | `http://pulldb-server:8000/` |
| Development | `http://localhost:8000/` |

> **Note**: The service runs on port 8000 by default. Contact your administrator if a different port is configured.

---

## Login & Authentication

### Login Page

Navigate to the root URL to access the login page:

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                   │
│                    ┌─────────────────────┐                       │
│                    │     pullDB Logo     │                       │
│                    └─────────────────────┘                       │
│                                                                   │
│                    ┌─────────────────────┐                       │
│                    │ Username            │                       │
│                    └─────────────────────┘                       │
│                    ┌─────────────────────┐                       │
│                    │ Password            │                       │
│                    └─────────────────────┘                       │
│                                                                   │
│                    [        Login        ]                       │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

> **Note**: User registration is handled via CLI (`pulldb register`), not the web UI.

### Session Management

- Sessions expire after **24 hours** by default
- You'll be redirected to login if your session expires
- Session timeout can be configured by the administrator

### First-Time Password Setup

If you're a new user without a password:

1. Enter your username on the login page
2. You'll be prompted to set a password
3. Passwords must be at least 8 characters

---

## Dashboard Overview

After login, you'll see the main dashboard:

```
┌─────────────────────────────────────────────────────────────────────┐
│ 🎬 │  Dashboard                                                     │
│    │  Welcome back, jsmith                                          │
├────┼────────────────────────────────────────────────────────────────┤
│ S  │                                                                 │
│ I  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│ D  │  │ Active Jobs  │  │  Completed   │  │   Failed     │         │
│ E  │  │     3        │  │    47        │  │     2        │         │
│ B  │  └──────────────┘  └──────────────┘  └──────────────┘         │
│ A  │                                                                 │
│ R  │  Recent Activity                                               │
│    │  ┌─────────────────────────────────────────────────────────┐  │
│ 📊 │  │ Job ID    │ Target     │ Status   │ Started     │ Host  │  │
│ Da │  ├───────────┼────────────┼──────────┼─────────────┼───────┤  │
│ sh │  │ 8b4c...   │ cust_123   │ running  │ 2 min ago   │ dev-1 │  │
│ bo │  │ 2f9a...   │ cust_456   │ queued   │ 5 min ago   │ dev-1 │  │
│ ar │  │ 7c3d...   │ cust_789   │ complete │ 1 hour ago  │ dev-2 │  │
│ d  │  └─────────────────────────────────────────────────────────┘  │
│    │                                                                 │
│ 📤 │  [  New Restore  ]                                             │
│ Re │                                                                 │
│ st │                                                                 │
│ or ├────────────────────────────────────────────────────────────────┤
│ e  │ © 2025 pullDB • v1.0.0              Service Titan / Field Routes│
├────┴────────────────────────────────────────────────────────────────┤
│ 👤 jsmith                                                            │
└─────────────────────────────────────────────────────────────────────┘
```

### Navigation Sidebar

| Icon | Page | Description |
|------|------|-------------|
| 📊 | Dashboard | Overview and recent activity |
| 📤 | New Restore | Submit a restore job |
| 📋 | Jobs | Browse all jobs with filters |
| ⚙️ | Settings | User preferences |
| 👥 | Team | Manager: team member jobs |
| 🔧 | Admin | Admin: system configuration |

---

## Submitting Restore Jobs

### New Restore Page

Click **New Restore** in the sidebar to open the job submission form:

```
┌─────────────────────────────────────────────────────────────────────┐
│ New Restore                                                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Restore Type                                                        │
│  ○ Customer Backup    ● QA Template                                  │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Customer *                                                    │    │
│  │ [ Search customers...                              🔍 ]      │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Target Database *                                             │    │
│  │ [ cust_12345                                        ]        │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Database Host                                                 │    │
│  │ [ dev-mysql-01                                   ▼ ]         │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  Advanced Options  ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ □ Overwrite existing database                                │    │
│  │ Environment: ○ Staging  ○ Production                         │    │
│  │ Backup Date: [ YYYY-MM-DD ]                                  │    │
│  │ Suffix: [ __ ] (optional, 1-3 letters)                       │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  [  Submit Restore  ]                                                │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Form Fields

| Field | Required | Description |
|-------|----------|-------------|
| **Restore Type** | Yes | Customer backup or QA template |
| **Customer** | Yes* | Customer name (autocomplete search) |
| **Target Database** | Yes | Database name for restore |
| **Database Host** | No | Target MySQL server (dropdown) |
| **Overwrite** | No | Allow overwriting existing database |
| **Environment** | No | Staging or Production S3 bucket |
| **Backup Date** | No | Specific backup date |
| **Suffix** | No | Add suffix to database name |

*Not required for QA Template restores.

### Submitting the Job

1. Fill in required fields
2. Click **Submit Restore**
3. You'll be redirected to the job detail page
4. Monitor progress in real-time

---

## Monitoring Jobs

### Jobs List Page

The Jobs page shows all jobs with filtering options:

```
┌─────────────────────────────────────────────────────────────────────┐
│ Jobs                                                  [Filter ▼]    │
├─────────────────────────────────────────────────────────────────────┤
│  Status: [All ▼]  User: [All ▼]  Host: [All ▼]  [🔍 Search...]    │
├─────────────────────────────────────────────────────────────────────┤
│ │ □ │ Job ID     │ Target      │ Status    │ Duration  │ Host     │ │
│ ├───┼────────────┼─────────────┼───────────┼───────────┼──────────┤ │
│ │ □ │ 8b4c4a3a   │ cust_12345  │ 🟢 done   │ 4m 23s    │ dev-01   │ │
│ │ □ │ 2f9a7b1c   │ cust_67890  │ 🔵 running│ 2m 15s    │ dev-01   │ │
│ │ □ │ 7c3d8e2f   │ cust_11111  │ 🟡 queued │ -         │ dev-02   │ │
│ │ □ │ 9a1b2c3d   │ cust_22222  │ 🔴 failed │ 1m 45s    │ dev-01   │ │
│ │ □ │ 4e5f6g7h   │ cust_33333  │ ⚫ canceled│ 30s      │ dev-02   │ │
└─────────────────────────────────────────────────────────────────────┘
│ Showing 1-25 of 156  [◀ Prev] [Next ▶]  [Bulk Actions ▼]           │
└─────────────────────────────────────────────────────────────────────┘
```

### Status Indicators

| Status | Icon | Description |
|--------|------|-------------|
| Queued | 🟡 | Waiting for worker |
| Running | 🔵 | Currently executing |
| Completed | 🟢 | Successfully finished |
| Failed | 🔴 | Error occurred |
| Canceled | ⚫ | Canceled by user |

### Filtering & Search

- **Status Filter**: Show only specific statuses
- **User Filter**: Filter by job owner
- **Host Filter**: Filter by target host
- **Search**: Free-text search across job IDs and targets

### Bulk Actions

Select multiple jobs using checkboxes, then use bulk actions:

- **Cancel Selected**: Cancel multiple queued/running jobs
- **Export CSV**: Download job data

---

## Job Details & Events

Click any job row to view detailed information:

```
┌─────────────────────────────────────────────────────────────────────┐
│ Job: 8b4c4a3a-85a1-4da2-9f3e-1a2b3c4d5e6f                          │
│ Status: 🟢 Completed                                    [Cancel]    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  Summary                                                             │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Target:        cust_12345                                    │    │
│  │ Source:        acme_pest (staging)                          │    │
│  │ Host:          dev-mysql-01                                 │    │
│  │ Submitted:     2026-01-02 15:30:00 by jsmith                │    │
│  │ Started:       2026-01-02 15:30:05                          │    │
│  │ Completed:     2026-01-02 15:34:28                          │    │
│  │ Duration:      4m 23s                                       │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  Performance Breakdown                                               │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ Download   ████████░░░░░░░░░░░░░░░░░  45.2s (17%)          │    │
│  │ Extract    ██░░░░░░░░░░░░░░░░░░░░░░░  12.8s (5%)           │    │
│  │ Restore    ██████████████████████░░░  180.5s (69%)         │    │
│  │ Post-SQL   ██░░░░░░░░░░░░░░░░░░░░░░░   7.0s (3%)           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  Event Log                                                           │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 15:30:00  job_queued     Job submitted by jsmith            │    │
│  │ 15:30:05  job_started    Worker w-001 claimed job           │    │
│  │ 15:30:05  download_start Downloading from s3://...          │    │
│  │ 15:30:50  download_done  Downloaded 1.2 GB in 45s           │    │
│  │ 15:31:03  extract_done   Extracted to staging               │    │
│  │ 15:34:23  restore_done   myloader completed                 │    │
│  │ 15:34:28  post_sql_done  Post-SQL scripts executed          │    │
│  │ 15:34:28  job_completed  Restore successful                 │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### Real-Time Updates

- Job detail page auto-refreshes every 5 seconds while job is active
- Event log updates in real-time
- Progress bar shows current operation

### Canceling Jobs

Click **Cancel** to request job cancellation:
- Queued jobs are canceled immediately
- Running jobs complete their current operation then stop
- Canceled jobs cannot be resumed

---

## Manager Features

Users with `MANAGER` role see additional navigation options.

### Team Dashboard

View jobs submitted by team members:

```
┌─────────────────────────────────────────────────────────────────────┐
│ Team Jobs                                                            │
├─────────────────────────────────────────────────────────────────────┤
│  Team Members: alice, bob, charlie                                   │
│                                                                       │
│  [Filter by member ▼]  [Date range ▼]                               │
│                                                                       │
│ │ Member  │ Active │ Completed │ Failed │ Last Activity        │   │
│ ├─────────┼────────┼───────────┼────────┼──────────────────────┤   │
│ │ alice   │ 2      │ 15        │ 1      │ 5 minutes ago        │   │
│ │ bob     │ 0      │ 23        │ 0      │ 2 hours ago          │   │
│ │ charlie │ 1      │ 8         │ 2      │ 10 minutes ago       │   │
└─────────────────────────────────────────────────────────────────────┘
```

### Manager Permissions

- View all team member jobs
- Cancel team member jobs
- Cannot modify team membership (Admin only)

---

## Admin Features

Users with `ADMIN` role have full system access.

### Admin Dashboard

```
┌─────────────────────────────────────────────────────────────────────┐
│ Administration                                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  System Status                                                       │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐        │
│  │ Workers: 3/3   │  │ Queue: 5 jobs  │  │ Uptime: 7d 4h  │        │
│  └────────────────┘  └────────────────┘  └────────────────┘        │
│                                                                       │
│  Quick Actions                                                       │
│  [Manage Users]  [Manage Hosts]  [System Settings]  [Audit Log]    │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### User Management

- Create/disable user accounts
- Assign roles (USER, MANAGER, ADMIN)
- Force password reset
- View login history

### Host Management

- Add/remove database hosts
- Enable/disable hosts for restore targets
- Configure host aliases

### System Settings

- Default database host
- Session timeout
- Maintenance mode
- Rate limiting

### Audit Log

- View all system changes
- Filter by user, action type, date
- Export audit data

---

## Keyboard Navigation

| Shortcut | Action |
|----------|--------|
| `Esc` | Close sidebar/modal/dialog |
| `Tab` | Navigate between form fields |
| `Enter` | Submit forms, activate buttons |
| `Arrow Keys` | Navigate dropdown options, table rows |

> **Note**: Additional keyboard shortcuts for page navigation may be added in future releases.

---

## Troubleshooting

### "Session Expired" Message

Your session has timed out. Log in again to continue.

### Jobs Not Appearing

- Refresh the page
- Check your filters (status, user, host)
- Verify you have permission to view the job

### Cannot Cancel Job

- Only queued or running jobs can be canceled
- You can only cancel your own jobs (or team jobs if Manager)
- Admins can cancel any job

### Page Not Loading

1. Check your network connection
2. Verify the pullDB service is running
3. Contact your administrator

---

## See Also

- [API Reference](api-reference.md) - REST API documentation
- [CLI Reference](cli-reference.md) - Command-line interface
- [Getting Started](getting-started.md) - Installation guide
