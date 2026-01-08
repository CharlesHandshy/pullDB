"""
pullDB automation package.

Provides intelligent documentation triage and prompt augmentation
for engineering-dna context loading.

Main modules:
- signal_extraction: Extract task signals for triage
- triage_engine: Select relevant documentation
- prompt_augmenter: Augment prompts with guidance
"""

from __future__ import annotations

from .prompt_augmenter import PromptAugmenter, augment_prompt
from .signal_extraction import TaskSignals, extract_signals
from .triage_engine import TriageEngine, TriageResult, triage_documents

__all__ = [
    # Signal extraction
    "extract_signals",
    "TaskSignals",
    # Triage engine
    "triage_documents",
    "TriageEngine",
    "TriageResult",
    # Prompt augmenter
    "augment_prompt",
    "PromptAugmenter",
]
