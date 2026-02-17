"""Customer name normalization utilities for pullDB.

Handles long customer names by truncating and appending a deterministic hash suffix.
This ensures unique, reproducible target database names within MySQL's constraints.

Architecture:
- MySQL database names: max 64 characters
- Staging name format: {target}_{12_hex_job_id} = target max 51 chars
- Target format: {user_code(6)}{customer(42)}{suffix(3)} = 51 chars max
- Customer max: 42 characters

For customer names > 42 chars, we truncate to 38 chars + 4 hex hash suffix = 42 chars.
The hash is deterministic (MD5-based) so the same input always produces the same output.

HCA Layer: entities (pulldb/domain/)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass


__all__ = [
    "NormalizedCustomerName",
    "normalize_customer_name",
    "normalize_customer_name_simple",
    "generate_staging_name",
    "HASH_SUFFIX_LEN",
    "MAX_CUSTOMER_LEN",
    "TRUNCATE_LEN",
    "MAX_DATABASE_NAME_LENGTH",
    "STAGING_SUFFIX_LENGTH",
    "JOB_ID_PREFIX_LENGTH",
    "MAX_TARGET_LENGTH",
    "STAGING_PATTERN_TEMPLATE",
]

logger = logging.getLogger(__name__)

# Length constraints - must match cli/parse.py constants
MAX_CUSTOMER_LEN = 42
HASH_SUFFIX_LEN = 4  # 4 hex chars = 65,536 combinations
TRUNCATE_LEN = MAX_CUSTOMER_LEN - HASH_SUFFIX_LEN  # 38 chars


@dataclass(frozen=True)
class NormalizedCustomerName:
    """Result of customer name normalization.
    
    Attributes:
        original: The original customer name as provided.
        normalized: The normalized name (may equal original if short enough).
        was_normalized: True if truncation/hashing was applied.
    """
    
    original: str
    normalized: str
    was_normalized: bool
    
    @property
    def display_message(self) -> str:
        """User-friendly message explaining the normalization.
        
        Returns empty string if no normalization was applied.
        """
        if not self.was_normalized:
            return ""
        return (
            f"Customer name '{self.original}' ({len(self.original)} chars) "
            f"exceeds {MAX_CUSTOMER_LEN} character limit. "
            f"Normalized to '{self.normalized}' for target database naming."
        )


def _compute_hash_suffix(name: str) -> str:
    """Compute deterministic 4-character alphabetic hash suffix from name.
    
    Uses MD5 for speed (not cryptographic use). Converts hash bytes to
    base-26 (a-z only) characters to ensure target database names remain
    lowercase letters only.
    
    4 chars in base-26 provides 26^4 = 456,976 unique combinations.
    """
    digest = hashlib.md5(name.encode("utf-8")).digest()
    # Use first 4 bytes to generate 4 letters
    result: list[str] = []
    for i in range(HASH_SUFFIX_LEN):
        # Take one byte and map to a-z (26 letters)
        byte_val = digest[i]
        letter = chr(ord('a') + (byte_val % 26))
        result.append(letter)
    return ''.join(result)


def normalize_customer_name(customer: str) -> NormalizedCustomerName:
    """Normalize a customer name to fit within MAX_CUSTOMER_LEN characters.
    
    If the name is <= 42 characters, returns it unchanged.
    If the name is > 42 characters, truncates to 38 chars and appends
    a 4-character deterministic hash suffix.
    
    The hash is computed from the ORIGINAL full name, ensuring:
    - Determinism: same input always produces same output
    - Uniqueness: different long names produce different hashes (with high probability)
    
    Args:
        customer: Raw customer name (lowercase letters only, pre-validated).
        
    Returns:
        NormalizedCustomerName with original, normalized name, and flag.
        
    Example:
        >>> result = normalize_customer_name("abcdefghij" * 5)  # 50 chars
        >>> result.was_normalized
        True
        >>> len(result.normalized)
        42
        >>> result.normalized[:38]
        'abcdefghijabcdefghijabcdefghijabcdefgh'
    """
    if len(customer) <= MAX_CUSTOMER_LEN:
        return NormalizedCustomerName(
            original=customer,
            normalized=customer,
            was_normalized=False,
        )
    
    # Truncate and append hash suffix
    truncated = customer[:TRUNCATE_LEN]
    hash_suffix = _compute_hash_suffix(customer)
    normalized = f"{truncated}{hash_suffix}"
    
    logger.info(
        "Customer name normalized: '%s' (%d chars) -> '%s' (%d chars)",
        customer,
        len(customer),
        normalized,
        len(normalized),
    )
    
    return NormalizedCustomerName(
        original=customer,
        normalized=normalized,
        was_normalized=True,
    )


def normalize_customer_name_simple(customer: str) -> str:
    """Convenience wrapper that returns just the normalized name string.
    
    Use when you only need the final name and don't need to track
    whether normalization occurred.
    
    Args:
        customer: Raw customer name.
        
    Returns:
        Normalized customer name (42 chars or less).
    """
    return normalize_customer_name(customer).normalized


# ---------------------------------------------------------------------------
# Staging name generation
# ---------------------------------------------------------------------------
# These constants and the ``generate_staging_name`` function were extracted
# from ``pulldb/worker/staging.py`` so that domain-layer code (e.g. the
# enqueue service) can use them without importing from the features layer.
# ``pulldb/worker/staging.py`` re-exports them for backward compatibility.

import re as _re

from pulldb.domain.errors import StagingError

# MySQL database name length limit (63 chars but we use 64 for legacy compat)
MAX_DATABASE_NAME_LENGTH = 64

# Staging suffix length: underscore + 12 hex chars from job_id
STAGING_SUFFIX_LENGTH = 13

# Job ID prefix length for staging suffix (hex characters)
JOB_ID_PREFIX_LENGTH = 12

# Maximum target database name length (derived)
MAX_TARGET_LENGTH = MAX_DATABASE_NAME_LENGTH - STAGING_SUFFIX_LENGTH

# Pattern for matching orphaned staging databases: {target}_[0-9a-f]{12}
STAGING_PATTERN_TEMPLATE = r"^{target}_[0-9a-f]{{12}}$"


def generate_staging_name(target_db: str, job_id: str) -> str:
    """Generate staging database name from target and job_id.

    Format: {target}_{job_id_first_12_chars}
    Example: jdoecustomer_550e8400e29b

    Args:
        target_db: Final target database name (must be <= 51 chars).
        job_id: Job UUID (will use first 12 hex characters).

    Returns:
        Staging database name.

    Raises:
        StagingError: If target_db exceeds maximum length (51 chars) or
            job_id is too short (< 12 chars).
    """
    max_target_length = MAX_DATABASE_NAME_LENGTH - STAGING_SUFFIX_LENGTH

    if len(target_db) > max_target_length:
        raise StagingError(
            f"Target database name '{target_db}' is {len(target_db)} chars, "
            f"exceeds maximum of {max_target_length} chars. "
            f"Staging name would exceed MySQL's {MAX_DATABASE_NAME_LENGTH} char limit. "
            f"Choose a shorter customer ID or username."
        )

    if len(job_id) < JOB_ID_PREFIX_LENGTH:
        raise StagingError(
            f"Job ID '{job_id}' is too short ({len(job_id)} chars), "
            f"need at least {JOB_ID_PREFIX_LENGTH} characters for staging suffix."
        )

    # Strip hyphens from UUID and take first 12 hex chars
    job_id_clean = job_id.replace("-", "").lower()
    job_id_prefix = job_id_clean[:JOB_ID_PREFIX_LENGTH]

    # Validate job_id prefix contains only hex characters
    if len(job_id_prefix) < JOB_ID_PREFIX_LENGTH:
        raise StagingError(
            f"Job ID '{job_id}' has insufficient hex characters after "
            f"removing hyphens ({len(job_id_prefix)} chars). "
            f"Expected at least {JOB_ID_PREFIX_LENGTH} hex digits."
        )

    if not _re.match(r"^[0-9a-f]{12}$", job_id_prefix):
        raise StagingError(
            f"Job ID prefix '{job_id_prefix}' contains non-hexadecimal characters. "
            f"Expected 12 hex digits from job_id."
        )

    staging_name = f"{target_db}_{job_id_prefix}"

    return staging_name
