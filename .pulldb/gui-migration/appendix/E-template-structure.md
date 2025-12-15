# Appendix E — Target Template Structure

> Final structure after all PRs complete.

---

## templates/

```
templates/
├── base.html                         # KEEP (shared layout)
│
├── features/
│   ├── admin/
│   │   ├── index.html
│   │   ├── cleanup.html
│   │   ├── cleanup_preview.html
│   │   ├── hosts.html
│   │   ├── host_detail.html
│   │   ├── jobs.html
│   │   ├── logo.html
│   │   ├── maintenance.html
│   │   ├── orphan_preview.html
│   │   ├── prune_preview.html
│   │   ├── settings.html            # + Appearance section
│   │   ├── styleguide.html
│   │   ├── users.html
│   │   └── user_detail.html
│   │
│   ├── audit/
│   │   ├── index.html
│   │   ├── my_actions.html
│   │   └── on_me.html
│   │
│   ├── auth/
│   │   ├── login.html               # Enhanced, no Bootstrap
│   │   ├── profile.html
│   │   └── change_password.html
│   │
│   ├── dashboard/
│   │   ├── dashboard.html
│   │   ├── _admin_dashboard.html    # Icon stat cards
│   │   ├── _manager_dashboard.html
│   │   └── _user_dashboard.html
│   │
│   ├── jobs/
│   │   ├── index.html
│   │   ├── detail.html              # Was my_job.html
│   │   ├── details.html
│   │   ├── history.html
│   │   ├── my_jobs.html
│   │   ├── profile.html
│   │   └── search.html
│   │
│   ├── manager/
│   │   ├── index.html
│   │   ├── create_user.html
│   │   ├── my_team.html
│   │   ├── submit_for_user.html
│   │   └── user_detail.html
│   │
│   ├── restore/
│   │   ├── restore.html             # + QA Template support
│   │   └── partials/
│   │
│   ├── search/
│   │   └── index.html
│   │
│   └── shared/
│       └── error.html
│
├── partials/
│   ├── icons/                       # NEW: HCA icon macros
│   │   ├── _index.html
│   │   ├── shared.html
│   │   ├── entities.html
│   │   ├── features.html
│   │   ├── widgets.html
│   │   └── pages.html
│   │
│   ├── breadcrumbs.html
│   ├── active_jobs.html
│   ├── filter_bar.html
│   ├── job_events.html
│   ├── job_row.html
│   └── searchable_dropdown.html
│
└── widgets/
    ├── lazy_table/
    ├── sidebar/
    └── theme_toggle/                # NEW: theme toggle
```

---

## Deleted After Migration

These files/folders will be removed:

```
# Root templates (moved or deleted)
templates/login.html           # DELETE (Bootstrap version)
templates/index.html           # DELETE (legacy dashboard)
templates/restore.html         # DELETE (duplicate)
templates/my_job.html          # MOVED → features/jobs/
templates/my_jobs.html         # MOVED → features/jobs/
templates/job_profile.html     # MOVED → features/jobs/
templates/job_history.html     # MOVED → features/jobs/
templates/search.html          # MOVED → features/search/
templates/error.html           # MOVED → features/shared/

# Old folders (contents moved)
templates/admin/               # DELETE entire folder
templates/manager/             # DELETE entire folder
templates/audit/               # DELETE entire folder
```

---

## Validation Command

After all PRs, run:

```bash
# Should only show base.html
ls pulldb/web/templates/*.html

# Should show 0
find pulldb/web/templates -maxdepth 1 -name "*.html" ! -name "base.html" | wc -l
```
