"""Unit tests for SimulatedAuthRepository.

Covers all methods added during the simulation audit (2026-02-20):
  create_api_key, verify_api_key, get_api_key_secret_hash, get_api_key_secret,
  approve_api_key, reactivate_api_key, delete_api_key, delete_api_keys_for_user,
  count_pending_api_keys_by_user, update_api_key_last_used,
  delete_expired_pending_keys, migrate_encrypt_existing_keys, get_all_api_keys.

Each method has at minimum: happy path, not-found / edge case, and error-path.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from pulldb.domain.errors import KeyPendingApprovalError, KeyRevokedError
from pulldb.simulation.adapters.mock_mysql import (
    SimulatedAuthRepository,
    SimulatedUserRepository,
)
from pulldb.simulation.core.state import get_simulation_state


class TestSimulatedAuthRepository(unittest.TestCase):
    """Tests for SimulatedAuthRepository API key management."""

    def setUp(self) -> None:
        self.state = get_simulation_state()
        self.state.clear()
        self.repo = SimulatedAuthRepository()
        self.user_repo = SimulatedUserRepository()
        self.user = self.user_repo.create_user("testuser", "testu")
        self.uid = self.user.user_id

    # ------------------------------------------------------------------
    # create_api_key
    # ------------------------------------------------------------------

    def test_create_api_key_pending_by_default(self) -> None:
        """Default create leaves key pending (unapproved, inactive)."""
        key_id, secret = self.repo.create_api_key(self.uid)
        key = self.state.api_keys[key_id]
        self.assertFalse(key["is_active"])
        self.assertIsNone(key["approved_at"])
        self.assertIsNone(key["approved_by"])
        self.assertIsNotNone(secret)
        self.assertEqual(key["user_id"], self.uid)

    def test_create_api_key_auto_approve(self) -> None:
        """auto_approve=True results in an active, approved key."""
        admin_id = "admin-001"
        key_id, secret = self.repo.create_api_key(
            self.uid,
            auto_approve=True,
            approved_by=admin_id,
        )
        key = self.state.api_keys[key_id]
        self.assertTrue(key["is_active"])
        self.assertIsNotNone(key["approved_at"])
        self.assertEqual(key["approved_by"], admin_id)

    def test_create_api_key_stores_created_from_ip(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, created_from_ip="10.0.0.5")
        self.assertEqual(self.state.api_keys[key_id]["created_from_ip"], "10.0.0.5")

    def test_create_api_key_defaults_ip(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid)
        self.assertEqual(self.state.api_keys[key_id]["created_from_ip"], "127.0.0.1")

    def test_create_api_key_returns_unique_ids(self) -> None:
        id1, _ = self.repo.create_api_key(self.uid)
        id2, _ = self.repo.create_api_key(self.uid)
        self.assertNotEqual(id1, id2)

    def test_create_api_key_sentinel_hash_matches_secret(self) -> None:
        """key_secret_hash must be the sentinel '$simulated$<secret>' for verify_api_key."""
        key_id, secret = self.repo.create_api_key(self.uid, auto_approve=True)
        expected_hash = "$simulated$" + secret
        self.assertEqual(self.state.api_keys[key_id]["key_secret_hash"], expected_hash)

    # ------------------------------------------------------------------
    # verify_api_key
    # ------------------------------------------------------------------

    def test_verify_api_key_valid(self) -> None:
        """verify_api_key returns user_id for a correct, approved, active key."""
        key_id, secret = self.repo.create_api_key(self.uid, auto_approve=True)
        result = self.repo.verify_api_key(key_id, secret)
        self.assertEqual(result, self.uid)

    def test_verify_api_key_wrong_secret(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        self.assertIsNone(self.repo.verify_api_key(key_id, "wrong-secret"))

    def test_verify_api_key_unknown_key(self) -> None:
        self.assertIsNone(self.repo.verify_api_key("nonexistent", "any"))

    def test_verify_api_key_inactive(self) -> None:
        key_id, secret = self.repo.create_api_key(self.uid, auto_approve=True)
        self.repo.revoke_api_key(key_id)
        self.assertIsNone(self.repo.verify_api_key(key_id, secret))

    def test_verify_api_key_pending(self) -> None:
        """Unapproved key should not verify (is_active=False)."""
        key_id, secret = self.repo.create_api_key(self.uid)
        self.assertIsNone(self.repo.verify_api_key(key_id, secret))

    def test_verify_api_key_expired(self) -> None:
        key_id, secret = self.repo.create_api_key(self.uid, auto_approve=True)
        self.state.api_keys[key_id]["expires_at"] = datetime.now(UTC) - timedelta(hours=1)
        self.assertIsNone(self.repo.verify_api_key(key_id, secret))

    def test_verify_api_key_updates_last_used_at(self) -> None:
        key_id, secret = self.repo.create_api_key(self.uid, auto_approve=True)
        before = datetime.now(UTC)
        self.repo.verify_api_key(key_id, secret)
        last_used = self.state.api_keys[key_id]["last_used_at"]
        self.assertIsNotNone(last_used)
        self.assertGreaterEqual(last_used, before)

    # ------------------------------------------------------------------
    # get_api_key_secret_hash
    # ------------------------------------------------------------------

    def test_get_api_key_secret_hash_returns_hash(self) -> None:
        key_id, secret = self.repo.create_api_key(self.uid, auto_approve=True)
        result = self.repo.get_api_key_secret_hash(key_id)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_get_api_key_secret_hash_not_empty_string(self) -> None:
        """Must return None for missing, never empty string."""
        result = self.repo.get_api_key_secret_hash("nonexistent")
        self.assertIsNone(result)

    def test_get_api_key_secret_hash_pending_raises(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid)
        with self.assertRaises(KeyPendingApprovalError):
            self.repo.get_api_key_secret_hash(key_id)

    def test_get_api_key_secret_hash_revoked_returns_none(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        self.repo.revoke_api_key(key_id)
        result = self.repo.get_api_key_secret_hash(key_id)
        self.assertIsNone(result)

    def test_get_api_key_secret_hash_expired_returns_none(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        self.state.api_keys[key_id]["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
        result = self.repo.get_api_key_secret_hash(key_id)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # get_api_key_secret
    # ------------------------------------------------------------------

    def test_get_api_key_secret_returns_plaintext(self) -> None:
        key_id, secret = self.repo.create_api_key(self.uid, auto_approve=True)
        result = self.repo.get_api_key_secret(key_id)
        self.assertEqual(result, secret)

    def test_get_api_key_secret_not_found_returns_none(self) -> None:
        result = self.repo.get_api_key_secret("nonexistent")
        self.assertIsNone(result)

    def test_get_api_key_secret_never_returns_empty_string(self) -> None:
        """Must return None (not '') when key not found."""
        result = self.repo.get_api_key_secret("nonexistent")
        self.assertIsNone(result)
        self.assertIsNot(result, "")

    def test_get_api_key_secret_pending_raises(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid)
        with self.assertRaises(KeyPendingApprovalError):
            self.repo.get_api_key_secret(key_id)

    def test_get_api_key_secret_revoked_raises(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        self.repo.revoke_api_key(key_id)
        with self.assertRaises(KeyRevokedError):
            self.repo.get_api_key_secret(key_id)

    def test_get_api_key_secret_expired_returns_none(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        self.state.api_keys[key_id]["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
        result = self.repo.get_api_key_secret(key_id)
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # approve_api_key
    # ------------------------------------------------------------------

    def test_approve_api_key_activates_pending_key(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid)
        result = self.repo.approve_api_key(key_id, "admin-1")
        self.assertTrue(result)
        key = self.state.api_keys[key_id]
        self.assertTrue(key["is_active"])
        self.assertEqual(key["approved_by"], "admin-1")
        self.assertIsNotNone(key["approved_at"])

    def test_approve_api_key_not_found_returns_false(self) -> None:
        self.assertFalse(self.repo.approve_api_key("nonexistent", "admin-1"))

    def test_approve_api_key_idempotent_returns_false_on_second_call(self) -> None:
        """Double-approval must return False (mirrors real WHERE approved_at IS NULL guard)."""
        key_id, _ = self.repo.create_api_key(self.uid)
        self.assertTrue(self.repo.approve_api_key(key_id, "admin-1"))
        self.assertFalse(self.repo.approve_api_key(key_id, "admin-2"))
        # approved_by must not have been overwritten
        self.assertEqual(self.state.api_keys[key_id]["approved_by"], "admin-1")

    # ------------------------------------------------------------------
    # reactivate_api_key
    # ------------------------------------------------------------------

    def test_reactivate_api_key_restores_revoked(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        self.repo.revoke_api_key(key_id)
        self.assertFalse(self.state.api_keys[key_id]["is_active"])
        result = self.repo.reactivate_api_key(key_id)
        self.assertTrue(result)
        self.assertTrue(self.state.api_keys[key_id]["is_active"])

    def test_reactivate_api_key_never_approved_returns_false(self) -> None:
        """Keys that were never approved cannot be reactivated."""
        key_id, _ = self.repo.create_api_key(self.uid)  # pending
        result = self.repo.reactivate_api_key(key_id)
        self.assertFalse(result)

    def test_reactivate_api_key_not_found_returns_false(self) -> None:
        self.assertFalse(self.repo.reactivate_api_key("nonexistent"))

    # ------------------------------------------------------------------
    # delete_api_key
    # ------------------------------------------------------------------

    def test_delete_api_key_removes_key(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        result = self.repo.delete_api_key(key_id)
        self.assertTrue(result)
        self.assertNotIn(key_id, self.state.api_keys)

    def test_delete_api_key_not_found_returns_false(self) -> None:
        self.assertFalse(self.repo.delete_api_key("nonexistent"))

    def test_delete_api_key_is_permanent(self) -> None:
        """After deletion the key cannot be fetched or re-deleted."""
        key_id, _ = self.repo.create_api_key(self.uid)
        self.repo.delete_api_key(key_id)
        self.assertFalse(self.repo.delete_api_key(key_id))

    # ------------------------------------------------------------------
    # delete_api_keys_for_user
    # ------------------------------------------------------------------

    def test_delete_api_keys_for_user_removes_all(self) -> None:
        self.repo.create_api_key(self.uid)
        self.repo.create_api_key(self.uid)
        count = self.repo.delete_api_keys_for_user(self.uid)
        self.assertEqual(count, 2)
        remaining = [k for k, v in self.state.api_keys.items() if v["user_id"] == self.uid]
        self.assertEqual(len(remaining), 0)

    def test_delete_api_keys_for_user_returns_zero_when_none(self) -> None:
        count = self.repo.delete_api_keys_for_user(self.uid)
        self.assertEqual(count, 0)

    def test_delete_api_keys_for_user_does_not_touch_other_users(self) -> None:
        other = self.user_repo.create_user("other", "othe")
        other_key_id, _ = self.repo.create_api_key(other.user_id)
        self.repo.create_api_key(self.uid)
        self.repo.delete_api_keys_for_user(self.uid)
        self.assertIn(other_key_id, self.state.api_keys)

    # ------------------------------------------------------------------
    # count_pending_api_keys_by_user
    # ------------------------------------------------------------------

    def test_count_pending_counts_unapproved(self) -> None:
        self.repo.create_api_key(self.uid)  # pending
        self.repo.create_api_key(self.uid)  # pending
        self.repo.create_api_key(self.uid, auto_approve=True)  # active
        self.assertEqual(self.repo.count_pending_api_keys_by_user(self.uid), 2)

    def test_count_pending_zero_when_all_approved(self) -> None:
        self.repo.create_api_key(self.uid, auto_approve=True)
        self.assertEqual(self.repo.count_pending_api_keys_by_user(self.uid), 0)

    def test_count_pending_zero_for_unknown_user(self) -> None:
        self.assertEqual(self.repo.count_pending_api_keys_by_user("no-such-uid"), 0)

    def test_count_pending_does_not_count_other_users(self) -> None:
        other = self.user_repo.create_user("other2", "oth2")
        self.repo.create_api_key(other.user_id)  # other user's pending
        self.assertEqual(self.repo.count_pending_api_keys_by_user(self.uid), 0)

    # ------------------------------------------------------------------
    # update_api_key_last_used
    # ------------------------------------------------------------------

    def test_update_api_key_last_used_sets_fields(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        before = datetime.now(UTC)
        self.repo.update_api_key_last_used(key_id, "192.168.1.5")
        key = self.state.api_keys[key_id]
        self.assertIsNotNone(key["last_used_at"])
        self.assertGreaterEqual(key["last_used_at"], before)
        self.assertEqual(key["last_used_ip"], "192.168.1.5")

    def test_update_api_key_last_used_accepts_none_ip(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        self.repo.update_api_key_last_used(key_id, None)
        self.assertIsNone(self.state.api_keys[key_id]["last_used_ip"])

    def test_update_api_key_last_used_no_op_for_missing_key(self) -> None:
        """Should not raise for unknown key_id."""
        self.repo.update_api_key_last_used("nonexistent", "10.0.0.1")  # must not raise

    # ------------------------------------------------------------------
    # delete_expired_pending_keys
    # ------------------------------------------------------------------

    def test_delete_expired_pending_keys_removes_old(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid)
        # Backdate the key beyond the default 7-day window
        self.state.api_keys[key_id]["created_at"] = datetime.now(UTC) - timedelta(days=8)
        deleted = self.repo.delete_expired_pending_keys(max_age_days=7)
        self.assertEqual(deleted, 1)
        self.assertNotIn(key_id, self.state.api_keys)

    def test_delete_expired_pending_keys_keeps_recent(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid)
        # Key is only 3 days old, within the 7-day window
        self.state.api_keys[key_id]["created_at"] = datetime.now(UTC) - timedelta(days=3)
        deleted = self.repo.delete_expired_pending_keys(max_age_days=7)
        self.assertEqual(deleted, 0)
        self.assertIn(key_id, self.state.api_keys)

    def test_delete_expired_pending_keys_keeps_approved(self) -> None:
        """Approved keys (even old ones) must not be deleted."""
        key_id, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        self.state.api_keys[key_id]["created_at"] = datetime.now(UTC) - timedelta(days=30)
        deleted = self.repo.delete_expired_pending_keys(max_age_days=7)
        self.assertEqual(deleted, 0)
        self.assertIn(key_id, self.state.api_keys)

    def test_delete_expired_pending_keys_custom_window(self) -> None:
        key_id, _ = self.repo.create_api_key(self.uid)
        self.state.api_keys[key_id]["created_at"] = datetime.now(UTC) - timedelta(days=2)
        # With a 1-day window it should be deleted
        deleted = self.repo.delete_expired_pending_keys(max_age_days=1)
        self.assertEqual(deleted, 1)

    def test_delete_expired_pending_keys_returns_zero_when_none(self) -> None:
        deleted = self.repo.delete_expired_pending_keys()
        self.assertEqual(deleted, 0)

    # ------------------------------------------------------------------
    # migrate_encrypt_existing_keys
    # ------------------------------------------------------------------

    def test_migrate_encrypt_existing_keys_is_noop(self) -> None:
        self.repo.create_api_key(self.uid, auto_approve=True)
        self.repo.create_api_key(self.uid, auto_approve=True)
        result = self.repo.migrate_encrypt_existing_keys()
        self.assertEqual(result, 0)

    def test_migrate_encrypt_existing_keys_returns_int(self) -> None:
        result = self.repo.migrate_encrypt_existing_keys()
        self.assertIsInstance(result, int)

    # ------------------------------------------------------------------
    # get_all_api_keys
    # ------------------------------------------------------------------

    def test_get_all_api_keys_returns_dicts(self) -> None:
        """Must return plain dicts, not dataclass instances."""
        self.repo.create_api_key(self.uid, auto_approve=True)
        results = self.repo.get_all_api_keys(include_inactive=True)
        self.assertGreater(len(results), 0)
        for row in results:
            self.assertIsInstance(row, dict)

    def test_get_all_api_keys_excludes_inactive_by_default(self) -> None:
        self.repo.create_api_key(self.uid, auto_approve=True)  # active
        self.repo.create_api_key(self.uid)                     # pending/inactive
        results = self.repo.get_all_api_keys()
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["is_active"])

    def test_get_all_api_keys_include_inactive(self) -> None:
        self.repo.create_api_key(self.uid, auto_approve=True)
        self.repo.create_api_key(self.uid)
        results = self.repo.get_all_api_keys(include_inactive=True)
        self.assertEqual(len(results), 2)

    def test_get_all_api_keys_filter_by_user_id(self) -> None:
        other = self.user_repo.create_user("other3", "oth3")
        self.repo.create_api_key(self.uid, auto_approve=True)
        self.repo.create_api_key(other.user_id, auto_approve=True)
        results = self.repo.get_all_api_keys(include_inactive=True, user_id=self.uid)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["user_id"], self.uid)

    def test_get_all_api_keys_contains_expected_fields(self) -> None:
        self.repo.create_api_key(self.uid, auto_approve=True)
        results = self.repo.get_all_api_keys(include_inactive=True)
        row = results[0]
        expected_fields = {
            "key_id", "user_id", "username", "user_code",
            "name", "host_name", "is_active", "approved_at",
            "created_at", "created_from_ip", "last_used_at",
            "last_used_ip", "expires_at",
        }
        self.assertEqual(set(row.keys()), expected_fields)

    def test_get_all_api_keys_does_not_expose_secret(self) -> None:
        """key_secret and key_secret_hash must NOT appear in the returned dicts."""
        self.repo.create_api_key(self.uid, auto_approve=True)
        results = self.repo.get_all_api_keys(include_inactive=True)
        for row in results:
            self.assertNotIn("key_secret", row)
            self.assertNotIn("key_secret_hash", row)

    def test_get_all_api_keys_sorted_by_created_at_desc(self) -> None:
        id1, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        id2, _ = self.repo.create_api_key(self.uid, auto_approve=True)
        # Ensure id1 appears older
        self.state.api_keys[id1]["created_at"] = datetime.now(UTC) - timedelta(hours=2)
        self.state.api_keys[id2]["created_at"] = datetime.now(UTC) - timedelta(hours=1)
        results = self.repo.get_all_api_keys(include_inactive=True)
        self.assertEqual(results[0]["key_id"], id2)
        self.assertEqual(results[1]["key_id"], id1)

    def test_get_all_api_keys_empty_state(self) -> None:
        results = self.repo.get_all_api_keys(include_inactive=True)
        self.assertEqual(results, [])


class TestSimulatedAuthRepositoryHostUserMethods(unittest.TestCase):
    """Tests for count_users_for_host and get_users_for_host (admin host detail page)."""

    def setUp(self) -> None:
        self.state = get_simulation_state()
        self.state.clear()
        self.repo = SimulatedAuthRepository()
        self.user_repo = SimulatedUserRepository()
        from pulldb.simulation.adapters.mock_mysql import SimulatedHostRepository
        self.host_repo = SimulatedHostRepository()

        # Create two hosts
        self.host_repo.add_host("db-primary.example.com", 4, None, host_id="host-001")
        self.host_repo.add_host("db-secondary.example.com", 4, None, host_id="host-002")

        # Create three users
        self.alice = self.user_repo.create_user("alice", "alice1")
        self.bob = self.user_repo.create_user("bob", "bob111")
        self.carol = self.user_repo.create_user("carol", "carol1")

    def _assign_hosts(self, user_id: str, host_ids: list, default: str | None) -> None:
        self.repo.set_user_hosts(user_id, host_ids, default)

    # --- count_users_for_host ---

    def test_count_users_for_host_zero_when_none_assigned(self) -> None:
        count = self.repo.count_users_for_host("host-001")
        self.assertEqual(count, 0)

    def test_count_users_for_host_one_user(self) -> None:
        self._assign_hosts(self.alice.user_id, ["host-001"], "host-001")
        self.assertEqual(self.repo.count_users_for_host("host-001"), 1)

    def test_count_users_for_host_multiple_users(self) -> None:
        self._assign_hosts(self.alice.user_id, ["host-001"], "host-001")
        self._assign_hosts(self.bob.user_id, ["host-001", "host-002"], "host-001")
        self._assign_hosts(self.carol.user_id, ["host-002"], "host-002")
        self.assertEqual(self.repo.count_users_for_host("host-001"), 2)
        self.assertEqual(self.repo.count_users_for_host("host-002"), 2)

    def test_count_users_for_host_nonexistent_host(self) -> None:
        self._assign_hosts(self.alice.user_id, ["host-001"], "host-001")
        self.assertEqual(self.repo.count_users_for_host("host-999"), 0)

    def test_count_does_not_double_count_same_user(self) -> None:
        """A user assigned to host-001 only counts once even with multiple host entries."""
        self._assign_hosts(self.alice.user_id, ["host-001", "host-002"], "host-001")
        self.assertEqual(self.repo.count_users_for_host("host-001"), 1)

    # --- get_users_for_host ---

    def test_get_users_for_host_empty(self) -> None:
        result = self.repo.get_users_for_host("host-001")
        self.assertEqual(result, [])

    def test_get_users_for_host_returns_dict_with_required_keys(self) -> None:
        self._assign_hosts(self.alice.user_id, ["host-001"], "host-001")
        result = self.repo.get_users_for_host("host-001")
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertIn("user_id", row)
        self.assertIn("username", row)
        self.assertIn("is_default", row)

    def test_get_users_for_host_correct_values(self) -> None:
        self._assign_hosts(self.alice.user_id, ["host-001"], "host-001")
        result = self.repo.get_users_for_host("host-001")
        self.assertEqual(result[0]["user_id"], self.alice.user_id)
        self.assertEqual(result[0]["username"], "alice")
        self.assertIsInstance(result[0]["is_default"], bool)

    def test_get_users_for_host_sorted_by_username(self) -> None:
        self._assign_hosts(self.carol.user_id, ["host-001"], "host-001")
        self._assign_hosts(self.alice.user_id, ["host-001"], "host-001")
        self._assign_hosts(self.bob.user_id, ["host-001"], "host-001")
        result = self.repo.get_users_for_host("host-001")
        names = [r["username"] for r in result]
        self.assertEqual(names, sorted(names))

    def test_get_users_for_host_excludes_unassigned_users(self) -> None:
        self._assign_hosts(self.alice.user_id, ["host-001"], "host-001")
        # bob not assigned to host-001
        result = self.repo.get_users_for_host("host-001")
        usernames = [r["username"] for r in result]
        self.assertNotIn("bob", usernames)

    def test_get_users_for_host_is_default_true(self) -> None:
        self._assign_hosts(self.alice.user_id, ["host-001"], "host-001")
        result = self.repo.get_users_for_host("host-001")
        self.assertTrue(result[0]["is_default"])

    def test_get_users_for_host_is_default_false_when_different_default(self) -> None:
        self._assign_hosts(self.alice.user_id, ["host-001", "host-002"], "host-002")
        result = self.repo.get_users_for_host("host-001")
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["is_default"])


if __name__ == "__main__":
    unittest.main()
