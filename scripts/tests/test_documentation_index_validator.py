"""Tests for documentation index validator.

Tests schema validation, file existence checks, and dependency resolution.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Import from parent directory
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from validate_documentation_index import (
    DocumentationIndexValidator,
    ValidationResult,
)


@pytest.fixture
def temp_project():
    """Create a temporary project structure with engineering-dna."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        
        # Create engineering-dna directory structure
        eng_dna = project / "engineering-dna"
        eng_dna.mkdir()
        (eng_dna / "metadata").mkdir()
        (eng_dna / "standards").mkdir()
        (eng_dna / "protocols").mkdir()
        (eng_dna / "patterns").mkdir()
        
        yield project


@pytest.fixture
def valid_index_data():
    """Create valid index data structure."""
    return {
        "schema_version": "1.0",
        "last_updated": "2026-01-08",
        "corpus_stats": {
            "total_documents": 3,
            "total_tokens_estimated": 3000,
        },
        "documents": [
            {
                "id": "agent_context",
                "path": "AGENT-CONTEXT.md",
                "category": "root",
                "token_estimate": 1000,
                "dependencies": {
                    "load_with": [],
                    "load_after": [],
                },
            },
            {
                "id": "standards_python",
                "path": "standards/python.md",
                "category": "standard",
                "token_estimate": 1000,
                "dependencies": {
                    "load_with": [],
                    "load_after": [],
                },
            },
            {
                "id": "protocols_fail_hard",
                "path": "protocols/fail-hard.md",
                "category": "protocol",
                "token_estimate": 1000,
                "dependencies": {
                    "load_with": ["standards_python"],
                    "load_after": [],
                },
            },
        ],
    }


def test_load_index_success(temp_project, valid_index_data):
    """Test successful index loading."""
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(valid_index_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    assert len(validator.documents) == 3
    assert "agent_context" in validator.documents


def test_load_index_missing_file(temp_project):
    """Test error handling for missing index file."""
    index_path = temp_project / "engineering-dna" / "metadata" / "nonexistent.json"
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    with pytest.raises(RuntimeError, match="Index file not found"):
        validator.load_index()


def test_load_index_invalid_json(temp_project):
    """Test error handling for invalid JSON."""
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text("{ invalid json }")
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    with pytest.raises(RuntimeError, match="Invalid JSON"):
        validator.load_index()


def test_validate_schema_valid(temp_project, valid_index_data):
    """Test schema validation with valid data."""
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(valid_index_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    errors = validator.validate_schema()
    assert len(errors) == 0


def test_validate_schema_missing_top_level_field(temp_project):
    """Test schema validation with missing top-level field."""
    invalid_data = {
        "documents": [],
        # Missing schema_version and corpus_stats
    }
    
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(invalid_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    errors = validator.validate_schema()
    assert any("schema_version" in err for err in errors)
    assert any("corpus_stats" in err for err in errors)


def test_validate_schema_missing_document_field(temp_project):
    """Test schema validation with missing document field."""
    invalid_data = {
        "schema_version": "1.0",
        "corpus_stats": {"total_documents": 1},
        "documents": [
            {
                "id": "test_doc",
                "path": "test.md",
                # Missing category and token_estimate
            }
        ],
    }
    
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(invalid_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    errors = validator.validate_schema()
    assert any("category" in err and "test_doc" in err for err in errors)
    assert any("token_estimate" in err and "test_doc" in err for err in errors)


def test_check_file_existence_all_exist(temp_project, valid_index_data):
    """Test file existence check when all files exist."""
    eng_dna = temp_project / "engineering-dna"
    
    # Create all referenced files
    (eng_dna / "AGENT-CONTEXT.md").write_text("# Agent Context")
    (eng_dna / "standards" / "python.md").write_text("# Python Standard")
    (eng_dna / "protocols" / "fail-hard.md").write_text("# Fail Hard Protocol")
    
    index_path = eng_dna / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(valid_index_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    missing = validator.check_file_existence()
    assert len(missing) == 0


def test_check_file_existence_missing_files(temp_project, valid_index_data):
    """Test file existence check when files are missing."""
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(valid_index_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    missing = validator.check_file_existence()
    assert len(missing) == 3  # All files missing
    assert "AGENT-CONTEXT.md" in missing
    assert "standards/python.md" in missing


def test_check_orphaned_dependencies_none(temp_project, valid_index_data):
    """Test orphaned dependency check with valid dependencies."""
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(valid_index_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    orphaned = validator.check_orphaned_dependencies()
    assert len(orphaned) == 0


def test_check_orphaned_dependencies_found(temp_project):
    """Test orphaned dependency detection."""
    invalid_data = {
        "schema_version": "1.0",
        "corpus_stats": {"total_documents": 2},
        "documents": [
            {
                "id": "doc1",
                "path": "doc1.md",
                "category": "standard",
                "token_estimate": 1000,
                "dependencies": {
                    "load_with": ["nonexistent_doc"],  # Orphaned
                    "load_after": [],
                },
            },
            {
                "id": "doc2",
                "path": "doc2.md",
                "category": "protocol",
                "token_estimate": 1000,
                "dependencies": {
                    "load_with": [],
                    "load_after": ["another_missing_doc"],  # Orphaned
                },
            },
        ],
    }
    
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(invalid_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    orphaned = validator.check_orphaned_dependencies()
    assert len(orphaned) == 2
    assert ("doc1", "nonexistent_doc") in orphaned
    assert ("doc2", "another_missing_doc") in orphaned


def test_estimate_tokens(temp_project):
    """Test token estimation for files."""
    test_file = temp_project / "test.md"
    # Write content with ~100 words
    content = " ".join(["word"] * 100)
    test_file.write_text(content)
    
    validator = DocumentationIndexValidator(
        temp_project / "index.json",
        temp_project
    )
    
    tokens = validator.estimate_tokens(test_file)
    # Should be around 130 tokens (100 words * 1.3)
    assert 120 < tokens < 140


def test_check_stale_token_estimates(temp_project, valid_index_data):
    """Test detection of stale token estimates."""
    eng_dna = temp_project / "engineering-dna"
    
    # Create file with different token count than indexed
    python_file = eng_dna / "standards" / "python.md"
    # Write much more content than indexed (1000 tokens)
    python_file.write_text(" ".join(["word"] * 2000))  # ~2600 tokens
    
    index_path = eng_dna / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(valid_index_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    stale = validator.check_stale_token_estimates(tolerance_percent=20)
    assert len(stale) >= 1
    # Should detect standards/python.md as stale


def test_find_undocumented_files(temp_project, valid_index_data):
    """Test detection of undocumented markdown files."""
    eng_dna = temp_project / "engineering-dna"
    
    # Create files in index
    (eng_dna / "standards" / "python.md").write_text("# Python")
    
    # Create undocumented files
    (eng_dna / "standards" / "undocumented.md").write_text("# Undocumented")
    (eng_dna / "protocols" / "new-protocol.md").write_text("# New")
    
    index_path = eng_dna / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(valid_index_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    undocumented = validator.find_undocumented_files()
    assert len(undocumented) >= 2
    paths_str = [str(p) for p in undocumented]
    assert any("undocumented.md" in p for p in paths_str)
    assert any("new-protocol.md" in p for p in paths_str)


def test_detect_dependency_cycles_none(temp_project, valid_index_data):
    """Test cycle detection with no cycles."""
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(valid_index_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    cycles = validator.detect_dependency_cycles()
    assert len(cycles) == 0


def test_detect_dependency_cycles_found(temp_project):
    """Test cycle detection with circular dependencies."""
    cyclic_data = {
        "schema_version": "1.0",
        "corpus_stats": {"total_documents": 3},
        "documents": [
            {
                "id": "doc1",
                "path": "doc1.md",
                "category": "standard",
                "token_estimate": 1000,
                "dependencies": {
                    "load_with": [],
                    "load_after": ["doc2"],  # doc1 → doc2
                },
            },
            {
                "id": "doc2",
                "path": "doc2.md",
                "category": "standard",
                "token_estimate": 1000,
                "dependencies": {
                    "load_with": [],
                    "load_after": ["doc3"],  # doc2 → doc3
                },
            },
            {
                "id": "doc3",
                "path": "doc3.md",
                "category": "standard",
                "token_estimate": 1000,
                "dependencies": {
                    "load_with": [],
                    "load_after": ["doc1"],  # doc3 → doc1 (cycle!)
                },
            },
        ],
    }
    
    index_path = temp_project / "engineering-dna" / "metadata" / "documentation-index.json"
    index_path.write_text(json.dumps(cyclic_data))
    
    validator = DocumentationIndexValidator(index_path, temp_project)
    validator.load_index()
    
    cycles = validator.detect_dependency_cycles()
    assert len(cycles) > 0


def test_validation_result_is_valid():
    """Test ValidationResult.is_valid() method."""
    result = ValidationResult()
    result.total_documents = 10
    assert result.is_valid()
    
    # Add violations
    result.missing_files.append("missing.md")
    assert not result.is_valid()
    
    # Clear and add other violation
    result.missing_files.clear()
    result.orphaned_dependencies.append(("doc1", "missing_dep"))
    assert not result.is_valid()


def test_validation_result_to_dict():
    """Test ValidationResult.to_dict() serialization."""
    result = ValidationResult()
    result.total_documents = 5
    result.schema_valid = False
    result.schema_errors = ["Missing field: id"]
    result.missing_files = ["test.md"]
    result.orphaned_dependencies = [("doc1", "dep1")]
    result.stale_token_estimates = [("file.md", 100, 150)]
    result.undocumented_files = [Path("new.md")]
    
    data = result.to_dict()
    assert data["status"] == "invalid"
    assert data["total_documents"] == 5
    assert not data["schema_valid"]
    assert len(data["missing_files"]) == 1
    assert len(data["orphaned_dependencies"]) == 1
    assert data["orphaned_dependencies"][0]["doc_id"] == "doc1"
