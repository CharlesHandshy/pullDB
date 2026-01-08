# Release Notes v1.0.1

**Release Date**: January 8, 2026  
**Type**: Feature Release with Critical Bug Fixes

## Summary

This release adds the skip database drops feature for handling jobs with inaccessible hosts, fixes critical state machine bugs in job deletion, and improves hostname display clarity in the CLI and API.

## 🎉 New Features

### Skip Database Drops
- **UI Checkbox**: Added "Skip database drops" option in bulk delete modal
- **Backend Parameter**: Full-stack implementation of `skip_database_drops` flag
- **Use Cases**: 
  - Decommissioned database hosts
  - Network failures preventing host access
  - Emergency cleanup when databases already gone
  - Test hosts temporarily unavailable
- **Documentation**: Complete feature documentation in `.pulldb/SKIP-DATABASE-DROPS-FEATURE.md`

### Force-Complete Delete Endpoint
- **Admin Endpoint**: `POST /web/admin/jobs/{job_id}/force-complete-delete`
- **Purpose**: Manually complete stuck job deletions when host unavailable
- **Audit Trail**: All force-completions logged with admin user and reason

### Enhanced Hostname Display
- **API Resolution**: `/api/hosts` now resolves actual database endpoints from AWS Secrets Manager
- **CLI Clarity**: `pulldb hosts` shows real RDS endpoints instead of short aliases
- **Backward Compatible**: Users can still reference by alias or full hostname

## 🐛 Critical Bug Fixes

### State Machine Integrity
**Issue**: Jobs could exceed MAX_DELETE_RETRY_COUNT (5) due to invalid state transitions
- Web endpoint now blocks re-deletion of FAILED jobs
- Admin bulk delete blocks re-deletion of FAILED and DELETING jobs
- Graceful degradation for missing hosts (immediate delete, no retry)

**Root Cause**: Delete endpoints allowed re-deletion of jobs in 'failed' status, causing `mark_job_deleting()` to increment retry_count beyond max (5 → 6)

**Fix Details**:
- [pulldb/web/features/jobs/routes.py](pulldb/web/features/jobs/routes.py#L743-L746): Block FAILED jobs at web endpoint
- [pulldb/worker/admin_tasks.py](pulldb/worker/admin_tasks.py#L755-L773): Block FAILED/DELETING in bulk delete
- [pulldb/worker/cleanup.py](pulldb/worker/cleanup.py#L784-L812): Immediate delete for missing hosts

### Atomic Rename Procedure Packaging
- **Issue**: Procedure SQL file not included in debian package
- **Fix**: Added `docs/hca/features/atomic_rename_procedure.sql` to package
- **Impact**: Ensures atomic rename auto-deployment works in production

## 🔧 Enhancements

### Maintenance Credentials
- New `get_host_credentials_for_maintenance()` method
- Allows deletion operations on disabled hosts
- Graceful handling when host deleted from `db_hosts` table

### Documentation
- `.pulldb/BUGFIX-DELETE-RETRY-LIMIT.md` - Comprehensive state machine fix documentation
- `.pulldb/FORCE-DELETE-UI-NOTES.md` - Force-complete delete feature guide
- `.pulldb/HOSTNAME-DISPLAY-FIX.md` - Hostname display enhancement details
- `.pulldb/SKIP-DATABASE-DROPS-FEATURE.md` - Complete feature documentation
- `scripts/apply_hostname_fix.sh` - Database hostname correction script

## 📦 Package Details

- **Debian Package**: `pulldb_1.0.1_amd64.deb` (12M)
- **Python Wheel**: `pulldb-1.0.1-py3-none-any.whl` (11M)
- **Included**: 
  - myloader-0.19.3-3 binary
  - 37 schema files
  - Atomic rename procedure SQL
  - After-SQL templates

## 🔄 Upgrade Instructions

### Debian Package Upgrade
```bash
# Download and install
sudo dpkg -i pulldb_1.0.1_amd64.deb

# Restart services
sudo systemctl restart pulldb-api
sudo systemctl restart pulldb-web
sudo systemctl restart pulldb-worker@{1,2,3}
```

### Development Environment
```bash
cd /path/to/pullDB
git pull origin main
git checkout v1.0.1
./scripts/dev-rebuild.sh
```

## ⚠️ Breaking Changes

None. This release is fully backward compatible with v1.0.0.

## 🧪 Testing Recommendations

1. **Skip Database Drops**: 
   - Navigate to jobs list → select jobs → bulk delete → check "Skip database drops"
   - Verify jobs transition to deleted without host access attempts

2. **State Machine**: 
   - Attempt to re-delete a FAILED job → should show error message
   - Verify retry_count never exceeds MAX_DELETE_RETRY_COUNT

3. **Hostname Display**: 
   - Run `pulldb hosts` → verify actual RDS endpoints shown
   - Check web UI shows correct hostnames

## 📊 Validation

- ✅ All 5 services active (api, web, worker@1, worker@2, worker@3)
- ✅ State machine blocks invalid transitions
- ✅ Skip database drops flows through entire stack
- ✅ UI checkbox renders correctly
- ✅ Graceful degradation for missing hosts
- ✅ Hostname resolution from AWS Secrets Manager

## 🔗 Related Issues

- Jobs stuck in 'deleting' when hosts removed from system
- retry_count exceeding MAX_DELETE_RETRY_COUNT
- Hostname display confusion in CLI output

## 📝 Contributors

- CharlesHandshy - All features and fixes

---

**Full Changelog**: https://github.com/CharlesHandshy/pullDB/compare/v1.0.0...v1.0.1
