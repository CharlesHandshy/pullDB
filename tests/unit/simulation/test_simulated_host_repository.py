"""Unit tests for SimulatedHostRepository.

Covers list_databases which was added during the full-page audit (2026-02-XX):
  list_databases — derives visible databases from staging state and job history.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from pulldb.domain.models import Job, JobStatus
from pulldb.simulation.adapters.mock_mysql import (
    SimulatedHostRepository,
    SimulatedJobRepository,
)
from pulldb.simulation.core.state import get_simulation_state


def _make_job(
    job_id: str,
    hostname: str,
    target: str,
    status: JobStatus = JobStatus.COMPLETE,
) -> Job:
    """Build a minimal Job for use in tests."""
    now = datetime.now(UTC)
    return Job(
        id=job_id,
        owner_user_id="user-test",
        owner_username="testuser",
        owner_user_code="testu",
        target=target,
        staging_name=f"{target}_{job_id[:12]}",
        dbhost=hostname,
        status=status,
        submitted_at=now - timedelta(minutes=10),
        completed_at=now,
    )


class TestSimulatedHostRepositoryListDatabases(unittest.TestCase):
    """Tests for SimulatedHostRepository.list_databases."""

    def setUp(self) -> None:
        self.state = get_simulation_state()
        self.state.clear()
        self.repo = SimulatedHostRepository()
        self.job_repo = SimulatedJobRepository()
        # Add a host so the hostname is "registered"
        self.repo.add_host("db.example.com", 4, None, host_id="host-001")

    # ------------------------------------------------------------------
    # Empty state
    # ------------------------------------------------------------------

    def test_list_databases_empty_state_returns_empty_list(self) -> None:
        result = self.repo.list_databases("db.example.com")
        self.assertEqual(result, [])

    def test_list_databases_unknown_host_returns_empty_list(self) -> None:
        result = self.repo.list_databases("nonexistent.example.com")
        self.assertEqual(result, [])

    # ------------------------------------------------------------------
    # Staging databases source
    # ------------------------------------------------------------------

    def test_list_databases_returns_staging_databases(self) -> None:
        self.state.staging_databases["db.example.com"] = {"customer_a", "customer_b"}
        result = self.repo.list_databases("db.example.com")
        self.assertIn("customer_a", result)
        self.assertIn("customer_b", result)

    def test_list_databases_filters_system_schemas_from_staging(self) -> None:
        system_dbs = {"information_schema", "mysql", "performance_schema", "sys", "pulldb"}
        self.state.staging_databases["db.example.com"] = system_dbs | {"customer_c"}
        result = self.repo.list_databases("db.example.com")
        for sys_db in system_dbs:
            self.assertNotIn(sys_db, result)
        self.assertIn("customer_c", result)

    # ------------------------------------------------------------------
    # Job history source
    # ------------------------------------------------------------------

    def test_list_databases_returns_job_target_databases(self) -> None:
        job = _make_job("job-001", "db.example.com", "testu_customer_x")
        self.state.jobs[job.id] = job
        result = self.repo.list_databases("db.example.com")
        self.assertIn("testu_customer_x", result)

    def test_list_databases_ignores_jobs_on_other_hosts(self) -> None:
        job_other = _make_job("job-002", "other.example.com", "testu_private")
        self.state.jobs[job_other.id] = job_other
        result = self.repo.list_databases("db.example.com")
        self.assertNotIn("testu_private", result)

    def test_list_databases_deduplicates_across_sources(self) -> None:
        """Same DB name from staging + jobs should appear only once."""
        self.state.staging_databases["db.example.com"] = {"testu_shared"}
        job = _make_job("job-003", "db.example.com", "testu_shared")
        self.state.jobs[job.id] = job
        result = self.repo.list_databases("db.example.com")
        self.assertEqual(result.count("testu_shared"), 1)

    def test_list_databases_filters_system_schemas_from_jobs(self) -> None:
        system_dbs = ["information_schema", "mysql", "performance_schema", "sys", "pulldb"]
        for i, db_name in enumerate(system_dbs):
            job = _make_job(f"job-sys-{i}", "db.example.com", db_name)
            self.state.jobs[job.id] = job
        result = self.repo.list_databases("db.example.com")
        for db_name in system_dbs:
            self.assertNotIn(db_name, result)

    # ------------------------------------------------------------------
    # Sort order
    # ------------------------------------------------------------------

    def test_list_databases_returns_sorted_list(self) -> None:
        self.state.staging_databases["db.example.com"] = {"zebra_db", "alpha_db", "mango_db"}
        result = self.repo.list_databases("db.example.com")
        self.assertEqual(result, sorted(result))

    # ------------------------------------------------------------------
    # Combined sources
    # ------------------------------------------------------------------

    def test_list_databases_combines_staging_and_jobs(self) -> None:
        self.state.staging_databases["db.example.com"] = {"from_staging"}
        job = _make_job("job-004", "db.example.com", "from_job")
        self.state.jobs[job.id] = job
        result = self.repo.list_databases("db.example.com")
        self.assertIn("from_staging", result)
        self.assertIn("from_job", result)


class TestSimulatedJobRepositoryPoolAttribute(unittest.TestCase):
    """Tests for SimulatedJobRepository.pool sentinel attribute."""

    def setUp(self) -> None:
        self.state = get_simulation_state()
        self.state.clear()
        self.repo = SimulatedJobRepository()

    def test_pool_attribute_exists(self) -> None:
        self.assertTrue(hasattr(self.repo, "pool"))

    def test_pool_is_none(self) -> None:
        """pool must be None in simulation mode — routes check for None to detect simulation."""
        self.assertIsNone(self.repo.pool)

    def test_pool_is_class_attribute_not_instance(self) -> None:
        """pool should be defined at class level so all instances share the sentinel."""
        self.assertIn("pool", SimulatedJobRepository.__dict__)


if __name__ == "__main__":
    unittest.main()
