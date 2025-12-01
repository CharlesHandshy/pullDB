"""Tests for the main index.html navigation page.

Tests cover:
- Page rendering and structure
- Menu item content and links
- Visual styling elements
- Navigation functionality
"""

from __future__ import annotations

from tests.qa.web.conftest import WEB_DIR


# ---------------------------------------------------------------------------
# Static File Tests
# ---------------------------------------------------------------------------


class TestIndexPageExists:
    """Tests that required files exist."""

    def test_index_html_exists(self) -> None:
        """index.html file exists in web directory."""
        index_path = WEB_DIR / "index.html"
        assert index_path.exists(), f"Missing {index_path}"

    def test_code_html_exists(self) -> None:
        """code.html file exists in web directory."""
        code_path = WEB_DIR / "code.html"
        assert code_path.exists(), f"Missing {code_path}"

    def test_flow_html_exists(self) -> None:
        """flow.html file exists in web directory."""
        flow_path = WEB_DIR / "flow.html"
        assert flow_path.exists(), f"Missing {flow_path}"

    def test_data_json_exists(self) -> None:
        """data.json file exists in web directory."""
        data_path = WEB_DIR / "data.json"
        assert data_path.exists(), f"Missing {data_path}"

    def test_flow_data_json_exists(self) -> None:
        """flow_data.json file exists in web directory."""
        flow_data_path = WEB_DIR / "flow_data.json"
        assert flow_data_path.exists(), f"Missing {flow_data_path}"


# ---------------------------------------------------------------------------
# Index Page Content Tests
# ---------------------------------------------------------------------------


class TestIndexPageContent:
    """Tests for index.html content structure."""

    def test_has_title(self) -> None:
        """Index page contains pullDB title."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert "<title>pullDB Visualization Tools</title>" in content

    def test_has_header(self) -> None:
        """Index page contains main header."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert "pullDB Visualizations" in content

    def test_has_code_structure_link(self) -> None:
        """Index page has link to code.html."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert 'href="code.html"' in content
        assert "Code Structure Graph" in content

    def test_has_flow_chart_link(self) -> None:
        """Index page has link to flow.html."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert 'href="flow.html"' in content
        assert "Logical Flow Graph" in content

    def test_has_code_description(self) -> None:
        """Code link has proper description."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert "Interactive 2D visualization of Python modules" in content

    def test_has_flow_description(self) -> None:
        """Flow link has proper description."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert "Interactive 2D Flow Chart with Drill-down" in content


# ---------------------------------------------------------------------------
# Index Page Styling Tests
# ---------------------------------------------------------------------------


class TestIndexPageStyling:
    """Tests for index.html CSS styling."""

    def test_has_dark_theme(self) -> None:
        """Index page uses dark theme colors."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        # Dark background color
        assert "#1e1e1e" in content

    def test_has_menu_styling(self) -> None:
        """Index page has menu item styling."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert ".menu-item" in content
        assert ".menu" in content

    def test_has_hover_effects(self) -> None:
        """Index page has hover effects."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert ".menu-item:hover" in content

    def test_has_container_styling(self) -> None:
        """Index page has container styling."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert ".container" in content
        assert "border-radius" in content


# ---------------------------------------------------------------------------
# Index Page Structure Tests
# ---------------------------------------------------------------------------


class TestIndexPageStructure:
    """Tests for index.html HTML structure."""

    def test_has_doctype(self) -> None:
        """Index page has HTML5 doctype."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert "<!DOCTYPE html>" in content

    def test_has_viewport_meta(self) -> None:
        """Index page has viewport meta tag for mobile."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert 'name="viewport"' in content

    def test_has_charset_meta(self) -> None:
        """Index page has UTF-8 charset meta tag."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert 'charset="UTF-8"' in content

    def test_uses_semantic_html(self) -> None:
        """Index page uses semantic HTML elements."""
        index_path = WEB_DIR / "index.html"
        content = index_path.read_text()
        assert "<h1>" in content
        assert "<body>" in content
        assert "<head>" in content
