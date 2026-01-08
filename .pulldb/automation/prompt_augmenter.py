"""
Prompt augmentation for engineering-dna context injection.

Takes user tasks and augments them with relevant engineering-dna
guidance while preserving the user's original intent.

Usage:
    from .pulldb.automation import prompt_augmenter
    
    augmented = prompt_augmenter.augment_prompt(
        user_task="Fix MySQL error in restore.py",
        active_files=["pulldb/worker/restore.py"],
        token_budget=50000
    )
    
    print(augmented.final_prompt)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .triage_engine import TriageResult, triage_documents


@dataclass
class AugmentedPrompt:
    """Result of prompt augmentation."""

    final_prompt: str
    triage_result: TriageResult
    guidance_sections: dict[str, str]  # tier → content
    constraints: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "final_prompt": self.final_prompt,
            "triage_result": self.triage_result.to_dict(),
            "guidance_sections": self.guidance_sections,
            "constraints": self.constraints,
        }


class PromptAugmenter:
    """
    Augments user prompts with engineering-dna guidance.

    Process:
    1. Triage documents (select relevant docs)
    2. Load actual content from filesystem
    3. Extract key constraints/principles
    4. Format augmented prompt
    5. Preserve user intent
    """

    def __init__(
        self, engineering_dna_root: Path | None = None, index_path: Path | None = None
    ):
        """
        Initialize prompt augmenter.

        Args:
            engineering_dna_root: Root directory of engineering-dna repo
            index_path: Path to documentation index (default: auto-detect)
        """
        if engineering_dna_root is None:
            engineering_dna_root = (
                Path(__file__).parent.parent.parent / "engineering-dna"
            )

        self.engineering_dna_root = engineering_dna_root
        self.index_path = index_path

    def augment_prompt(
        self,
        user_task: str,
        active_files: list[str] | None = None,
        token_budget: int = 50000,
    ) -> AugmentedPrompt:
        """
        Main augmentation entry point.

        Args:
            user_task: User's original task description
            active_files: Currently open/active files
            token_budget: Maximum tokens for documentation (default: 50k)

        Returns:
            AugmentedPrompt with formatted prompt and metadata
        """
        # Triage documents
        triage_result = triage_documents(
            user_task=user_task,
            active_files=active_files,
            token_budget=token_budget,
            index_path=self.index_path,
        )

        # Load document content
        guidance_sections = self._load_document_content(triage_result.selected_docs)

        # Extract constraints
        constraints = self._extract_constraints(
            triage_result.selected_docs, guidance_sections
        )

        # Format final prompt
        final_prompt = self._format_prompt(user_task, guidance_sections, constraints)

        return AugmentedPrompt(
            final_prompt=final_prompt,
            triage_result=triage_result,
            guidance_sections=guidance_sections,
            constraints=constraints,
        )

    def _load_document_content(
        self, selected_docs: list[dict[str, Any]]
    ) -> dict[str, str]:
        """
        Load actual document content from filesystem.

        Groups by tier for structured presentation.

        Returns:
            Dict mapping tier label to combined content
        """
        tier_content: dict[int, list[str]] = {0: [], 1: [], 2: []}

        for doc in selected_docs:
            doc_path = self.engineering_dna_root / doc["path"]

            try:
                content = doc_path.read_text(encoding="utf-8")
                tier = doc["tier"]
                tier_content[tier].append(f"## {doc['path']}\n\n{content}")
            except FileNotFoundError:
                print(f"Warning: Document not found: {doc_path}")
            except Exception as e:
                print(f"Warning: Failed to load {doc_path}: {e}")

        # Format by tier
        sections = {}
        if tier_content[0]:
            sections["tier0_always"] = "\n\n---\n\n".join(tier_content[0])
        if tier_content[1]:
            sections["tier1_universal"] = "\n\n---\n\n".join(tier_content[1])
        if tier_content[2]:
            sections["tier2_specialized"] = "\n\n---\n\n".join(tier_content[2])

        return sections

    def _extract_constraints(
        self, selected_docs: list[dict[str, Any]], guidance_sections: dict[str, str]
    ) -> list[str]:
        """
        Extract key constraints and principles from loaded documentation.

        Looks for:
        - MUST/MUST NOT statements
        - Prohibited patterns
        - Critical rules
        - Anti-patterns
        """
        constraints: list[str] = []

        # Extract from summaries (high-level)
        for doc in selected_docs:
            summary = doc.get("summary", "")
            if summary:
                constraints.append(f"[{doc['id']}] {summary}")

        # Extract key directives from content
        import re

        for section_content in guidance_sections.values():
            # Find MUST/MUST NOT statements
            must_patterns = re.findall(
                r"(?:^|\n)\s*[*-]?\s*(MUST (?:NOT )?[^.!?\n]+[.!?])",
                section_content,
                re.MULTILINE | re.IGNORECASE,
            )
            constraints.extend(must_patterns[:3])  # Top 3 per section

            # Find prohibited patterns
            prohibited = re.findall(
                r"(?:^|\n).*(?:prohibited|forbidden|never|avoid):\s*([^\n]+)",
                section_content,
                re.IGNORECASE,
            )
            constraints.extend(prohibited[:2])  # Top 2 per section

        # Deduplicate and limit
        unique_constraints = []
        seen = set()
        for constraint in constraints:
            constraint_clean = constraint.strip().lower()
            if constraint_clean not in seen and len(constraint_clean) > 10:
                unique_constraints.append(constraint.strip())
                seen.add(constraint_clean)
                if len(unique_constraints) >= 15:  # Max 15 constraints
                    break

        return unique_constraints

    def _format_prompt(
        self,
        user_task: str,
        guidance_sections: dict[str, str],
        constraints: list[str],
    ) -> str:
        """
        Format the final augmented prompt.

        Structure:
        1. Engineering guidance (tier 0, 1, 2)
        2. User's original task (preserved)
        3. Task constraints (extracted key rules)
        """
        prompt_parts = []

        # Engineering guidance
        if "tier0_always" in guidance_sections:
            prompt_parts.append(
                f"<engineering_guidance priority=\"always\">\n"
                f"{guidance_sections['tier0_always']}\n"
                f"</engineering_guidance>"
            )

        if "tier1_universal" in guidance_sections:
            prompt_parts.append(
                f"<engineering_guidance priority=\"universal\">\n"
                f"{guidance_sections['tier1_universal']}\n"
                f"</engineering_guidance>"
            )

        if "tier2_specialized" in guidance_sections:
            prompt_parts.append(
                f"<engineering_guidance priority=\"specialized\">\n"
                f"{guidance_sections['tier2_specialized']}\n"
                f"</engineering_guidance>"
            )

        # User task (preserved exactly)
        prompt_parts.append(f"\n{user_task}\n")

        # Task constraints
        if constraints:
            constraints_text = "\n".join(f"- {c}" for c in constraints)
            prompt_parts.append(
                f"<task_constraints>\n" f"{constraints_text}\n" f"</task_constraints>"
            )

        return "\n\n".join(prompt_parts)


def augment_prompt(
    user_task: str,
    active_files: list[str] | None = None,
    token_budget: int = 50000,
    engineering_dna_root: Path | None = None,
    index_path: Path | None = None,
) -> AugmentedPrompt:
    """
    Convenience function for one-off prompt augmentation.

    For repeated operations, instantiate PromptAugmenter once.
    """
    augmenter = PromptAugmenter(engineering_dna_root, index_path)
    return augmenter.augment_prompt(user_task, active_files, token_budget)
