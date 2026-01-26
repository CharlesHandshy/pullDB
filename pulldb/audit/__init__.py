"""Documentation Audit Agent Package.

Continuous documentation auditing to keep KNOWLEDGE-POOL synchronized
with codebase reality. Triggered after edits to detect and update
documentation that has drifted from actual implementation.

HCA Layer: features (business logic for documentation maintenance)

TWO MODES OF OPERATION:

1. **Targeted Audit** - Uses hardcoded mappings for precise verification
   ```python
   from pulldb.audit import DocumentationAuditAgent
   agent = DocumentationAuditAgent()
   report = agent.audit_changes()  # Audit recent git changes
   report = agent.audit_full()     # Full audit of all mappings
   ```

2. **Comprehensive Drift Detection** - Scans entire codebase
   ```python
   from pulldb.audit import DocumentationAuditAgent
   agent = DocumentationAuditAgent()
   drift = agent.detect_drift()
   
   # For AI/Copilot agent integration:
   context = agent.get_copilot_context()
   print(context)  # Rich markdown for AI reasoning
   ```
"""

from pulldb.audit.agent import DocumentationAuditAgent
from pulldb.audit.drift import DriftAlert, DriftDetector, DriftType
from pulldb.audit.inventory import FileCategory, FileInventory, FileInventoryItem
from pulldb.audit.report import AuditFinding, AuditReport, FindingSeverity

__all__ = [
    # Main agent
    "DocumentationAuditAgent",
    # Targeted audit
    "AuditReport",
    "AuditFinding",
    "FindingSeverity",
    # Comprehensive drift detection
    "DriftDetector",
    "DriftAlert",
    "DriftType",
    # File inventory
    "FileInventory",
    "FileInventoryItem",
    "FileCategory",
]
