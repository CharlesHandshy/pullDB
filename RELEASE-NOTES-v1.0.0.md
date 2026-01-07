# Release Notes - v1.0.0

**Release Date**: 2026-01-07  
**Type**: Major Release - Multi-Host API Keys & Production Ready

---

## Highlights

This release introduces a **multi-host API key system** enabling users to authenticate from multiple machines, along with comprehensive admin tools for key management. This marks the first production-ready release of pullDB.

---

## New Features

### Multi-Host API Key System

Users can now register and authenticate from multiple machines:

- **One user, many machines**: Each machine gets its own API key tied to hostname
- **Approval workflow**: New keys start as "pending" until an admin approves them
- **Host tracking**: Records hostname, IP address, and usage statistics per key
- **Key lifecycle**: Keys can be approved, revoked, reactivated, or removed

### Admin API Key Management

New "API Keys" tab in the Users management modal:

| Action | Description |
|--------|-------------|
| **View** | See all keys for a user with hostname, status, dates, last used |
| **Approve** | Activate pending keys for new machine registrations |
| **Revoke** | Disable active keys (soft delete - can be reactivated) |
| **Reactivate** | Re-enable previously revoked keys |
| **Remove** | Permanently delete a key (hard delete) |

### Unified CLI Registration

The `pulldb register` command now handles all registration scenarios:

| Scenario | Behavior |
|----------|----------|
| **New user** | Creates account + API key for this host |
| **Existing user, new machine** | Requests new API key for this host |
| **Revoked key** | Prompts to request new key |
| **Deleted key** | Detected and prompts re-registration |

The standalone `request-host-key` command has been removed - `pulldb register` handles everything.

### Improved Error Detection

The CLI now accurately detects and reports API key states:

- **Pending approval**: "Your API key is pending approval. Contact an administrator."
- **Key revoked**: "Your API key has been revoked. Run `pulldb register` to request a new key."
- **Key deleted**: "This machine is not registered. Run `pulldb register`."
- **Invalid credentials**: Clear messaging with recovery instructions

---

## Database Schema Changes

### New: `api_keys` Table Columns

| Column | Type | Description |
|--------|------|-------------|
| `hostname` | VARCHAR(255) | Machine hostname where key was created |
| `registered_ip` | VARCHAR(45) | IP address at registration time |
| `last_used_ip` | VARCHAR(45) | Most recent IP address used |
| `last_used_at` | DATETIME(6) | Timestamp of most recent API call |
| `approved_at` | DATETIME(6) | When key was approved (NULL = pending) |

Migration: `schema/pulldb_service/00716_api_keys_host_tracking.sql`

---

## Documentation Updates

- CLI reference updated for unified `register` command
- Help pages reflect new registration workflow
- Admin guide includes API key management section
- New annotated screenshots for admin UI features

---

## Breaking Changes

### Removed Commands

| Command | Replacement |
|---------|-------------|
| `pulldb request-host-key` | `pulldb register` (handles both cases) |

### API Changes

- `POST /api/auth/register` now handles both new users and existing users on new machines
- `DELETE /web/admin/api-keys/{key_id}` - New endpoint for hard-deleting keys

---

## Upgrade Instructions

### From v0.0.10

```bash
# For .deb installations
sudo systemctl stop pulldb-api pulldb-worker pulldb-web
sudo apt update
sudo apt install --only-upgrade pulldb
sudo systemctl start pulldb-api pulldb-worker pulldb-web

# Database migration runs automatically during package install
```

### For Development

```bash
git fetch --tags
git checkout v1.0.0
pip install -e .

# Apply schema migration if needed
mysql -u root pulldb < schema/pulldb_service/00716_api_keys_host_tracking.sql
```

---

## Client Updates

Users with existing API keys continue to work unchanged. However:

1. **Multi-machine users**: Can now register additional machines with `pulldb register`
2. **Revoked keys**: Will see clear messaging and instructions to re-register
3. **Deleted keys**: Automatically detected with recovery instructions

---

## Known Issues

None at this time.

---

## Contributors

- Charles Handshy

---

## Full Changelog

See commit history: `git log v0.0.10..v1.0.0 --oneline`
