"""Tests for web module initialization and structure.

Tests cover:
- Module exports
- Router configuration
- Template directory structure (HCA-based)
"""

from __future__ import annotations

from pathlib import Path


WEB_DIR = Path(__file__).parent.parent.parent.parent / "pulldb" / "web"
TEMPLATES_DIR = WEB_DIR / "templates"


# ---------------------------------------------------------------------------
# Module Structure Tests
# ---------------------------------------------------------------------------


class TestWebModuleStructure:
    """Tests for web module file structure."""

    def test_web_dir_exists(self) -> None:
        """Web module directory exists."""
        assert WEB_DIR.is_dir()

    def test_init_exists(self) -> None:
        """__init__.py exists."""
        assert (WEB_DIR / "__init__.py").exists()

    def test_router_registry_exists(self) -> None:
        """router_registry.py exists (HCA entry point)."""
        assert (WEB_DIR / "router_registry.py").exists()

    def test_templates_dir_exists(self) -> None:
        """templates directory exists."""
        assert (WEB_DIR / "templates").is_dir()

    def test_static_dir_exists(self) -> None:
        """static directory exists."""
        assert (WEB_DIR / "static").is_dir()

    def test_pages_dir_exists(self) -> None:
        """pages directory exists (HCA structure)."""
        assert (WEB_DIR / "pages").is_dir()

    def test_features_dir_exists(self) -> None:
        """features directory exists (HCA structure)."""
        assert (WEB_DIR / "features").is_dir()

    def test_shared_dir_exists(self) -> None:
        """shared directory exists (HCA structure)."""
        assert (WEB_DIR / "shared").is_dir()


# ---------------------------------------------------------------------------
# Module Exports Tests
# ---------------------------------------------------------------------------


class TestWebModuleExports:
    """Tests for web module exports."""

    def test_exports_main_router(self) -> None:
        """Web module exports main_router."""
        content = (WEB_DIR / "__init__.py").read_text()
        assert "main_router" in content

    def test_router_registry_has_main_router(self) -> None:
        """router_registry defines main_router."""
        content = (WEB_DIR / "router_registry.py").read_text()
        assert "main_router" in content
        assert "APIRouter" in content


# ---------------------------------------------------------------------------
# Template Directory Structure Tests (HCA)
# ---------------------------------------------------------------------------


class TestTemplateDirectoryStructure:
    """Tests for HCA-based template directory organization."""

    def test_has_base_template(self) -> None:
        """Base template exists for layout inheritance."""
        assert (TEMPLATES_DIR / "base.html").exists()

    def test_has_base_auth_template(self) -> None:
        """Base auth template exists for login pages."""
        assert (TEMPLATES_DIR / "base_auth.html").exists()

    def test_has_features_directory(self) -> None:
        """Features directory exists for page templates."""
        assert (TEMPLATES_DIR / "features").is_dir()

    def test_has_partials_directory(self) -> None:
        """Partials directory exists for shared components."""
        assert (TEMPLATES_DIR / "partials").is_dir()

    def test_has_widgets_directory(self) -> None:
        """Widgets directory exists for reusable components."""
        assert (TEMPLATES_DIR / "widgets").is_dir()

    def test_features_has_auth(self) -> None:
        """features/auth directory exists."""
        assert (TEMPLATES_DIR / "features" / "auth").is_dir()

    def test_features_has_dashboard(self) -> None:
        """features/dashboard directory exists."""
        assert (TEMPLATES_DIR / "features" / "dashboard").is_dir()

    def test_features_has_jobs(self) -> None:
        """features/jobs directory exists."""
        assert (TEMPLATES_DIR / "features" / "jobs").is_dir()

    def test_features_has_restore(self) -> None:
        """features/restore directory exists."""
        assert (TEMPLATES_DIR / "features" / "restore").is_dir()

    def test_features_has_admin(self) -> None:
        """features/admin directory exists."""
        assert (TEMPLATES_DIR / "features" / "admin").is_dir()


# ---------------------------------------------------------------------------
# Template Content Quality Tests
# ---------------------------------------------------------------------------


class TestTemplateQuality:
    """Tests for template content quality."""

    def test_base_template_valid_html(self) -> None:
        """Base template has valid HTML structure."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "<!DOCTYPE html>" in content

    def test_base_template_has_blocks(self) -> None:
        """Base template defines required blocks."""
        content = (TEMPLATES_DIR / "base.html").read_text()
        assert "{% block title %}" in content
        assert "{% block content %}" in content

    def test_feature_templates_extend_base(self) -> None:
        """Feature templates extend base.html or base_auth.html."""
        features_dir = TEMPLATES_DIR / "features"
        for feature_dir in features_dir.iterdir():
            if feature_dir.is_dir():
                for template in feature_dir.glob("*.html"):
                    # Skip partials (files starting with _)
                    if template.name.startswith("_"):
                        continue
                    content = template.read_text()
                    has_extends = '{% extends "base.html" %}' in content or '{% extends "base_auth.html" %}' in content
                    assert has_extends, f"{template} should extend base template"

    def test_partials_are_fragments(self) -> None:
        """Partial templates are HTML fragments, not full documents."""
        partials_dir = TEMPLATES_DIR / "partials"
        for partial in partials_dir.glob("*.html"):
            content = partial.read_text()
            # Partials should NOT have doctype
            assert "<!DOCTYPE" not in content, f"{partial.name} has doctype"
