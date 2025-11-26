import os
import pytest
from pathlib import Path
from pulldb.worker.restore import _detect_backup_version

def test_detect_backup_version_ini_metadata(tmp_path):
    """Test detection of 0.19+ backup via INI metadata."""
    metadata = tmp_path / "metadata"
    metadata.write_text("[config]\nkey=value", encoding="utf-8")
    
    assert _detect_backup_version(str(tmp_path)) == "0.19+ (INI metadata)"

def test_detect_backup_version_legacy_metadata(tmp_path):
    """Test detection of 0.9 backup via legacy metadata."""
    metadata = tmp_path / "metadata"
    metadata.write_text("Started dump at: 2023-01-01 12:00:00", encoding="utf-8")
    
    assert _detect_backup_version(str(tmp_path)) == "0.9 (Legacy metadata)"

def test_detect_backup_version_zst_extension(tmp_path):
    """Test detection of 0.19+ backup via .zst extension (fallback)."""
    (tmp_path / "db.table.sql.zst").touch()
    
    assert _detect_backup_version(str(tmp_path)) == "0.19+ (zst extension)"

def test_detect_backup_version_gz_extension_is_inconclusive(tmp_path):
    """Test that .gz extension alone is NOT used for detection.
    
    Both 0.9 and 0.19+ formats can use .gz compression, so file extension
    alone is unreliable. Without metadata or .zst files, we assume legacy
    to be conservative (metadata synthesis will handle it).
    """
    (tmp_path / "db.table.sql.gz").touch()
    
    # .gz alone should return "unknown (assuming legacy)" - not "0.9 (gz extension)"
    assert _detect_backup_version(str(tmp_path)) == "unknown (assuming legacy)"

def test_detect_backup_version_unknown(tmp_path):
    """Test detection of unknown backup version (empty directory)."""
    assert _detect_backup_version(str(tmp_path)) == "unknown (assuming legacy)"

def test_detect_backup_version_priority(tmp_path):
    """Test that metadata content takes priority over extensions."""
    # Create legacy metadata but with .zst files (contradictory, but metadata wins)
    metadata = tmp_path / "metadata"
    metadata.write_text("Started dump at: ...", encoding="utf-8")
    (tmp_path / "db.table.sql.zst").touch()
    
    assert _detect_backup_version(str(tmp_path)) == "0.9 (Legacy metadata)"
