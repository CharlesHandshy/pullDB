"""Mock adapters for infrastructure components.

Provides simulated versions of external dependencies for testing:
- MockS3Client: In-memory S3 simulation
- MockProcessExecutor: Fake subprocess execution
- SimulatedJobRepository: In-memory job queue
- SimulatedHostRepository: In-memory host registry
- SimulatedAuthRepository: In-memory auth/user storage

HCA Layer: shared
"""

from __future__ import annotations
