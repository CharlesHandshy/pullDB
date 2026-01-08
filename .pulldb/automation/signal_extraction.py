"""
Signal extraction for documentation triage.

Analyzes task descriptions and context to extract signals that guide
document selection. Signals include:
- Keywords (stemmed, stopwords removed)
- Task type classification
- File extensions
- File path patterns
- Special flags (HCA, AWS, database, security, etc.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# Common stopwords to exclude from keyword extraction
STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "as",
    "is",
    "was",
    "are",
    "were",
    "been",
    "be",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "should",
    "could",
    "can",
    "may",
    "might",
    "this",
    "that",
    "these",
    "those",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
}

# Task type patterns (order matters - most specific first)
TASK_TYPE_PATTERNS = [
    (r"\b(test|testing|pytest|unit test|integration test)\b", "test"),
    (r"\b(fix|debug|troubleshoot|diagnose|resolve error)\b", "debug"),
    (r"\b(refactor|reorganize|restructure|clean up)\b", "refactor"),
    (r"\b(review|audit|check|validate|verify)\b", "review"),
    (
        r"\b(implement|add|create|build|develop|write|generate)\b",
        "implement",
    ),
]

# File extension patterns
FILE_EXTENSION_PATTERN = r"\b(\.\w{2,4})\b"

# File path patterns
FILE_PATH_PATTERN = r"\b([\w-]+/[\w/-]+\.?\w*)\b"


@dataclass
class TaskSignals:
    """Extracted signals from task analysis."""

    keywords: list[str]
    task_types: list[str]
    file_extensions: list[str]
    file_paths: list[str]
    special_flags: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "keywords": self.keywords,
            "task_types": self.task_types,
            "file_extensions": self.file_extensions,
            "file_paths": self.file_paths,
            "special_flags": self.special_flags,
        }


def simple_stem(word: str) -> str:
    """
    Basic stemming - remove common suffixes.

    Not as sophisticated as Porter stemmer, but sufficient for our needs.
    """
    word = word.lower()

    # Remove trailing 's' (plural)
    if word.endswith("s") and len(word) > 3 and word[-2] not in "su":
        word = word[:-1]

    # Remove -ing
    if word.endswith("ing") and len(word) > 5:
        word = word[:-3]

    # Remove -ed
    if word.endswith("ed") and len(word) > 4:
        word = word[:-2]

    return word


def extract_keywords(text: str) -> list[str]:
    """
    Extract keywords from text.

    Process:
    1. Lowercase and tokenize
    2. Remove stopwords
    3. Basic stemming
    4. Deduplicate
    5. Return most relevant (length-weighted)
    """
    # Tokenize (alphanumeric sequences)
    tokens = re.findall(r"\b[a-z]{3,}\b", text.lower())

    # Remove stopwords
    tokens = [t for t in tokens if t not in STOPWORDS]

    # Stem
    stemmed = [simple_stem(t) for t in tokens]

    # Count occurrences (frequency)
    freq: dict[str, int] = {}
    for word in stemmed:
        freq[word] = freq.get(word, 0) + 1

    # Score by frequency × length (favor longer, more specific terms)
    scored = [(word, count * len(word)) for word, count in freq.items()]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Return top keywords
    return [word for word, _score in scored[:15]]


def classify_task_type(text: str) -> list[str]:
    """
    Classify task type from action verbs.

    Returns list because a task can have multiple types
    (e.g., "refactor and test the authentication module").
    """
    text_lower = text.lower()
    types = []

    for pattern, task_type in TASK_TYPE_PATTERNS:
        if re.search(pattern, text_lower):
            types.append(task_type)

    # Default if no match
    if not types:
        types.append("implement")

    return types


def extract_file_extensions(text: str, file_paths: list[str] | None = None) -> list[str]:
    """Extract file extensions mentioned in text and from file paths."""
    extensions = set()
    
    # From text
    text_exts = re.findall(FILE_EXTENSION_PATTERN, text)
    extensions.update(ext.lower() for ext in text_exts)
    
    # From file paths
    if file_paths:
        for path in file_paths:
            # Extract extension from path
            if "." in path:
                ext = "." + path.rsplit(".", 1)[-1]
                if len(ext) <= 5:  # Reasonable extension length
                    extensions.add(ext.lower())
    
    return list(extensions)


def extract_file_paths(text: str, active_files: list[str] | None = None) -> list[str]:
    """
    Extract file paths from text and active_files.

    Active files are typically provided by the editor context.
    """
    paths = set()

    # From text
    text_paths = re.findall(FILE_PATH_PATTERN, text)
    paths.update(text_paths)

    # From active files
    if active_files:
        paths.update(active_files)

    return list(paths)


def detect_special_flags(text: str, file_paths: list[str]) -> dict[str, bool]:
    """
    Detect special conditions that trigger specific documentation.

    Flags:
    - hca_required: Mentions of layers, imports, hierarchy
    - aws_required: AWS services mentioned
    - database_required: Database/SQL operations
    - security_required: Security, authentication, validation
    - ui_required: Frontend, CSS, HTML, UX
    - testing_required: Tests, pytest, coverage
    """
    text_lower = text.lower()

    flags = {
        "hca_required": bool(
            re.search(
                r"\b(hca|hierarchy|layer|import direction|file placement)\b",
                text_lower,
            )
        ),
        "aws_required": bool(
            re.search(
                r"\b(aws|s3|secrets manager|iam|lambda|ec2|rds|aurora)\b",
                text_lower,
            )
        ),
        "database_required": bool(
            re.search(
                r"\b(database|mysql|sql|query|schema|table|migration)\b",
                text_lower,
            )
        ),
        "security_required": bool(
            re.search(
                r"\b(security|auth|authentication|authorization|owasp|xss|sql injection|validation)\b",
                text_lower,
            )
        ),
        "ui_required": bool(
            re.search(r"\b(ui|ux|frontend|css|html|button|layout|design)\b", text_lower)
        ),
        "testing_required": bool(
            re.search(r"\b(test|testing|pytest|coverage|mock|fixture)\b", text_lower)
        ),
        "python_required": bool(
            re.search(
                r"\b(python|\.py|ruff|mypy|type hint|decorator)\b", text_lower
            )
        ),
        "shell_required": bool(
            re.search(r"\b(bash|shell|script|\.sh)\b", text_lower)
        ),
    }

    # File path analysis
    for path in file_paths:
        path_lower = path.lower()
        if ".py" in path_lower:
            flags["python_required"] = True
        if ".sh" in path_lower:
            flags["shell_required"] = True
        if ".sql" in path_lower:
            flags["database_required"] = True
        if "test" in path_lower:
            flags["testing_required"] = True
        if any(ui_term in path_lower for ui_term in ["web", "ui", "css", "html"]):
            flags["ui_required"] = True

    return flags


def extract_signals(
    user_task: str, active_files: list[str] | None = None
) -> TaskSignals:
    """
    Extract all signals from task description and context.

    This is the main entry point for signal extraction.

    Args:
        user_task: User's task description
        active_files: List of currently open/active files

    Returns:
        TaskSignals with extracted information
    """
    # Normalize
    if active_files is None:
        active_files = []

    # Extract components
    keywords = extract_keywords(user_task)
    task_types = classify_task_type(user_task)
    file_paths = extract_file_paths(user_task, active_files)
    file_extensions = extract_file_extensions(user_task, file_paths)
    special_flags = detect_special_flags(user_task, file_paths)

    return TaskSignals(
        keywords=keywords,
        task_types=task_types,
        file_extensions=file_extensions,
        file_paths=file_paths,
        special_flags=special_flags,
    )


def match_score(
    signal_value: str | list[str], trigger_values: list[str]
) -> int:
    """
    Calculate match score between signal and trigger.

    Returns: Number of matches
    """
    if isinstance(signal_value, str):
        signal_value = [signal_value]

    matches = 0
    for sig in signal_value:
        for trigger in trigger_values:
            if sig.lower() in trigger.lower() or trigger.lower() in sig.lower():
                matches += 1

    return matches
