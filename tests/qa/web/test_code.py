"""Tests for the code.html D3.js code structure graph page.

Tests cover:
- Page structure and dependencies
- D3.js library loading
- Code graph data structure
- Node types and styling
- Search functionality
- State persistence
"""

from __future__ import annotations

import json

from tests.qa.web.conftest import WEB_DIR


# ---------------------------------------------------------------------------
# Code Page Structure Tests
# ---------------------------------------------------------------------------


class TestCodePageStructure:
    """Tests for code.html HTML structure."""

    def test_has_title(self) -> None:
        """Code page has correct title."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "<title>" in content
        assert "Graph" in content

    def test_has_graph_container(self) -> None:
        """Code page has graph container element."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert 'id="graph-container"' in content

    def test_has_controls_panel(self) -> None:
        """Code page has controls panel."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert 'id="controls-panel"' in content

    def test_has_details_panel(self) -> None:
        """Code page has details panel."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert 'id="details-panel"' in content

    def test_has_search_input(self) -> None:
        """Code page has search input field."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert 'id="search-input"' in content


# ---------------------------------------------------------------------------
# Code Page Dependencies Tests
# ---------------------------------------------------------------------------


class TestCodePageDependencies:
    """Tests for code.html external dependencies."""

    def test_loads_d3(self) -> None:
        """Code page loads D3.js library."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "d3js.org" in content or "d3.v" in content

    def test_loads_d3_v7(self) -> None:
        """Code page loads D3.js version 7."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "d3.v7" in content


# ---------------------------------------------------------------------------
# Code Page Controls Tests
# ---------------------------------------------------------------------------


class TestCodePageControls:
    """Tests for code.html control buttons."""

    def test_has_search_button(self) -> None:
        """Code page has Search button."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "searchNodes()" in content
        assert ">Search<" in content

    def test_has_minimize_all_button(self) -> None:
        """Code page has Minimize All button."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "collapseAllNodes()" in content
        assert "Minimize All" in content

    def test_has_save_exit_button(self) -> None:
        """Code page has Save & Exit button."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "saveAndExit()" in content
        assert "Save" in content


# ---------------------------------------------------------------------------
# Code Page JavaScript Tests
# ---------------------------------------------------------------------------


class TestCodePageJavaScript:
    """Tests for code.html JavaScript functionality."""

    def test_loads_data_json(self) -> None:
        """Code page loads data.json."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "d3.json('data.json')" in content

    def test_has_tree_layout(self) -> None:
        """Code page uses D3 tree layout."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "d3.tree()" in content

    def test_has_hierarchy_function(self) -> None:
        """Code page uses D3 hierarchy."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "d3.hierarchy" in content

    def test_has_zoom_function(self) -> None:
        """Code page has zoom functionality."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "d3.zoom()" in content

    def test_has_collapse_function(self) -> None:
        """Code page has collapse function."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "function collapse" in content

    def test_has_expand_function(self) -> None:
        """Code page has expand function."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "function expand" in content

    def test_has_search_function(self) -> None:
        """Code page has searchNodes function."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "function searchNodes()" in content

    def test_has_update_function(self) -> None:
        """Code page has update function for tree rendering."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "update = function" in content or "function update" in content

    def test_uses_local_storage(self) -> None:
        """Code page uses localStorage for state persistence."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "localStorage" in content
        assert "setItem" in content
        assert "getItem" in content


# ---------------------------------------------------------------------------
# Code Page Styling Tests
# ---------------------------------------------------------------------------


class TestCodePageStyling:
    """Tests for code.html CSS styling."""

    def test_has_node_styling(self) -> None:
        """Code page has node CSS styling."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert ".node" in content

    def test_has_link_styling(self) -> None:
        """Code page has link CSS styling."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert ".link" in content

    def test_has_type_badges(self) -> None:
        """Code page has type badge styling."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert ".type-badge" in content
        assert ".type-class" in content
        assert ".type-method" in content
        assert ".type-function" in content
        assert ".type-file" in content
        assert ".type-folder" in content

    def test_has_search_match_styling(self) -> None:
        """Code page has search match highlight styling."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert ".search-match" in content

    def test_full_viewport_container(self) -> None:
        """Graph container fills viewport."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert "100vw" in content
        assert "100vh" in content


# ---------------------------------------------------------------------------
# Code Page Details Panel Tests
# ---------------------------------------------------------------------------


class TestCodePageDetailsPanel:
    """Tests for code.html details panel structure."""

    def test_has_detail_name(self) -> None:
        """Details panel has name element."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert 'id="detail-name"' in content

    def test_has_detail_type(self) -> None:
        """Details panel has type element."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert 'id="detail-type"' in content

    def test_has_detail_path(self) -> None:
        """Details panel has path element."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert 'id="detail-path"' in content

    def test_has_detail_content(self) -> None:
        """Details panel has content element."""
        code_path = WEB_DIR / "code.html"
        content = code_path.read_text()
        assert 'id="detail-content"' in content


# ---------------------------------------------------------------------------
# Code Data JSON Tests
# ---------------------------------------------------------------------------


class TestCodeDataJSON:
    """Tests for data.json structure."""

    def test_data_is_valid_json(self) -> None:
        """data.json is valid JSON."""
        data_path = WEB_DIR / "data.json"
        content = data_path.read_text()
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_has_root_node(self) -> None:
        """data.json has root node."""
        data_path = WEB_DIR / "data.json"
        data = json.loads(data_path.read_text())
        assert "id" in data
        assert "name" in data

    def test_root_is_pulldb(self) -> None:
        """Root node represents pulldb."""
        data_path = WEB_DIR / "data.json"
        data = json.loads(data_path.read_text())
        assert data.get("name") == "pulldb"

    def test_has_children(self) -> None:
        """Root node has children."""
        data_path = WEB_DIR / "data.json"
        data = json.loads(data_path.read_text())
        assert "children" in data
        assert isinstance(data["children"], list)
        assert len(data["children"]) > 0

    def test_nodes_have_id(self) -> None:
        """All nodes have unique id field."""
        data_path = WEB_DIR / "data.json"
        data = json.loads(data_path.read_text())
        seen_ids: set[str] = set()

        def check_node(node: dict) -> None:
            assert "id" in node, f"Node missing 'id': {node.get('name')}"
            assert node["id"] not in seen_ids, f"Duplicate id: {node['id']}"
            seen_ids.add(node["id"])
            if node.get("children"):
                for child in node["children"]:
                    check_node(child)

        check_node(data)

    def test_nodes_have_name(self) -> None:
        """All nodes have name field."""
        data_path = WEB_DIR / "data.json"
        data = json.loads(data_path.read_text())

        def check_node(node: dict) -> None:
            assert "name" in node, f"Node missing 'name': {node}"
            if node.get("children"):
                for child in node["children"]:
                    check_node(child)

        check_node(data)

    def test_nodes_have_type(self) -> None:
        """All nodes have type field."""
        data_path = WEB_DIR / "data.json"
        data = json.loads(data_path.read_text())
        valid_types = {
            "root",
            "folder",
            "file",
            "class",
            "method",
            "function",
            "variable",
            "property",
            "category",
            "interface",
        }

        def check_node(node: dict) -> None:
            assert "type" in node, f"Node missing 'type': {node.get('name')}"
            assert node["type"] in valid_types, f"Invalid type: {node['type']}"
            if node.get("children"):
                for child in node["children"]:
                    check_node(child)

        check_node(data)

    def test_has_infra_folder(self) -> None:
        """data.json contains infra folder."""
        data_path = WEB_DIR / "data.json"
        data = json.loads(data_path.read_text())
        content = data_path.read_text()
        assert '"name": "infra"' in content or '"name":"infra"' in content

    def test_has_worker_folder(self) -> None:
        """data.json contains worker folder."""
        data_path = WEB_DIR / "data.json"
        content = data_path.read_text()
        assert '"name": "worker"' in content or '"name":"worker"' in content

    def test_has_domain_folder(self) -> None:
        """data.json contains domain folder."""
        data_path = WEB_DIR / "data.json"
        content = data_path.read_text()
        assert '"name": "domain"' in content or '"name":"domain"' in content
