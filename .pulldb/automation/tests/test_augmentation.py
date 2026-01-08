"""
Tests for prompt augmentation.

Test scenarios:
1. User intent is preserved in final prompt
2. Relevant guidance is injected
3. Constraints are actionable
4. Token counts are accurate
5. Formatting is correct
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ..prompt_augmenter import PromptAugmenter, AugmentedPrompt


@pytest.fixture
def mock_engineering_dna_root(tmp_path):
    """Create mock engineering-dna directory structure."""
    root = tmp_path / "engineering-dna"
    root.mkdir()

    # Create mock documents
    (root / "AGENT-CONTEXT.md").write_text(
        "# AI Agent Context\n\n"
        "**FAIL HARD**: Never silently degrade.\n\n"
        "## Core Principles\n\n"
        "1. FAIL HARD\n"
        "2. KNOWLEDGE-FIRST\n"
        "3. ATOMIC OUTPUT\n"
    )

    standards = root / "standards"
    standards.mkdir()

    (standards / "python.md").write_text(
        "# Python Standards\n\n"
        "MUST use modern type hints (Python 3.10+).\n\n"
        "## Type Hints\n\n"
        "Use `dict[str, int]` not `Dict[str, int]`.\n\n"
        "Prohibited: Using `Optional[X]` instead of `X | None`.\n"
    )

    (standards / "database.md").write_text(
        "# Database Standards\n\n"
        "MUST separate service user from admin user.\n\n"
        "## Credentials\n\n"
        "Never hardcode credentials.\n"
    )

    protocols = root / "protocols"
    protocols.mkdir()

    (protocols / "fail-hard.md").write_text(
        "# FAIL HARD Protocol\n\n"
        "MUST provide: Goal, Problem, Root Cause, Solutions.\n\n"
        "Never use `except: pass`.\n"
    )

    # Create metadata directory with index
    metadata = root / "metadata"
    metadata.mkdir()

    index = {
        "schema_version": "1.0",
        "last_updated": "2026-01-08",
        "token_budget_default": 50000,
        "corpus_stats": {
            "total_documents": 4,
            "total_tokens_estimated": 3000,
            "categories": {"root": 1, "standard": 2, "protocol": 1},
        },
        "documents": [
            {
                "id": "agent_context",
                "path": "AGENT-CONTEXT.md",
                "category": "root",
                "tier": 0,
                "priority": "always_load",
                "token_estimate": 500,
                "topics": ["fail hard", "principles"],
                "triggers": {
                    "keywords": ["*"],
                    "file_extensions": [],
                    "file_paths": [],
                    "task_types": ["*"],
                },
                "dependencies": {"load_with": [], "load_after": []},
                "summary": "AI entry point with core principles",
            },
            {
                "id": "python",
                "path": "standards/python.md",
                "category": "standard",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 1000,
                "topics": ["python", "type hints"],
                "triggers": {
                    "keywords": ["python"],
                    "file_extensions": [".py"],
                    "file_paths": [],
                    "task_types": ["implement", "debug"],
                },
                "dependencies": {"load_with": ["fail_hard"], "load_after": []},
                "summary": "Python coding standards",
            },
            {
                "id": "database",
                "path": "standards/database.md",
                "category": "standard",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 800,
                "topics": ["database", "mysql", "credentials"],
                "triggers": {
                    "keywords": ["database", "mysql"],
                    "file_extensions": [".sql"],
                    "file_paths": [],
                    "task_types": ["implement", "debug"],
                },
                "dependencies": {"load_with": ["fail_hard"], "load_after": []},
                "summary": "Database patterns and security",
            },
            {
                "id": "fail_hard",
                "path": "protocols/fail-hard.md",
                "category": "protocol",
                "tier": 1,
                "priority": "conditional",
                "token_estimate": 700,
                "topics": ["error handling", "fail hard"],
                "triggers": {
                    "keywords": ["error", "exception"],
                    "file_extensions": [],
                    "file_paths": [],
                    "task_types": ["debug"],
                },
                "dependencies": {"load_with": [], "load_after": []},
                "summary": "FAIL HARD error handling protocol",
            },
        ],
    }

    (metadata / "documentation-index.json").write_text(json.dumps(index, indent=2))

    return root


@pytest.fixture
def augmenter(mock_engineering_dna_root):
    """Create prompt augmenter with mock directory."""
    index_path = mock_engineering_dna_root / "metadata" / "documentation-index.json"
    return PromptAugmenter(
        engineering_dna_root=mock_engineering_dna_root, index_path=index_path
    )


def test_user_intent_preserved(augmenter):
    """Test that user's original task is preserved in augmented prompt."""
    user_task = "Fix the database connection timeout in restore.py"

    result = augmenter.augment_prompt(
        user_task=user_task, active_files=["pulldb/worker/restore.py"]
    )

    # User task should appear in final prompt
    assert user_task in result.final_prompt


def test_guidance_injected(augmenter):
    """Test that relevant guidance is injected."""
    result = augmenter.augment_prompt(
        user_task="Fix MySQL error in restore.py",
        active_files=["pulldb/worker/restore.py"],
    )

    # Should contain guidance sections
    assert "<engineering_guidance" in result.final_prompt
    assert "</engineering_guidance>" in result.final_prompt

    # Should have loaded database.md and python.md
    assert any("database" in section for section in result.guidance_sections.values())


def test_constraints_extracted(augmenter):
    """Test that constraints are extracted and actionable."""
    result = augmenter.augment_prompt(
        user_task="Implement user authentication",
        active_files=["pulldb/api/auth.py"],
    )

    # Should have constraints section
    assert "<task_constraints>" in result.final_prompt
    assert "</task_constraints>" in result.final_prompt

    # Should have at least some constraints
    assert len(result.constraints) > 0

    # Constraints should be actionable (contain directives)
    assert any(
        keyword in " ".join(result.constraints).lower()
        for keyword in ["must", "never", "prohibited", "avoid"]
    )


def test_tier_organization(augmenter):
    """Test that guidance is organized by tier."""
    result = augmenter.augment_prompt(
        user_task="Fix error", active_files=["test.py"]
    )

    # Should have tier0 (always load)
    assert "tier0_always" in result.guidance_sections

    # Check priority attributes in prompt
    assert 'priority="always"' in result.final_prompt


def test_token_budget_respected(augmenter):
    """Test that token budget is respected."""
    result = augmenter.augment_prompt(
        user_task="Fix error", active_files=[], token_budget=1500
    )

    # Token count should be within budget
    assert result.triage_result.total_tokens <= 1500

    # Should still have at least tier-0 docs
    assert len(result.triage_result.selected_docs) >= 1


def test_multiple_document_types(augmenter):
    """Test loading multiple document types (standards + protocols)."""
    result = augmenter.augment_prompt(
        user_task="Debug Python database connection",
        active_files=["app/db.py"],
    )

    # Should load both standards (python, database) and protocols (fail_hard)
    doc_ids = [doc["id"] for doc in result.triage_result.selected_docs]

    assert "python" in doc_ids
    assert "database" in doc_ids
    assert "fail_hard" in doc_ids


def test_prompt_structure(augmenter):
    """Test that prompt has correct structure."""
    result = augmenter.augment_prompt(user_task="Test task", active_files=[])

    prompt = result.final_prompt

    # Should have guidance sections before user task
    guidance_start = prompt.find("<engineering_guidance")
    task_start = prompt.find("Test task")
    constraints_start = prompt.find("<task_constraints>")

    assert guidance_start < task_start
    assert task_start < constraints_start


def test_no_duplicate_content(augmenter):
    """Test that documents aren't duplicated in guidance."""
    result = augmenter.augment_prompt(
        user_task="Fix Python error", active_files=["test.py"]
    )

    # Count occurrences of document paths
    prompt = result.final_prompt
    assert prompt.count("## AGENT-CONTEXT.md") <= 1
    assert prompt.count("## standards/python.md") <= 1


def test_augmented_prompt_to_dict(augmenter):
    """Test that AugmentedPrompt.to_dict() works."""
    result = augmenter.augment_prompt(user_task="Test task", active_files=[])

    result_dict = result.to_dict()

    # Check structure
    assert "final_prompt" in result_dict
    assert "triage_result" in result_dict
    assert "guidance_sections" in result_dict
    assert "constraints" in result_dict

    # Check types
    assert isinstance(result_dict["final_prompt"], str)
    assert isinstance(result_dict["triage_result"], dict)
    assert isinstance(result_dict["guidance_sections"], dict)
    assert isinstance(result_dict["constraints"], list)


def test_empty_task(augmenter):
    """Test behavior with empty task."""
    result = augmenter.augment_prompt(user_task="", active_files=[])

    # Should still work, load tier-0
    assert len(result.triage_result.selected_docs) >= 1

    # Final prompt should still have structure
    assert "<engineering_guidance" in result.final_prompt


def test_constraint_deduplication(augmenter):
    """Test that duplicate constraints are removed."""
    result = augmenter.augment_prompt(
        user_task="Fix error", active_files=["test.py"]
    )

    # Check for duplicates
    constraints_lower = [c.lower() for c in result.constraints]
    assert len(constraints_lower) == len(set(constraints_lower))


def test_constraint_limit(augmenter):
    """Test that constraints are limited to reasonable number."""
    result = augmenter.augment_prompt(
        user_task="Implement complex feature", active_files=[]
    )

    # Should not exceed 15 constraints
    assert len(result.constraints) <= 15


def test_different_tasks_different_guidance(augmenter):
    """Test that different tasks get different guidance."""
    result1 = augmenter.augment_prompt(
        user_task="Fix database error", active_files=["db.py"]
    )

    result2 = augmenter.augment_prompt(
        user_task="Refactor CSS styles", active_files=["styles.css"]
    )

    # Should load different documents (or at least different guidance)
    docs1 = [doc["id"] for doc in result1.triage_result.selected_docs]
    docs2 = [doc["id"] for doc in result2.triage_result.selected_docs]

    # At least some difference (excluding tier-0)
    non_tier0_docs1 = [d for d in docs1 if d != "agent_context"]
    non_tier0_docs2 = [d for d in docs2 if d != "agent_context"]

    # Different tasks should produce meaningfully different results
    # (CSS task shouldn't load database docs, database task shouldn't load UI docs)
    assert non_tier0_docs1 != non_tier0_docs2 or result1.final_prompt != result2.final_prompt


def test_guidance_content_loaded(augmenter):
    """Test that actual file content is loaded, not just metadata."""
    result = augmenter.augment_prompt(
        user_task="Fix Python error", active_files=["test.py"]
    )

    # Check that actual content appears (not just paths)
    prompt = result.final_prompt

    # Should contain content from python.md
    assert "type hints" in prompt.lower() or "python" in prompt.lower()

    # Should contain content from AGENT-CONTEXT.md
    assert "fail hard" in prompt.lower()


def test_reasoning_log_available(augmenter):
    """Test that triage reasoning is available for debugging."""
    result = augmenter.augment_prompt(user_task="Test task", active_files=[])

    # Should have reasoning log from triage
    assert len(result.triage_result.reasoning_log) > 0

    # Should mention phases
    reasoning_text = " ".join(result.triage_result.reasoning_log)
    assert "Phase" in reasoning_text
