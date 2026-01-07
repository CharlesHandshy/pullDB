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
- [API Key Authentication](#api-key-authentication)
- [CLI Authentication](#cli-authentication)
- [Troubleshooting](#troubleshooting)

---

## Overview

pullDB supports three authentication methods that can be used independently or together:

| Method | Use Case | Identity Source |
|--------|----------|-----------------|
| **API Key** | CLI from multiple hosts | HMAC-signed `X-API-Key` header |
| **Trusted Header** | Legacy CLI via SSH | `X-Pulldb-User` header |
| **Session Cookie** | Web UI | Username/password → cookie |

The authentication mode is configured via `PULLDB_AUTH_MODE`:

```bash
# Accept all methods (recommended)
PULLDB_AUTH_MODE=both

# Session-only (web-only deployments)
PULLDB_AUTH_MODE=session

# Trusted-only (internal CLI only, deprecated)
PULLDB_AUTH_MODE=trusted
```

> **Note**: API Key authentication is the preferred method for CLI access.
> It provides per-host authorization with admin approval workflow.

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

## API Key Authentication

pullDB uses HMAC-signed API keys for secure CLI authentication across multiple hosts. Each key is tied to a specific host and requires admin approval before use.

### How API Key Auth Works

```
┌──────────────────────────────────────────────────────────────────┐
│  CLI Request with API Key                                         │
│                                                                   │
│  1. User runs: pulldb status                                     │
│                                                                   │
│  2. CLI reads stored key from: ~/.pulldb/<api_url_hash>/key      │
│                                                                   │
│  3. CLI signs request:                                           │
│     X-API-Key: abc123...                                         │
│     X-Timestamp: 1737123456                                      │
│     X-Signature: HMAC-SHA256(method|path|timestamp)              │
│                                                                   │
│  4. Server validates signature, timestamp, and key status        │
│                                                                   │
│  5. Request proceeds as authenticated user                       │
└──────────────────────────────────────────────────────────────────┘
```

### Getting Your API Key

#### New User Registration

When you register a new account, an API key is automatically requested:

```bash
$ pulldb register
Enter username: jsmith
Enter password: 
Confirm password: 
✓ Account created successfully
  Username: jsmith
  Status: Pending admin approval

⚠ Your API key is pending approval.
Contact an administrator to approve your key, then CLI will work.
```

#### Requesting Key for New Host

If you already have an account but need CLI access from a new machine:

```bash
$ pulldb request-host-key
✓ API key requested for host: devserver
  Key ID: abc12345...
  Status: Pending admin approval

Contact an administrator to approve your key.
```

### Key Status and Errors

| Status | CLI Behavior |
|--------|--------------|
| **pending** | Returns 401 with "pending approval" message |
| **approved** | Request proceeds normally |
| **revoked** | Returns 401 with "key revoked" message |

Example pending key error:
```
$ pulldb status
Error: API key pending approval (key: abc12345)
Contact an administrator to approve your key.
```

### Viewing Your Keys

```bash
# List all your registered hosts
pulldb hosts

Registered Hosts:
  devserver     Created: 2025-01-18  Status: approved
  laptop        Created: 2025-01-20  Status: pending
```

### Security Features

- **HMAC-SHA256 signatures**: Requests are cryptographically signed
- **Timestamp validation**: ±5 minute window prevents replay attacks
- **Per-host keys**: Separate key for each machine
- **IP tracking**: Registration and usage IPs logged
- **Admin approval**: No auto-approval, requires human review

### Key Storage

API keys are stored locally in `~/.pulldb/<api_url_hash>/`:
- `key` - The API key ID
- `secret` - The HMAC signing secret

```bash
# Key storage location (example)
~/.pulldb/a1b2c3d4/key     # API key ID
~/.pulldb/a1b2c3d4/secret  # Signing secret
```

---

## CLI Authentication

The CLI supports two authentication methods: **API Key** (recommended) and **Trusted Header** (legacy).

### API Key Method (Recommended)

This is the default and preferred method. See [API Key Authentication](#api-key-authentication) above for details.

```bash
# Register and get API key
pulldb register

# Or request key for existing account on new host
pulldb request-host-key

# After admin approval, CLI commands work automatically
pulldb status
```

### Trusted Header Method (Legacy)

For internal deployments without API key infrastructure, the CLI can use trusted header authentication:

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

### "API key pending approval"

- Your API key was created but hasn't been approved yet
- Contact an administrator to approve your key
- Check status: `pulldb hosts`
- Admin command: `pulldb-admin keys approve <key_id>`

### "API key revoked"

- Your API key has been revoked by an administrator
- Request a new key: `pulldb request-host-key`
- Contact your admin to understand why it was revoked

### "API key required for this host"

- You don't have an API key for this machine
- Run: `pulldb request-host-key`
- Wait for admin approval

### "Invalid API key"

- Key doesn't exist in database
- May have been deleted or corrupted
- Request new key: `pulldb request-host-key`

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
