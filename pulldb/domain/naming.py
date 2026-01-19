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
    "HASH_SUFFIX_LEN",
    "MAX_CUSTOMER_LEN",
    "TRUNCATE_LEN",
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
