"""
Documentation Triage Engine for engineering-dna.

Implements 5-phase triage logic to intelligently select and order
documentation based on task analysis, respecting token budgets and
dependency constraints.

Usage:
    from .pulldb.automation import triage_engine
    
    result = triage_engine.triage_documents(
        user_task="Fix MySQL error in restore.py",
        active_files=["pulldb/worker/restore.py"],
        token_budget=50000
    )
    
    for doc in result.selected_docs:
        print(f"Load: {doc['path']} ({doc['token_estimate']} tokens)")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .signal_extraction import TaskSignals, extract_signals, match_score

# Default paths (relative to pullDB root)
DEFAULT_INDEX_PATH = Path(__file__).parent.parent.parent / "engineering-dna" / "metadata" / "documentation-index.json"


@dataclass
class DocumentScore:
    """Scored document candidate."""

    doc_id: str
    score: int
    metadata: dict[str, Any]
    reasoning: list[str] = field(default_factory=list)

    def __lt__(self, other: DocumentScore) -> bool:
        """Sort by score descending."""
        return self.score > other.score


@dataclass
class TriageResult:
    """Result of triage operation."""

    selected_docs: list[dict[str, Any]]
    total_tokens: int
    reasoning_log: list[str]
    signals: TaskSignals

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "selected_docs": self.selected_docs,
            "total_tokens": self.total_tokens,
            "reasoning_log": self.reasoning_log,
            "signals": self.signals.to_dict(),
        }


class TriageEngine:
    """
    Documentation triage engine.

    Phases:
    1. Always-load (tier-0 docs)
    2. Context analysis (extract signals)
    3. Candidate scoring (relevance scoring)
    4. Dependency resolution (with token budget)
    5. Topological sorting (ordering)
    """

    def __init__(self, index_path: Path | None = None):
        """
        Initialize triage engine.

        Args:
            index_path: Path to documentation-index.json (default: auto-detect)
        """
        if index_path is None:
            index_path = DEFAULT_INDEX_PATH

        self.index_path = index_path
        self.index = self._load_index()

    def _load_index(self) -> dict[str, Any]:
        """Load documentation index from JSON."""
        try:
            with open(self.index_path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Documentation index not found: {self.index_path}\n"
                "Run: cd engineering-dna && python3 metadata/build-index.py"
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid index JSON: {e}")

    def triage_documents(
        self,
        user_task: str,
        active_files: list[str] | None = None,
        token_budget: int = 50000,
    ) -> TriageResult:
        """
        Main triage entry point.

        Args:
            user_task: User's task description
            active_files: Currently open/active files
            token_budget: Maximum tokens to load (default: 50k)

        Returns:
            TriageResult with selected docs, token count, reasoning
        """
        reasoning_log: list[str] = []

        # Phase 1: Always-load (tier-0)
        always_load = self._phase1_always_load()
        current_tokens = sum(doc["token_estimate"] for doc in always_load)
        reasoning_log.append(
            f"Phase 1: Loaded {len(always_load)} tier-0 docs ({current_tokens} tokens)"
        )

        # Phase 2: Context analysis
        signals = extract_signals(user_task, active_files)
        reasoning_log.append(
            f"Phase 2: Extracted signals - "
            f"keywords={len(signals.keywords)}, "
            f"task_types={signals.task_types}, "
            f"file_exts={signals.file_extensions}, "
            f"flags={sum(signals.special_flags.values())}"
        )

        # Phase 3: Candidate scoring
        scored_candidates = self._phase3_score_candidates(signals, always_load)
        reasoning_log.append(
            f"Phase 3: Scored {len(scored_candidates)} candidates "
            f"(top score: {scored_candidates[0].score if scored_candidates else 0})"
        )

        # Phase 4: Dependency resolution with token budget
        selected_docs = self._phase4_resolve_dependencies(
            scored_candidates,
            always_load,
            token_budget,
            current_tokens,
            reasoning_log,
        )

        # Phase 5: Topological sorting
        ordered_docs = self._phase5_topological_sort(selected_docs)
        total_tokens = sum(doc["token_estimate"] for doc in ordered_docs)
        reasoning_log.append(
            f"Phase 5: Ordered {len(ordered_docs)} docs ({total_tokens} tokens)"
        )

        return TriageResult(
            selected_docs=ordered_docs,
            total_tokens=total_tokens,
            reasoning_log=reasoning_log,
            signals=signals,
        )

    def _phase1_always_load(self) -> list[dict[str, Any]]:
        """Phase 1: Load tier-0 (always-load) documents."""
        always_load = []
        for doc in self.index["documents"]:
            if doc["priority"] == "always_load":
                always_load.append(doc)
        return always_load

    def _phase3_score_candidates(
        self, signals: TaskSignals, already_loaded: list[dict[str, Any]]
    ) -> list[DocumentScore]:
        """
        Phase 3: Score document candidates by relevance.

        Scoring formula:
            score = keyword_matches * 10
                  + task_type_match * 15
                  + file_extension_match * 20
                  + file_path_match * 20
                  + priority_boost (always_load +100, conditional +50)
                  + tier_boost ((3 - tier) * 3)
                  + special_flag_boost * 30
        """
        already_loaded_ids = {doc["id"] for doc in already_loaded}
        scored: list[DocumentScore] = []

        for doc in self.index["documents"]:
            # Skip already loaded
            if doc["id"] in already_loaded_ids:
                continue

            score = 0
            reasoning: list[str] = []
            triggers = doc["triggers"]

            # Keyword matching
            keyword_matches = match_score(signals.keywords, triggers.get("keywords", []))
            if keyword_matches > 0:
                score += keyword_matches * 10
                reasoning.append(f"keywords({keyword_matches})")

            # Task type matching
            task_type_matches = match_score(
                signals.task_types, triggers.get("task_types", [])
            )
            if task_type_matches > 0:
                score += task_type_matches * 15
                reasoning.append(f"task_types({task_type_matches})")

            # File extension matching
            ext_matches = match_score(
                signals.file_extensions, triggers.get("file_extensions", [])
            )
            if ext_matches > 0:
                score += ext_matches * 20
                reasoning.append(f"file_ext({ext_matches})")

            # File path matching
            path_matches = match_score(signals.file_paths, triggers.get("file_paths", []))
            if path_matches > 0:
                score += path_matches * 20
                reasoning.append(f"file_path({path_matches})")

            # Priority boost
            if doc["priority"] == "always_load":
                score += 100
                reasoning.append("always_load")
            elif doc["priority"] == "conditional":
                score += 50
                reasoning.append("conditional")

            # Tier boost (prefer universal over specialized)
            tier_boost = (3 - doc["tier"]) * 3
            score += tier_boost
            reasoning.append(f"tier_{doc['tier']}({tier_boost})")

            # Special flags (direct mapping)
            special_boost = 0
            doc_id = doc["id"]
            flags = signals.special_flags

            if flags.get("hca_required") and "hca" in doc_id:
                special_boost += 30
            if flags.get("aws_required") and "aws" in doc_id:
                special_boost += 30
            if flags.get("database_required") and ("database" in doc_id or "sql" in doc_id):
                special_boost += 30
            if flags.get("security_required") and "security" in doc_id:
                special_boost += 30
            if flags.get("ui_required") and ("ui" in doc_id or "internal_ui" in doc_id):
                special_boost += 30
            if flags.get("testing_required") and "test" in doc_id:
                special_boost += 30
            if flags.get("python_required") and "python" in doc_id:
                special_boost += 30
            if flags.get("shell_required") and "shell" in doc_id:
                special_boost += 30

            if special_boost > 0:
                score += special_boost
                reasoning.append(f"special_flags({special_boost})")

            # Only include if score > 0
            if score > 0:
                scored.append(
                    DocumentScore(
                        doc_id=doc["id"],
                        score=score,
                        metadata=doc,
                        reasoning=reasoning,
                    )
                )

        # Sort by score descending
        scored.sort()
        return scored

    def _phase4_resolve_dependencies(
        self,
        candidates: list[DocumentScore],
        already_loaded: list[dict[str, Any]],
        token_budget: int,
        current_tokens: int,
        reasoning_log: list[str],
    ) -> list[dict[str, Any]]:
        """
        Phase 4: Resolve dependencies while respecting token budget.

        Algorithm:
        1. Process candidates in score order
        2. For each candidate:
           a. Check if adding it + dependencies exceeds budget
           b. If within budget, add dependencies first (load_with)
           c. Then add candidate
        3. Track selected IDs to avoid duplicates
        """
        selected: list[dict[str, Any]] = list(already_loaded)
        selected_ids = {doc["id"] for doc in selected}
        doc_map = {doc["id"]: doc for doc in self.index["documents"]}

        for candidate in candidates:
            doc = candidate.metadata
            doc_id = doc["id"]

            # Already selected?
            if doc_id in selected_ids:
                continue

            # Calculate total cost (doc + unselected dependencies)
            deps = doc.get("dependencies", {}).get("load_with", [])
            total_cost = doc["token_estimate"]
            deps_to_add = []

            for dep_id in deps:
                if dep_id not in selected_ids and dep_id in doc_map:
                    deps_to_add.append(doc_map[dep_id])
                    total_cost += doc_map[dep_id]["token_estimate"]

            # Check budget
            if current_tokens + total_cost > token_budget:
                reasoning_log.append(
                    f"  Skipped {doc_id} (would exceed budget by "
                    f"{current_tokens + total_cost - token_budget} tokens)"
                )
                continue

            # Add dependencies first
            for dep_doc in deps_to_add:
                selected.append(dep_doc)
                selected_ids.add(dep_doc["id"])
                current_tokens += dep_doc["token_estimate"]
                reasoning_log.append(
                    f"  Added dependency {dep_doc['id']} ({dep_doc['token_estimate']} tokens)"
                )

            # Add candidate
            selected.append(doc)
            selected_ids.add(doc_id)
            current_tokens += doc["token_estimate"]
            reasoning_log.append(
                f"  Added {doc_id} (score={candidate.score}, "
                f"{doc['token_estimate']} tokens) - {', '.join(candidate.reasoning)}"
            )

        return selected

    def _phase5_topological_sort(
        self, docs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Phase 5: Topologically sort documents by load_after dependencies.

        Uses Kahn's algorithm for topological sorting.
        If cycle detected, falls back to current order.
        """
        # Build adjacency list and in-degree count
        doc_map = {doc["id"]: doc for doc in docs}
        doc_ids = set(doc_map.keys())

        adj: dict[str, list[str]] = {doc_id: [] for doc_id in doc_ids}
        in_degree: dict[str, int] = {doc_id: 0 for doc_id in doc_ids}

        for doc in docs:
            doc_id = doc["id"]
            load_after = doc.get("dependencies", {}).get("load_after", [])
            for dep_id in load_after:
                if dep_id in doc_ids:
                    adj[dep_id].append(doc_id)
                    in_degree[doc_id] += 1

        # Kahn's algorithm
        queue = [doc_id for doc_id, degree in in_degree.items() if degree == 0]
        sorted_ids: list[str] = []

        while queue:
            # Sort queue for deterministic output
            queue.sort()
            current = queue.pop(0)
            sorted_ids.append(current)

            for neighbor in adj[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for cycle
        if len(sorted_ids) != len(docs):
            # Cycle detected, return original order
            return docs

        # Return sorted order
        return [doc_map[doc_id] for doc_id in sorted_ids]


def triage_documents(
    user_task: str,
    active_files: list[str] | None = None,
    token_budget: int = 50000,
    index_path: Path | None = None,
) -> TriageResult:
    """
    Convenience function for one-off triage.

    For repeated triage operations, instantiate TriageEngine once
    to avoid re-loading the index.
    """
    engine = TriageEngine(index_path)
    return engine.triage_documents(user_task, active_files, token_budget)
