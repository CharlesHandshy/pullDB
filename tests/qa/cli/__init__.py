"""
pullDB CLI QA Test Suite

This package contains comprehensive CLI tests for the pullDB command-line interface.

Test Categories:
1. test_version.py - Basic command execution (version, help)
2. test_restore.py - Restore command functionality
3. test_search.py - Search command functionality
4. test_status.py - Status command functionality
5. test_history.py - History command functionality
6. test_events.py - Events command functionality
7. test_profile.py - Profile command functionality
8. test_cancel.py - Cancel command functionality
9. test_common.py - Common patterns and edge cases

Usage:
    pytest tests/qa/cli/ -v                    # Run all CLI tests
    pytest tests/qa/cli/test_version.py -v    # Run specific category
    pytest tests/qa/cli/ -k "restore" -v      # Run tests matching pattern
"""
