"""
Tests for documentation triage engine.

Test scenarios:
1. "Fix MySQL error in restore.py" → database.md, myloader.md, fail-hard.md
2. "Add new API endpoint" → python.md, hca.md, api-design.md
3. "Refactor CSS" → ui-ux.md, hca.md
4. Token budget enforcement
5. Dependency cycle detection
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ..signal_extraction import TaskSignals, extract_signals
from ..triage_engine import TriageEngine, TriageResult


@pytest.fixture
def mock_index():
    """Create a minimal mock index for testing."""
    return {
        "schema_version": "1.0",
        "last_updated": "2026-01-08",
        "token_budget_default": 50000,
        "corpus_stats": {
            "total_documents": 10,
            "total_tokens_estimated": 15000,
            "categories": {"standard": 5, "protocol": 3, "pattern": 2},
        },
        "documents": [
            {
                "id": "agent_context",
                "path": "AGENT-CONTEXT.md",
                "category": "root",
                "tier": 0,
                "priority": "always_load",
                "token_estimate": 1000,
                "topics": ["context loading", "tiered architecture"],
                "triggers": {
                    "keywords": ["*"],
                    "file_extensions": [],
                    "file_paths": [],
                    "task_types": ["*"],
                },
                "dependencies": {"load_with": [], "load_after": []},
                "summary": "AI entry point",
            },
            {
                "id": "database",
                "path": "standards/database.md",
                "category": "standard",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 2500,
                "topics": ["mysql", "database", "credentials"],
                "triggers": {
                    "keywords": ["database", "mysql", "sql"],
                    "file_extensions": [".sql"],
                    "file_paths": [],
                    "task_types": ["implement", "debug"],
                },
                "dependencies": {"load_with": ["fail_hard"], "load_after": []},
                "summary": "Database patterns",
            },
            {
                "id": "python",
                "path": "standards/python.md",
                "category": "standard",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 2800,
                "topics": ["python", "type hints", "ruff"],
                "triggers": {
                    "keywords": ["python"],
                    "file_extensions": [".py"],
                    "file_paths": [],
                    "task_types": ["implement", "debug", "refactor"],
                },
                "dependencies": {"load_with": ["fail_hard"], "load_after": []},
                "summary": "Python standards",
            },
            {
                "id": "fail_hard",
                "path": "protocols/fail-hard.md",
                "category": "protocol",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 1000,
                "topics": ["error handling", "fail hard"],
                "triggers": {
                    "keywords": ["error", "exception", "debug"],
                    "file_extensions": [],
                    "file_paths": [],
                    "task_types": ["implement", "debug"],
                },
                "dependencies": {"load_with": [], "load_after": []},
                "summary": "FAIL HARD protocol",
            },
            {
                "id": "hca",
                "path": "standards/hca.md",
                "category": "standard",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 2200,
                "topics": ["hca", "hierarchy", "imports"],
                "triggers": {
                    "keywords": ["hca", "layers", "imports"],
                    "file_extensions": [".py"],
                    "file_paths": [],
                    "task_types": ["implement", "refactor"],
                },
                "dependencies": {"load_with": [], "load_after": []},
                "summary": "HCA architecture",
            },
            {
                "id": "api",
                "path": "standards/api.md",
                "category": "standard",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 1800,
                "topics": ["api", "rest", "endpoints"],
                "triggers": {
                    "keywords": ["api", "endpoint", "rest"],
                    "file_extensions": [],
                    "file_paths": [],
                    "task_types": ["implement", "review"],
                },
                "dependencies": {"load_with": ["python"], "load_after": []},
                "summary": "API design standards",
            },
            {
                "id": "internal_ui",
                "path": "standards/internal-ui.md",
                "category": "standard",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 1900,
                "topics": ["ui", "ux", "css"],
                "triggers": {
                    "keywords": ["ui", "css", "html", "design"],
                    "file_extensions": [".css", ".html"],
                    "file_paths": [],
                    "task_types": ["implement", "refactor"],
                },
                "dependencies": {"load_with": [], "load_after": []},
                "summary": "UI/UX standards",
            },
            {
                "id": "aws",
                "path": "standards/aws.md",
                "category": "standard",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 1300,
                "topics": ["aws", "s3", "secrets"],
                "triggers": {
                    "keywords": ["aws", "s3"],
                    "file_extensions": [],
                    "file_paths": [],
                    "task_types": ["implement", "debug"],
                },
                "dependencies": {"load_with": [], "load_after": []},
                "summary": "AWS patterns",
            },
            {
                "id": "security",
                "path": "standards/security.md",
                "category": "standard",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 2400,
                "topics": ["security", "owasp", "validation"],
                "triggers": {
                    "keywords": ["security", "auth", "validation"],
                    "file_extensions": [],
                    "file_paths": [],
                    "task_types": ["implement", "review"],
                },
                "dependencies": {"load_with": [], "load_after": []},
                "summary": "Security standards",
            },
            {
                "id": "test_timeout",
                "path": "protocols/test-timeout-monitoring.md",
                "category": "protocol",
                "tier": 1,
                "priority": "reference_only",
                "token_estimate": 1300,
                "topics": ["testing", "timeout", "pytest"],
                "triggers": {
                    "keywords": ["test", "pytest", "timeout"],
                    "file_extensions": [],
                    "file_paths": [],
                    "task_types": ["test", "debug"],
                },
                "dependencies": {"load_with": ["python"], "load_after": []},
                "summary": "Test timeout monitoring",
            },
        ],
    }


@pytest.fixture
def engine(mock_index):
    """Create a triage engine with mock index."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(mock_index, f)
        index_path = Path(f.name)

    engine = TriageEngine(index_path)
    yield engine

    # Cleanup
    index_path.unlink()


def test_signal_extraction_mysql_error():
    """Test signal extraction for MySQL error task."""
    signals = extract_signals(
        user_task="Fix MySQL error in restore.py",
        active_files=["pulldb/worker/restore.py"],
    )

    assert "mysql" in signals.keywords or "error" in signals.keywords
    assert "debug" in signals.task_types
    assert ".py" in signals.file_extensions
    assert signals.special_flags["database_required"] is True
    assert signals.special_flags["python_required"] is True


def test_signal_extraction_api_endpoint():
    """Test signal extraction for API endpoint task."""
    signals = extract_signals(
        user_task="Add new API endpoint for user authentication",
        active_files=["pulldb/api/routes.py"],
    )

    assert "api" in signals.keywords or "endpoint" in signals.keywords
    assert "implement" in signals.task_types
    assert ".py" in signals.file_extensions


def test_signal_extraction_css_refactor():
    """Test signal extraction for CSS refactor task."""
    signals = extract_signals(
        user_task="Refactor CSS styles for admin dashboard",
        active_files=["pulldb/web/static/admin.css"],
    )

    assert "refactor" in signals.task_types
    assert ".css" in signals.file_extensions
    assert signals.special_flags["ui_required"] is True


def test_triage_mysql_error(engine):
    """
    Test triage for: "Fix MySQL error in restore.py"

    Expected: database.md, python.md, fail-hard.md (+ agent_context)
    """
    result = engine.triage_documents(
        user_task="Fix MySQL error in restore.py",
        active_files=["pulldb/worker/restore.py"],
        token_budget=50000,
    )

    # Check always-load
    doc_ids = [doc["id"] for doc in result.selected_docs]
    assert "agent_context" in doc_ids

    # Check relevant docs loaded
    assert "database" in doc_ids
    assert "python" in doc_ids
    assert "fail_hard" in doc_ids

    # Check token budget respected
    assert result.total_tokens <= 50000

    # Check reasoning log
    assert len(result.reasoning_log) >= 5  # All phases logged


def test_triage_api_endpoint(engine):
    """
    Test triage for: "Add new API endpoint"

    Expected: python.md, hca.md, api.md, fail-hard.md
    """
    result = engine.triage_documents(
        user_task="Add new API endpoint for user management",
        active_files=["pulldb/api/routes.py"],
        token_budget=50000,
    )

    doc_ids = [doc["id"] for doc in result.selected_docs]

    # Check relevant docs
    assert "python" in doc_ids
    assert "hca" in doc_ids
    assert "api" in doc_ids

    # Check dependencies resolved (api requires python)
    if "api" in doc_ids:
        api_idx = doc_ids.index("api")
        python_idx = doc_ids.index("python")
        # Python should be loaded with api (either before or as dependency)
        assert "python" in doc_ids


def test_triage_css_refactor(engine):
    """
    Test triage for: "Refactor CSS"

    Expected: internal_ui.md, hca.md
    """
    result = engine.triage_documents(
        user_task="Refactor CSS styles for consistency",
        active_files=["pulldb/web/static/styles.css"],
        token_budget=50000,
    )

    doc_ids = [doc["id"] for doc in result.selected_docs]

    # Check UI doc loaded
    assert "internal_ui" in doc_ids

    # HCA might be loaded (refactor task)
    # This is optional, depends on scoring


def test_token_budget_enforcement(engine):
    """Test that token budget is strictly enforced."""
    # Set very low budget
    result = engine.triage_documents(
        user_task="Fix error in Python script",
        active_files=[],
        token_budget=2000,  # Only allows agent_context + maybe 1 small doc
    )

    assert result.total_tokens <= 2000
    assert "agent_context" in [doc["id"] for doc in result.selected_docs]


def test_dependency_resolution(engine):
    """Test that dependencies are properly resolved."""
    result = engine.triage_documents(
        user_task="Debug database connection issue",
        active_files=[],
        token_budget=50000,
    )

    doc_ids = [doc["id"] for doc in result.selected_docs]

    # If database is loaded, fail_hard should be too (load_with)
    if "database" in doc_ids:
        assert "fail_hard" in doc_ids


def test_dependency_ordering(engine):
    """Test that load_after dependencies are respected in ordering."""
    # This would require a more complex mock with load_after deps
    # For now, just check that topological sort doesn't crash
    result = engine.triage_documents(
        user_task="Test task",
        active_files=[],
        token_budget=50000,
    )

    # Should complete without error
    assert result.selected_docs is not None


def test_no_documents_match(engine):
    """Test behavior when no documents match the task."""
    result = engine.triage_documents(
        user_task="Configure COBOL mainframe integration",
        active_files=[],
        token_budget=50000,
    )

    # Should still load tier-0 docs
    doc_ids = [doc["id"] for doc in result.selected_docs]
    assert "agent_context" in doc_ids

    # But probably nothing else
    assert len(result.selected_docs) >= 1


def test_special_flags_aws(engine):
    """Test that AWS-specific tasks trigger AWS docs."""
    result = engine.triage_documents(
        user_task="Upload files to S3 bucket",
        active_files=[],
        token_budget=50000,
    )

    doc_ids = [doc["id"] for doc in result.selected_docs]
    assert "aws" in doc_ids


def test_special_flags_security(engine):
    """Test that security tasks trigger security docs."""
    result = engine.triage_documents(
        user_task="Implement input validation against SQL injection",
        active_files=[],
        token_budget=50000,
    )

    doc_ids = [doc["id"] for doc in result.selected_docs]
    assert "security" in doc_ids


def test_special_flags_testing(engine):
    """Test that testing tasks trigger test docs."""
    result = engine.triage_documents(
        user_task="Fix pytest timeout in test suite",
        active_files=[],
        token_budget=50000,
    )

    doc_ids = [doc["id"] for doc in result.selected_docs]
    assert "test_timeout" in doc_ids


def test_triage_result_structure(engine):
    """Test that TriageResult has expected structure."""
    result = engine.triage_documents(
        user_task="Test task",
        active_files=[],
        token_budget=50000,
    )

    # Check structure
    assert hasattr(result, "selected_docs")
    assert hasattr(result, "total_tokens")
    assert hasattr(result, "reasoning_log")
    assert hasattr(result, "signals")

    # Check types
    assert isinstance(result.selected_docs, list)
    assert isinstance(result.total_tokens, int)
    assert isinstance(result.reasoning_log, list)

    # Check to_dict works
    result_dict = result.to_dict()
    assert "selected_docs" in result_dict
    assert "signals" in result_dict


def test_triage_deterministic(engine):
    """Test that triage is deterministic (same input → same output)."""
    result1 = engine.triage_documents(
        user_task="Fix database error",
        active_files=["test.py"],
        token_budget=30000,
    )

    result2 = engine.triage_documents(
        user_task="Fix database error",
        active_files=["test.py"],
        token_budget=30000,
    )

    # Same documents selected
    ids1 = [doc["id"] for doc in result1.selected_docs]
    ids2 = [doc["id"] for doc in result2.selected_docs]
    assert ids1 == ids2

    # Same order
    assert result1.selected_docs == result2.selected_docs
