#!/usr/bin/env python3
"""
Demo of the triage system in action.

Shows how the system selects relevant documentation for different tasks.
"""

from pathlib import Path

# Import from current directory structure
from triage_engine import triage_documents

# Test scenarios
scenarios = [
    {
        "name": "MySQL Error",
        "task": "Fix MySQL error in restore.py",
        "files": ["pulldb/worker/restore.py"],
        "budget": 20000,
    },
    {
        "name": "New API Endpoint",
        "task": "Add new API endpoint for user authentication",
        "files": ["pulldb/api/routes.py"],
        "budget": 20000,
    },
    {
        "name": "CSS Refactor",
        "task": "Refactor CSS styles for admin dashboard",
        "files": ["pulldb/web/static/admin.css"],
        "budget": 15000,
    },
]

for scenario in scenarios:
    print(f"\n{'='*70}")
    print(f"Scenario: {scenario['name']}")
    print(f"Task: {scenario['task']}")
    print(f"Budget: {scenario['budget']:,} tokens")
    print(f"{'='*70}")

    result = triage_documents(
        user_task=scenario["task"],
        active_files=scenario["files"],
        token_budget=scenario["budget"],
    )

    print(f"\n✓ Selected {len(result.selected_docs)} documents ({result.total_tokens:,} tokens):\n")
    
    for doc in result.selected_docs:
        print(f"  • {doc['path']:<40} ({doc['token_estimate']:>5} tokens)")

    print(f"\nSignals detected:")
    print(f"  - Keywords: {', '.join(result.signals.keywords[:5])}")
    print(f"  - Task types: {', '.join(result.signals.task_types)}")
    print(f"  - File extensions: {', '.join(result.signals.file_extensions)}")
    flags = [k for k, v in result.signals.special_flags.items() if v]
    if flags:
        print(f"  - Special flags: {', '.join(flags)}")

print(f"\n{'='*70}")
print("Demo complete!")
print(f"{'='*70}\n")
