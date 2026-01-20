from __future__ import annotations

"""Web entities layer - Data-bound display templates for domain objects.

HCA Layer: entities

Structure:
    entities/
    ├── job/       - Job-related templates (job_row, job_card)
    ├── user/      - User-related templates (user_row)
    ├── host/      - Host-related templates (host_row)
    └── database/  - Database-related templates (database_row)

Contract:
    - Each entity template expects a specific object in context
    - Templates are self-contained and reusable
    - No business logic - pure display
"""
