"""Unit tests for pulldb.domain.naming module."""

from __future__ import annotations

import pytest

from pulldb.domain.naming import (
    HASH_SUFFIX_LEN,
    MAX_CUSTOMER_LEN,
    TRUNCATE_LEN,
    NormalizedCustomerName,
    normalize_customer_name,
    normalize_customer_name_simple,
)


class TestConstants:
    """Verify naming constants are consistent."""
    
    def test_max_customer_len(self) -> None:
        assert MAX_CUSTOMER_LEN == 42
    
    def test_hash_suffix_len(self) -> None:
        assert HASH_SUFFIX_LEN == 4
    
    def test_truncate_len(self) -> None:
        assert TRUNCATE_LEN == 38
        assert TRUNCATE_LEN + HASH_SUFFIX_LEN == MAX_CUSTOMER_LEN


class TestNormalizeCustomerName:
    """Tests for normalize_customer_name function."""
    
    def test_short_name_unchanged(self) -> None:
        """Names <= 42 chars should pass through unchanged."""
        result = normalize_customer_name("acme")
        assert result.original == "acme"
        assert result.normalized == "acme"
        assert result.was_normalized is False
        assert result.display_message == ""
    
    def test_exactly_42_chars_unchanged(self) -> None:
        """Exactly 42 chars should not be normalized."""
        name = "a" * 42
        result = normalize_customer_name(name)
        assert result.normalized == name
        assert result.was_normalized is False
    
    def test_43_chars_normalized(self) -> None:
        """43 chars should trigger normalization."""
        name = "a" * 43
        result = normalize_customer_name(name)
        assert result.was_normalized is True
        assert len(result.normalized) == 42
        assert result.normalized[:38] == "a" * 38
    
    def test_long_name_truncated_with_hash(self) -> None:
        """Long names should be truncated to 38 chars + 4 char hash."""
        long_name = "abcdefghijklmnopqrstuvwxyz" * 3  # 78 chars
        result = normalize_customer_name(long_name)
        
        assert result.was_normalized is True
        assert len(result.normalized) == 42
        assert result.normalized[:38] == long_name[:38]
        # Hash suffix should be 4 lowercase letters (a-z only)
        assert len(result.normalized[38:]) == 4
        assert all(c in "abcdefghijklmnopqrstuvwxyz" for c in result.normalized[38:])
    
    def test_deterministic_hash(self) -> None:
        """Same input should always produce same output."""
        name = "verylongcustomernamethatexceedsthelimit" * 2
        result1 = normalize_customer_name(name)
        result2 = normalize_customer_name(name)
        
        assert result1.normalized == result2.normalized
    
    def test_different_long_names_different_hashes(self) -> None:
        """Different long names should produce different hashes."""
        name1 = "a" * 50
        name2 = "b" * 50
        
        result1 = normalize_customer_name(name1)
        result2 = normalize_customer_name(name2)
        
        # Truncated portions are different, hashes should differ too
        assert result1.normalized != result2.normalized
    
    def test_similar_long_names_different_hashes(self) -> None:
        """Names that truncate to same prefix should have different hashes."""
        # Both will truncate to "a" * 38, but full name differs
        name1 = "a" * 50
        name2 = "a" * 38 + "b" * 12  # Same first 38, different after
        
        result1 = normalize_customer_name(name1)
        result2 = normalize_customer_name(name2)
        
        # Same truncated prefix but different full names = different hashes
        assert result1.normalized[:38] == result2.normalized[:38]
        assert result1.normalized[38:] != result2.normalized[38:]
    
    def test_display_message_when_normalized(self) -> None:
        """Display message should explain the normalization."""
        name = "x" * 50
        result = normalize_customer_name(name)
        
        assert "50 chars" in result.display_message
        assert "exceeds 42 character limit" in result.display_message
        assert result.normalized in result.display_message


class TestNormalizeCustomerNameSimple:
    """Tests for normalize_customer_name_simple convenience function."""
    
    def test_short_name(self) -> None:
        assert normalize_customer_name_simple("acme") == "acme"
    
    def test_long_name(self) -> None:
        name = "a" * 50
        result = normalize_customer_name_simple(name)
        assert len(result) == 42
        assert result[:38] == "a" * 38


class TestNormalizedCustomerNameDataclass:
    """Tests for NormalizedCustomerName dataclass."""
    
    def test_frozen(self) -> None:
        """Dataclass should be immutable."""
        result = NormalizedCustomerName(
            original="test",
            normalized="test",
            was_normalized=False,
        )
        with pytest.raises(AttributeError):
            result.original = "changed"  # type: ignore[misc]
    
    def test_equality(self) -> None:
        """Equal values should be equal."""
        r1 = NormalizedCustomerName("a", "a", False)
        r2 = NormalizedCustomerName("a", "a", False)
        assert r1 == r2


class TestRealWorldCases:
    """Test realistic customer name scenarios."""
    
    def test_typical_short_customer(self) -> None:
        """Common short customer names work unchanged."""
        for name in ["acme", "bigcorp", "testcustomer", "mycompany"]:
            result = normalize_customer_name(name)
            assert result.normalized == name
            assert not result.was_normalized
    
    def test_boundary_42_chars(self) -> None:
        """Boundary case at exactly 42 chars."""
        name = "a" * 42
        result = normalize_customer_name(name)
        assert result.normalized == name
        assert not result.was_normalized
    
    def test_realistic_long_name(self) -> None:
        """A realistic long customer name that might occur."""
        # 55 character name
        name = "megacorporationinternationalglobalholdingsllc"
        if len(name) < 43:
            name = name + "x" * (43 - len(name))
        
        result = normalize_customer_name(name)
        assert result.was_normalized
        assert len(result.normalized) == 42
