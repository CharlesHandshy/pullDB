# Audit Logging & Disallowed Users Implementation Plan

> **Status**: ✅ Complete  
> **Started**: 2025-12-29  
> **Completed**: 2025-12-29

## Overview

Two-phase implementation:
1. **Phase 1**: Fix audit logging bugs and add missing audit coverage (22 gaps) ✅
2. **Phase 2**: Implement disallowed users feature with audit trail ✅

---

## Phase 1: Audit Logging Remediation

### 1.1 Bug Fixes
| Task | File | Status |
|------|------|--------|
| Fix `job_repo.add_audit_log()` → `audit_repo.log_action()` | `pulldb/web/features/jobs/routes.py` | ✅ Done |

### 1.2 User Management Audit (8 operations)
| Action | Location | Status |
|--------|----------|--------|
| `user_created` | `admin/routes.py` POST `/admin/users` | ✅ Done |
| `user_enabled` | `admin/routes.py` POST `/admin/users/{id}/enable` | ✅ Done |
| `user_disabled` | `admin/routes.py` POST `/admin/users/{id}/disable` | ✅ Done |
| `role_changed` | `admin/routes.py` POST `/admin/users/{id}/role` | ✅ Done |
| `manager_assigned` | `admin/routes.py` POST `/admin/users/{id}/manager` | ✅ Done |
| `user_deleted` | `admin/routes.py` DELETE `/admin/users/{id}` | ✅ Done |
| `force_password_reset` | `admin/routes.py` POST `/admin/users/{id}/force-password-reset` | ✅ Done |
| `user_hosts_updated` | `admin/routes.py` POST `/admin/users/{id}/hosts` | ✅ Done |

### 1.3 Job Operations Audit (3 operations)
| Action | Location | Status |
|--------|----------|--------|
| `job_submitted` | `api/logic.py` `enqueue_job()` | ✅ Done |
| `job_canceled` | `jobs/routes.py` POST `/jobs/{id}/cancel` | ✅ Done |
| `job_delete_requested` | `jobs/routes.py` DELETE `/jobs/{id}` | ✅ Done |

### 1.4 Host Management Audit (8 operations)
| Action | Location | Status |
|--------|----------|--------|
| `host_created` | `admin/routes.py` POST `/admin/hosts` | ✅ Done |
| `host_updated` | `admin/routes.py` PUT `/admin/hosts/{id}` | ✅ Done |
| `host_deleted` | `admin/routes.py` DELETE `/admin/hosts/{id}` | ✅ Done |
| `host_enabled` | `admin/routes.py` POST `/admin/hosts/{id}/enable` | ✅ Done |
| `host_disabled` | `admin/routes.py` POST `/admin/hosts/{id}/disable` | ✅ Done |
| `host_toggled` | `admin/routes.py` POST `/admin/hosts/{id}/toggle` | ✅ Done |
| `host_secret_updated` | `admin/routes.py` POST `/admin/hosts/{id}/secret` | ✅ Done |
| `host_provisioned` | `admin/routes.py` POST `/admin/hosts/{id}/provision` | ✅ Done |

### 1.5 Manager Operations Audit (4 operations)
| Action | Location | Status |
|--------|----------|--------|
| `team_user_enabled` | `manager/routes.py` POST `/my-team/{id}/enable` | ✅ Done |
| `team_user_disabled` | `manager/routes.py` POST `/my-team/{id}/disable` | ✅ Done |
| `team_password_reset` | `manager/routes.py` POST `/my-team/{id}/force-password-reset` | ✅ Done |
| `team_password_reset_cleared` | `manager/routes.py` POST `/my-team/{id}/clear-password-reset` | ✅ Done |

---

## Phase 2: Disallowed Users Feature

### 2.1 Domain Layer
| Task | File | Status |
|------|------|--------|
| Add `DISALLOWED_USERS_HARDCODED` frozenset | `pulldb/domain/validation.py` | ✅ Done |
| Add `MIN_USERNAME_LENGTH = 6` constant | `pulldb/domain/validation.py` | ✅ Done |
| Add `validate_username_format()` function | `pulldb/domain/validation.py` | ✅ Done |
| Add `validate_username_not_disallowed()` function | `pulldb/domain/validation.py` | ✅ Done |

### 2.2 Database Layer
| Task | File | Status |
|------|------|--------|
| Create migration `081_disallowed_users.sql` | `schema/pulldb_service/` | ✅ Done |
| Add `DisallowedUser` dataclass | `pulldb/infra/mysql.py` | ✅ Done |
| Add `DisallowedUserRepository` class | `pulldb/infra/mysql.py` | ✅ Done |
| Add `get_disallowed_user_repository()` factory | `pulldb/infra/factory.py` | ✅ Done |

### 2.3 API Layer
| Task | File | Status |
|------|------|--------|
| Add validation in `/api/auth/register` | `pulldb/api/main.py` | ✅ Done |
| Add `GET /api/disallowed-users` | `pulldb/web/features/admin/routes.py` | ✅ Done |
| Add `POST /api/disallowed-users` | `pulldb/web/features/admin/routes.py` | ✅ Done |
| Add `DELETE /api/disallowed-users/{username}` | `pulldb/web/features/admin/routes.py` | ✅ Done |

### 2.4 CLI Layer
| Task | File | Status |
|------|------|--------|
| Add `disallow_group` Click group | `pulldb/cli/admin_commands.py` | ✅ Done |
| Add `pulldb-admin disallow list` | `pulldb/cli/admin_commands.py` | ✅ Done |
| Add `pulldb-admin disallow add` | `pulldb/cli/admin_commands.py` | ✅ Done |
| Add `pulldb-admin disallow remove` | `pulldb/cli/admin_commands.py` | ✅ Done |
| Register disallow_group in CLI | `pulldb/cli/admin.py` | ✅ Done |

### 2.5 Web UI Layer
| Task | File | Status |
|------|------|--------|
| Create disallowed users management page | `pulldb/web/templates/features/admin/disallowed_users.html` | ✅ Done |
| Add `GET /disallowed-users` page route | `pulldb/web/features/admin/routes.py` | ✅ Done |
| Add breadcrumb entry | `pulldb/web/widgets/breadcrumbs/__init__.py` | ✅ Done |
| Add quick link in admin dashboard | `pulldb/web/templates/features/admin/admin.html` | ✅ Done |

---

## Hardcoded Disallowed Users List

Standard Ubuntu/Linux system accounts + service accounts (~30):

```
root, daemon, bin, sys, sync, games, man, lp, mail, news, uucp, proxy,
www-data, backup, list, irc, gnats, nobody, systemd-network, systemd-resolve,
systemd-timesync, messagebus, syslog, _apt, tss, uuidd, tcpdump, avahi-autoipd,
usbmux, rtkit, dnsmasq, cups-pk-helper, speech-dispatcher, avahi, kernoops,
saned, nm-openvpn, hplip, whoopsie, colord, geoclue, pulse, gnome-initial-setup,
gdm, sssd, mysql, postgres, redis, nginx, ubuntu
```

---

## Notes

- **Hardcoded accounts**: Always blocked, cannot be overridden via DB
- **DB accounts**: Extend hardcoded list, can be added/removed by admins
- **Case sensitivity**: All comparisons done lowercase
- **Audit**: All add/remove operations logged to `audit_logs` table
