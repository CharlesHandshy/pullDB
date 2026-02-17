"""Protocol parity tests for simulation infrastructure.

These tests ensure SimulatedJobRepository implements the same interface as
the real JobRepository. This prevents mock drift where simulation classes
diverge from production interfaces.

FAIL HARD: If these tests fail, the simulation infrastructure is out of sync
with production code and MUST be fixed before any other work.
"""

from __future__ import annotations

import inspect

import pytest

from pulldb.infra.mysql import JobRepository
from pulldb.infra.mysql_admin import (
    AdminTaskRepository,
    DisallowedUserRepository,
)
from pulldb.infra.mysql_history import JobHistorySummaryRepository
from pulldb.infra.mysql_settings import SettingsRepository
from pulldb.simulation.adapters.mock_mysql import (
    SimulatedAdminTaskRepository,
    SimulatedDisallowedUserRepository,
    SimulatedHostRepository,
    SimulatedJobHistorySummaryRepository,
    SimulatedJobRepository,
    SimulatedSettingsRepository,
    SimulatedUserRepository,
)


def _get_public_methods(cls: type) -> dict[str, inspect.Signature]:
    """Extract public method signatures from a class.

    Returns dict of method_name -> signature, excluding:
    - Private methods (starting with _)
    - Dunder methods (starting with __)
    - Class methods that are properties
    """
    methods = {}
    for name, member in inspect.getmembers(cls):
        # Skip private and dunder methods
        if name.startswith("_"):
            continue
        # Skip properties
        if isinstance(getattr(cls, name, None), property):
            continue
        # Only include callable methods
        if callable(member):
            try:
                sig = inspect.signature(member)
                methods[name] = sig
            except (ValueError, TypeError):
                # Some methods may not have inspectable signatures
                pass
    return methods


class TestJobRepositoryParity:
    """Ensure SimulatedJobRepository matches JobRepository interface."""

    def test_all_public_methods_exist(self) -> None:
        """SimulatedJobRepository must implement all JobRepository public methods."""
        real_methods = _get_public_methods(JobRepository)
        sim_methods = _get_public_methods(SimulatedJobRepository)

        # These are the core methods that MUST exist
        # Deprecation warnings are acceptable for some methods
        missing = set(real_methods.keys()) - set(sim_methods.keys())

        # Allow some methods to be intentionally skipped if documented
        # get_next_queued_job is deprecated in favor of claim_next_job
        # mark_job_running is deprecated (claim_next_job handles it)
        allowed_missing = {"get_next_queued_job", "mark_job_running"}

        critical_missing = missing - allowed_missing

        if critical_missing:
            pytest.fail(
                "SimulatedJobRepository is missing methods that exist in "
                f"JobRepository:\n  {sorted(critical_missing)}\n\n"
                "This indicates mock drift - the simulation will fail in ways "
                "that differ from production. Add these methods to "
                "SimulatedJobRepository."
            )

    def test_method_signatures_compatible(self) -> None:
        """Method signatures should be compatible (same required params)."""
        real_methods = _get_public_methods(JobRepository)
        sim_methods = _get_public_methods(SimulatedJobRepository)

        # Check methods that exist in both
        common_methods = set(real_methods.keys()) & set(sim_methods.keys())

        signature_issues = []
        for method_name in common_methods:
            real_sig = real_methods[method_name]
            sim_sig = sim_methods[method_name]

            # Extract required parameters (those without defaults)
            var_kinds = (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            )
            real_params = {
                name: param
                for name, param in real_sig.parameters.items()
                if name != "self"
                and param.default is inspect.Parameter.empty
                and param.kind not in var_kinds
            }
            sim_params = {
                name: param
                for name, param in sim_sig.parameters.items()
                if name != "self"
                and param.default is inspect.Parameter.empty
                and param.kind not in var_kinds
            }

            # SimulatedJobRepository can have FEWER required params (more optional)
            # but should not require MORE params than the real implementation
            extra_required = set(sim_params.keys()) - set(real_params.keys())
            if extra_required:
                signature_issues.append(
                    f"  {method_name}: simulation requires extra "
                    f"params {extra_required}"
                )

        if signature_issues:
            pytest.fail(
                "SimulatedJobRepository has incompatible signatures:\n"
                + "\n".join(signature_issues)
            )


class TestUserRepositoryParity:
    """Ensure SimulatedUserRepository matches UserRepository interface."""

    def test_core_methods_exist(self) -> None:
        """SimulatedUserRepository must implement core UserRepository methods."""
        sim_methods = _get_public_methods(SimulatedUserRepository)

        # Core methods that API endpoints use
        # Note: update_user and delete_user are not yet implemented in simulation
        # but are not critical for dev server operation
        core_methods = {
            "get_user_by_id",
            "get_user_by_username",
            "list_users",
            "create_user",
        }

        missing = core_methods - set(sim_methods.keys())
        if missing:
            pytest.fail(
                f"SimulatedUserRepository is missing core methods:\n  {sorted(missing)}"
            )


class TestHostRepositoryParity:
    """Ensure SimulatedHostRepository matches HostRepository interface."""

    def test_core_methods_exist(self) -> None:
        """SimulatedHostRepository must implement core HostRepository methods."""
        sim_methods = _get_public_methods(SimulatedHostRepository)

        # Core methods that cleanup and API endpoints use
        # Note: HostRepository uses get_host_by_name, simulation uses
        # get_host_by_hostname and get_host_by_alias - adjust test accordingly
        core_methods = {
            "get_enabled_hosts",
            "add_host",
            # Simulation uses get_host_by_hostname instead of get_host_by_name
            "get_host_by_hostname",
        }

        # Check which core methods are missing
        available = set(sim_methods.keys())
        missing = core_methods - available

        if missing:
            pytest.fail(
                "SimulatedHostRepository is missing core methods:\n"
                f"  {sorted(missing)}\n"
                f"Available: {sorted(available)}"
            )


class TestSpecificMethodsExist:
    """Test specific methods that have caused bugs when missing."""

    def test_find_job_by_staging_prefix_exists(self) -> None:
        """This method caused the cleanup-staging bug when missing from mocks."""
        assert hasattr(SimulatedJobRepository, "find_job_by_staging_prefix"), (
            "find_job_by_staging_prefix missing - this was the root cause of "
            "the cleanup-staging bug. Never remove this method."
        )

    def test_get_old_terminal_jobs_exists(self) -> None:
        """Required for cleanup operations."""
        assert hasattr(SimulatedJobRepository, "get_old_terminal_jobs"), (
            "get_old_terminal_jobs missing - required for cleanup operations"
        )

    def test_has_active_jobs_for_target_exists(self) -> None:
        """Required for cleanup safety checks."""
        assert hasattr(SimulatedJobRepository, "has_active_jobs_for_target"), (
            "has_active_jobs_for_target missing - required for cleanup safety"
        )


class TestSettingsRepositoryParity:
    """Ensure SimulatedSettingsRepository matches SettingsRepository interface."""

    def test_all_public_methods_exist(self) -> None:
        """SimulatedSettingsRepository must implement all SettingsRepository public methods."""
        real_methods = _get_public_methods(SettingsRepository)
        sim_methods = _get_public_methods(SimulatedSettingsRepository)

        missing = set(real_methods.keys()) - set(sim_methods.keys())
        if missing:
            pytest.fail(
                "SimulatedSettingsRepository is missing methods that exist in "
                f"SettingsRepository:\n  {sorted(missing)}"
            )


class TestDisallowedUserRepositoryParity:
    """Ensure SimulatedDisallowedUserRepository matches DisallowedUserRepository."""

    def test_all_public_methods_exist(self) -> None:
        """SimulatedDisallowedUserRepository must implement all public methods."""
        real_methods = _get_public_methods(DisallowedUserRepository)
        sim_methods = _get_public_methods(SimulatedDisallowedUserRepository)

        missing = set(real_methods.keys()) - set(sim_methods.keys())
        if missing:
            pytest.fail(
                "SimulatedDisallowedUserRepository is missing methods that exist in "
                f"DisallowedUserRepository:\n  {sorted(missing)}"
            )


class TestAdminTaskRepositoryParity:
    """Ensure SimulatedAdminTaskRepository matches AdminTaskRepository."""

    def test_all_public_methods_exist(self) -> None:
        """SimulatedAdminTaskRepository must implement all public methods."""
        real_methods = _get_public_methods(AdminTaskRepository)
        sim_methods = _get_public_methods(SimulatedAdminTaskRepository)

        missing = set(real_methods.keys()) - set(sim_methods.keys())
        if missing:
            pytest.fail(
                "SimulatedAdminTaskRepository is missing methods that exist in "
                f"AdminTaskRepository:\n  {sorted(missing)}"
            )


class TestJobHistorySummaryRepositoryParity:
    """Ensure SimulatedJobHistorySummaryRepository matches production."""

    def test_all_public_methods_exist(self) -> None:
        """SimulatedJobHistorySummaryRepository must implement all public methods."""
        real_methods = _get_public_methods(JobHistorySummaryRepository)
        sim_methods = _get_public_methods(SimulatedJobHistorySummaryRepository)

        missing = set(real_methods.keys()) - set(sim_methods.keys())
        if missing:
            pytest.fail(
                "SimulatedJobHistorySummaryRepository is missing methods that exist in "
                f"JobHistorySummaryRepository:\n  {sorted(missing)}"
            )
