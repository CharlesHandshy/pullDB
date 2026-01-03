# pullDB Authentication Guide

> **Complete guide to authentication, registration, and session management**
>
> This guide covers the Phase 4 authentication features including password-based
> login, user registration, session management, and the CLI authentication flow.

## Table of Contents

- [Overview](#overview)
- [Authentication Modes](#authentication-modes)
- [User Registration](#user-registration)
- [Password Management](#password-management)
- [Session-Based Authentication](#session-based-authentication)
- [CLI Authentication](#cli-authentication)
- [Troubleshooting](#troubleshooting)

---

## Overview

pullDB supports two authentication methods that can be used independently or together:

| Method | Use Case | Identity Source |
|--------|----------|-----------------|
| **Trusted Header** | CLI via SSH | `X-Pulldb-User` header |
| **Session Cookie** | Web UI | Username/password → cookie |

The authentication mode is configured via `PULLDB_AUTH_MODE`:

```bash
# Accept both methods (recommended)
PULLDB_AUTH_MODE=both

# Session-only (web-only deployments)
PULLDB_AUTH_MODE=session

# Trusted-only (internal CLI only)
PULLDB_AUTH_MODE=trusted
```

---

## Authentication Modes

### Both Mode (Default)

In `both` mode, the API accepts either authentication method:

1. **Session Cookie**: If a valid `session_token` cookie is present, use it
2. **Trusted Header**: If `X-Pulldb-User` header is present, trust it
3. **Anonymous**: If neither, request is unauthenticated (may be rejected)

```python
# Priority order in both mode:
# 1. Session cookie (if valid)
# 2. X-Pulldb-User header (if present)
# 3. Anonymous (401 Unauthorized for protected routes)
```

### Session Mode

In `session` mode, only cookie-based authentication is accepted:

- `X-Pulldb-User` header is **ignored**
- All API access requires login
- Used for web-only deployments or external access

### Trusted Mode

In `trusted` mode, only header-based authentication is accepted:

- No password required
- User must be SSH'd into the server
- CLI sends username automatically
- Used for internal-only deployments

---

## User Registration

### Web UI Registration

1. Navigate to the login page
2. Click "Register" link
3. Fill in the registration form:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Create Account                               │
│                                                                   │
│  Username *                                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ jsmith                                                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Password *                                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ ••••••••••••                                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Confirm Password *                                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ ••••••••••••                                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  [  Create Account  ]                                            │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### CLI Registration

Register a new account from the command line:

```bash
# Interactive registration
pulldb register

# With username specified
pulldb register --username jsmith

# Non-interactive (prompts for password)
pulldb register --username jsmith --password
```

Example session:

```
$ pulldb register
Enter username: jsmith
Enter password: 
Confirm password: 
✓ Account created successfully
  Username: jsmith
  User Code: jsmith

You can now use 'pulldb' commands.
```

### API Registration

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "jsmith",
    "password": "securepassword123"
  }'
```

Response:
```json
{
  "user_id": "usr_abc123",
  "username": "jsmith",
  "message": "User registered successfully"
}
```

### Registration Requirements

| Field | Requirements |
|-------|-------------|
| Username | 3-50 characters, alphanumeric + underscore |
| Password | Minimum 8 characters |
| User Code | Auto-generated from username |

### Username Restrictions

Certain usernames are blocked:

```python
BLOCKED_USERNAMES = [
    'admin', 'administrator', 'root', 'system',
    'pulldb', 'api', 'worker', 'service',
    # ... see admin guide for full list
]
```

---

## Password Management

### Setting Password (First Time)

If you have a username but no password (created by admin), set one:

```bash
# CLI
pulldb set-password

# Or with username
pulldb set-password --username jsmith
```

### Changing Password

#### Web UI

1. Login to web UI
2. Navigate to Settings → Security
3. Enter current and new password

#### CLI

```bash
pulldb set-password --change
```

#### API

```bash
curl -X POST http://localhost:8000/api/auth/change-password \
  -H "Content-Type: application/json" \
  -d '{
    "username": "jsmith",
    "current_password": "oldpassword",
    "new_password": "newsecurepassword"
  }'
```

### Password Reset (Admin)

Administrators can force a password reset:

```bash
# Force user to set new password on next login
pulldb-admin users force-reset jsmith
```

### Password Storage

- Passwords are hashed using **bcrypt** with cost factor 12
- Salt is automatically generated and stored with hash
- Raw passwords are never stored or logged

---

## Session-Based Authentication

### Login Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                   │
│  1. User submits credentials                                     │
│     POST /web/login                                              │
│     {username, password}                                         │
│                                    ▼                              │
│  2. Server validates                                             │
│     - Lookup user by username                                    │
│     - Verify password (bcrypt)                                   │
│     - Check user not disabled                                    │
│                                    ▼                              │
│  3. Create session                                               │
│     - Generate 32-byte token                                     │
│     - Hash with SHA-256 for storage                              │
│     - Insert into sessions table                                 │
│                                    ▼                              │
│  4. Set cookie                                                   │
│     Set-Cookie: session_token=abc123...; HttpOnly; SameSite=Lax │
│                                    ▼                              │
│  5. Redirect to dashboard                                        │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Session Properties

| Property | Value | Description |
|----------|-------|-------------|
| Token Length | 32 bytes | 64 hex characters |
| Storage | SHA-256 hash | Never store raw token |
| Default TTL | 24 hours | Configurable |
| Cookie Flags | HttpOnly, SameSite=Lax | Security headers |

### Session Configuration

```bash
# Session timeout in hours (default: 24)
PULLDB_SESSION_TTL_HOURS=24

# For longer sessions (7 days)
PULLDB_SESSION_TTL_HOURS=168
```

### Logout

#### Web UI

Click the logout link in the sidebar.

#### API

```bash
curl -X POST http://localhost:8000/web/logout \
  -b "session_token=abc123..."
```

This invalidates the session token and clears the cookie.

---

## CLI Authentication

### How CLI Authentication Works

The CLI uses **trusted header** authentication when running on the same network:

```
┌──────────────────────────────────────────────────────────────────┐
│ Developer Machine                                                 │
│                                                                   │
│  $ ssh devserver                                                 │
│  $ whoami                                                        │
│  jsmith                                                          │
│                                                                   │
│  $ pulldb restore acme_pest                                      │
│                     │                                             │
│                     ▼                                             │
│  CLI reads $USER environment variable                            │
│  CLI sends: X-Pulldb-User: jsmith                                │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### CLI Configuration

The CLI reads the API URL from environment or config:

```bash
# Set API endpoint
export PULLDB_API_URL=http://pulldb-server:8000

# Or in ~/.pulldb/config
[api]
url = http://pulldb-server:8000
```

### First-Time CLI Setup

When running `pulldb` for the first time:

1. CLI checks if user exists in database
2. If not, prompts to register or set password

```
$ pulldb status

Welcome to pullDB!

Your username 'jsmith' was found but has no password set.
Please set a password to continue.

Enter new password: 
Confirm password: 
✓ Password set successfully

[Active Jobs: 0] [Queued: 2]
```

### Using CLI with Session Auth

For session-based auth from CLI (e.g., remote access):

```bash
# Login and save token
pulldb login
Username: jsmith
Password: 

# Token saved to ~/.pulldb/session

# Subsequent commands use saved session
pulldb status
```

---

## Troubleshooting

### "Invalid username or password"

- Verify username is correct (case-sensitive)
- Check if account is disabled
- Try password reset if forgotten

### "Session expired"

- Session has exceeded TTL (default 24 hours)
- Login again to get new session
- Check `PULLDB_SESSION_TTL_HOURS` setting

### "User not found"

- Username doesn't exist in database
- Register first: `pulldb register`
- Or ask admin to create account

### "Account disabled"

- Your account has been disabled by an administrator
- Contact your admin to re-enable

### "Password reset required"

- Admin has forced a password reset
- You must set a new password before continuing

### CLI not sending credentials

Verify environment:

```bash
# Check username
echo $USER

# Check API URL
echo $PULLDB_API_URL

# Test with verbose
pulldb --verbose status
```

### Cookie not being set

Check browser settings:
- Cookies must be enabled
- Third-party cookie blockers may interfere
- Check browser developer tools → Network → Response headers

---

## See Also

- [Security Model](../widgets/security.md) - Full security architecture
- [API Reference](api-reference.md) - REST API documentation
- [Admin Guide](admin-guide.md) - User management for administrators
