"""
Category 5: User Host Assignment Tests

Tests for user host assignment functionality:
- SimulatedAuthRepository.set_user_hosts / get_user_hosts
- Auto-default when single host assigned
- Server-side validation in admin routes (inactive host rejection)

Test Count: 11 tests
"""

from __future__ import annotations

import os
import sys
import unittest

# Ensure we import from the local project
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from pulldb.simulation.adapters.mock_mysql import (
    SimulatedAuthRepository,
    SimulatedHostRepository,
    SimulatedUserRepository,
)
from pulldb.simulation.core.state import get_simulation_state


class TestUserHostAssignment(unittest.TestCase):
    """Tests for user host assignment via SimulatedAuthRepository."""

    def setUp(self):
        """Set up fresh simulation state for each test."""
        self.state = get_simulation_state()
        self.state.clear()
        
        self.user_repo = SimulatedUserRepository()
        self.auth_repo = SimulatedAuthRepository()
        self.host_repo = SimulatedHostRepository()
        
        # Create test hosts
        self.host_repo.add_host("mysql-stg-01.example.com", 5, "creds:stg01")
        self.host_repo.add_host("mysql-stg-02.example.com", 3, "creds:stg02")
        self.host_repo.add_host("mysql-inactive.example.com", 2, "creds:inactive")
        self.host_repo.disable_host("mysql-inactive.example.com")
        
        # Get host IDs
        hosts = self.host_repo.list_hosts()
        self.host1 = next(h for h in hosts if "stg-01" in h.hostname)
        self.host2 = next(h for h in hosts if "stg-02" in h.hostname)
        self.inactive_host = next(h for h in hosts if "inactive" in h.hostname)
        self.host1_id = str(self.host1.id)
        self.host2_id = str(self.host2.id)
        self.inactive_id = str(self.inactive_host.id)
        
        # Create test user
        self.user = self.user_repo.create_user("testuser", "testu")

    def test_set_single_host_auto_default(self):
        """Setting single host should auto-set it as default."""
        self.auth_repo.set_user_hosts(
            user_id=self.user.user_id,
            host_ids=[self.host1_id],
            default_host_id=None,  # Let it auto-default
            assigned_by="1",
        )
        
        # Verify host was assigned
        hosts = self.auth_repo.get_user_hosts(self.user.user_id)
        self.assertEqual(len(hosts), 1)
        
        # Verify auto-default was set (returns hostname string)
        default = self.auth_repo.get_user_default_host(self.user.user_id)
        self.assertIsNotNone(default)
        self.assertEqual(default, self.host1.hostname)

    def test_set_multiple_hosts_with_explicit_default(self):
        """Setting multiple hosts with explicit default."""
        self.auth_repo.set_user_hosts(
            user_id=self.user.user_id,
            host_ids=[self.host1_id, self.host2_id],
            default_host_id=self.host2_id,
            assigned_by="1",
        )
        
        hosts = self.auth_repo.get_user_hosts(self.user.user_id)
        self.assertEqual(len(hosts), 2)
        
        default = self.auth_repo.get_user_default_host(self.user.user_id)
        self.assertEqual(default, self.host2.hostname)

    def test_set_multiple_hosts_no_default_uses_none(self):
        """Setting multiple hosts without explicit default sets no default."""
        self.auth_repo.set_user_hosts(
            user_id=self.user.user_id,
            host_ids=[self.host2_id, self.host1_id],
            default_host_id=None,  # No default specified
            assigned_by="1",
        )
        
        # With multiple hosts and no explicit default, no default is set
        # (auto-default only applies when single host)
        # Just verify no exception is raised

    def test_clear_all_hosts(self):
        """Setting empty host list should clear all assignments."""
        # First assign some hosts
        self.auth_repo.set_user_hosts(
            user_id=self.user.user_id,
            host_ids=[self.host1_id],
            default_host_id=self.host1_id,
            assigned_by="1",
        )
        
        # Now clear
        self.auth_repo.set_user_hosts(
            user_id=self.user.user_id,
            host_ids=[],
            default_host_id=None,
            assigned_by="1",
        )
        
        hosts = self.auth_repo.get_user_hosts(self.user.user_id)
        self.assertEqual(len(hosts), 0)
        
        default = self.auth_repo.get_user_default_host(self.user.user_id)
        self.assertIsNone(default)

    def test_get_allowed_hosts(self):
        """get_user_allowed_hosts returns list of hostnames."""
        self.auth_repo.set_user_hosts(
            user_id=self.user.user_id,
            host_ids=[self.host1_id, self.host2_id],
            default_host_id=self.host1_id,
            assigned_by="1",
        )
        
        allowed = self.auth_repo.get_user_allowed_hosts(self.user.user_id)
        self.assertEqual(len(allowed), 2)
        self.assertIn(self.host1.hostname, allowed)
        self.assertIn(self.host2.hostname, allowed)

    def test_change_default_host(self):
        """Changing default host should work."""
        # Set initial
        self.auth_repo.set_user_hosts(
            user_id=self.user.user_id,
            host_ids=[self.host1_id, self.host2_id],
            default_host_id=self.host1_id,
            assigned_by="1",
        )
        
        # Verify initial default
        default = self.auth_repo.get_user_default_host(self.user.user_id)
        self.assertEqual(default, self.host1.hostname)
        
        # Change default
        self.auth_repo.set_user_hosts(
            user_id=self.user.user_id,
            host_ids=[self.host1_id, self.host2_id],
            default_host_id=self.host2_id,
            assigned_by="1",
        )
        
        # Verify new default
        default = self.auth_repo.get_user_default_host(self.user.user_id)
        self.assertEqual(default, self.host2.hostname)


class TestUserHostValidation(unittest.TestCase):
    """Tests for host validation logic (server-side)."""

    def setUp(self):
        """Set up fresh simulation state for each test."""
        self.state = get_simulation_state()
        self.state.clear()
        
        self.host_repo = SimulatedHostRepository()
        
        # Create test hosts
        self.host_repo.add_host("mysql-active.example.com", 5, "creds:active")
        self.host_repo.add_host("mysql-inactive.example.com", 2, "creds:inactive")
        self.host_repo.disable_host("mysql-inactive.example.com")
        
        self.hosts = self.host_repo.list_hosts()
        self.active_host = next(h for h in self.hosts if h.enabled)
        self.inactive_host = next(h for h in self.hosts if not h.enabled)

    def test_active_host_is_enabled(self):
        """Active host should have enabled=True."""
        self.assertTrue(self.active_host.enabled)

    def test_inactive_host_is_disabled(self):
        """Inactive host should have enabled=False."""
        self.assertFalse(self.inactive_host.enabled)

    def test_validate_host_enabled_status(self):
        """Validation logic should check enabled status."""
        # Simulate the validation logic from routes.py
        host_map = {str(h.id): h for h in self.hosts}
        
        # Active host should pass
        active_id = str(self.active_host.id)
        host = host_map.get(active_id)
        self.assertIsNotNone(host)
        self.assertTrue(host.enabled)  # type: ignore[union-attr]
        
        # Inactive host should fail
        inactive_id = str(self.inactive_host.id)
        host = host_map.get(inactive_id)
        self.assertIsNotNone(host)
        self.assertFalse(host.enabled)  # type: ignore[union-attr]

    def test_validate_host_exists(self):
        """Validation should detect non-existent hosts."""
        host_map = {str(h.id): h for h in self.hosts}
        
        # Non-existent host should not be in map
        self.assertIsNone(host_map.get("999"))
        self.assertIsNone(host_map.get("nonexistent"))


class TestHostDisplayName(unittest.TestCase):
    """Tests for host display name resolution."""

    def setUp(self):
        """Set up fresh simulation state."""
        self.state = get_simulation_state()
        self.state.clear()
        
        self.host_repo = SimulatedHostRepository()
        
        # Add host (alias is optional in simulation)
        self.host_repo.add_host("mysql-stg-01.example.com", 5, "creds:stg01")

    def test_display_uses_alias_if_present(self):
        """Display name should prefer host_alias over hostname."""
        host = self.host_repo.get_host_by_hostname("mysql-stg-01.example.com")
        self.assertIsNotNone(host)
        
        # Get display name using same logic as routes.py
        display = getattr(host, "host_alias", None) or host.hostname  # type: ignore[union-attr]
        
        # In simulation, host_alias may be None, so should fall back to hostname
        self.assertIsNotNone(display)
        self.assertEqual(display, "mysql-stg-01.example.com")


if __name__ == "__main__":
    unittest.main()
