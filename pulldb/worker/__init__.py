"""Worker service package for pullDB.

Contains the queue polling implementation, restore orchestration logic,
and component modules for the full restore workflow (download, staging,
restore, post-SQL, atomic rename).
"""
