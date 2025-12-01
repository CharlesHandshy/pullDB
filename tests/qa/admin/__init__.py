"""
pulldb-admin CLI Test Suite

Tests for administrative commands that run on the server.
These commands have direct MySQL access (unlike pulldb-client).

Test Modules:
- test_jobs.py: Jobs management (list, cancel)
- test_hosts.py: Database host management (list, add, enable, disable)
- test_users.py: User management (list, enable, disable, show)
- test_settings.py: Settings management (list, get, set, reset, push, pull, diff)
- test_cleanup.py: Cleanup orphaned resources
- test_common.py: Common CLI behavior (help, version, errors)
"""
