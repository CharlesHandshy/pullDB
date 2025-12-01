"""Tests for the flow.html Cytoscape flow chart page.

Tests cover:
- Page structure and dependencies
- Cytoscape.js library loading
- Flow chart data structure
- Node types and styling
- Navigation and drill-down functionality
"""

from __future__ import annotations

import json

from tests.qa.web.conftest import WEB_DIR


# ---------------------------------------------------------------------------
# Flow Page Structure Tests
# ---------------------------------------------------------------------------


class TestFlowPageStructure:
    """Tests for flow.html HTML structure."""

    def test_has_title(self) -> None:
        """Flow page has correct title."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "<title>pullDB Flow Chart</title>" in content

    def test_has_cytoscape_container(self) -> None:
        """Flow page has Cytoscape container element."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert 'id="cy"' in content

    def test_has_controls_panel(self) -> None:
        """Flow page has controls panel."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert 'id="controls"' in content

    def test_has_breadcrumbs(self) -> None:
        """Flow page has breadcrumb navigation."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert 'id="breadcrumbs"' in content

    def test_has_tooltip(self) -> None:
        """Flow page has tooltip element."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert 'id="tooltip"' in content


# ---------------------------------------------------------------------------
# Flow Page Dependencies Tests
# ---------------------------------------------------------------------------


class TestFlowPageDependencies:
    """Tests for flow.html external dependencies."""

    def test_loads_cytoscape(self) -> None:
        """Flow page loads Cytoscape.js library."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "cytoscape" in content.lower()
        assert "cdnjs.cloudflare.com" in content or "cdn.jsdelivr.net" in content

    def test_loads_dagre(self) -> None:
        """Flow page loads dagre layout library."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "dagre" in content.lower()

    def test_loads_cytoscape_dagre(self) -> None:
        """Flow page loads cytoscape-dagre extension."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "cytoscape-dagre" in content


# ---------------------------------------------------------------------------
# Flow Page Legend Tests
# ---------------------------------------------------------------------------


class TestFlowPageLegend:
    """Tests for flow.html legend items."""

    def test_has_start_node_legend(self) -> None:
        """Flow page legend shows Start node type."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "shape-start" in content
        assert ">Start<" in content

    def test_has_process_node_legend(self) -> None:
        """Flow page legend shows Process node type."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "shape-process" in content
        assert ">Process<" in content

    def test_has_decision_node_legend(self) -> None:
        """Flow page legend shows Decision node type."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "shape-decision" in content
        assert ">Decision<" in content

    def test_has_database_node_legend(self) -> None:
        """Flow page legend shows Database node type."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "shape-database" in content
        assert ">Database<" in content

    def test_has_end_node_legend(self) -> None:
        """Flow page legend shows End/Fail node type."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "shape-end" in content
        assert "End" in content


# ---------------------------------------------------------------------------
# Flow Page JavaScript Tests
# ---------------------------------------------------------------------------


class TestFlowPageJavaScript:
    """Tests for flow.html JavaScript functionality."""

    def test_initializes_cytoscape(self) -> None:
        """Flow page initializes Cytoscape instance."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "cytoscape(" in content
        assert "container:" in content

    def test_fetches_flow_data(self) -> None:
        """Flow page fetches flow_data.json."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "fetch('flow_data.json')" in content

    def test_has_render_graph_function(self) -> None:
        """Flow page has renderGraph function."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "function renderGraph" in content

    def test_has_load_graph_function(self) -> None:
        """Flow page has loadGraph function."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "loadGraph" in content

    def test_has_breadcrumb_update_function(self) -> None:
        """Flow page has updateBreadcrumbs function."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "function updateBreadcrumbs" in content

    def test_has_node_click_handler(self) -> None:
        """Flow page has node click event handler."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "cy.on('tap', 'node'" in content

    def test_has_tooltip_handlers(self) -> None:
        """Flow page has tooltip mouseover/mouseout handlers."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "cy.on('mouseover', 'node'" in content
        assert "cy.on('mouseout', 'node'" in content


# ---------------------------------------------------------------------------
# Flow Page Styling Tests
# ---------------------------------------------------------------------------


class TestFlowPageStyling:
    """Tests for flow.html CSS styling."""

    def test_has_dark_theme(self) -> None:
        """Flow page uses dark theme."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "#1e1e1e" in content

    def test_has_node_styles(self) -> None:
        """Flow page has node type styling."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        # Process node (blue)
        assert "#3498db" in content
        # Decision node (yellow)
        assert "#f1c40f" in content
        # Database node (purple)
        assert "#9b59b6" in content
        # Start node (green)
        assert "#2ecc71" in content
        # End node (red)
        assert "#e74c3c" in content

    def test_has_edge_styles(self) -> None:
        """Flow page has edge styling."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "target-arrow-shape" in content
        assert "curve-style" in content

    def test_full_viewport_container(self) -> None:
        """Cytoscape container fills viewport."""
        flow_path = WEB_DIR / "flow.html"
        content = flow_path.read_text()
        assert "100vw" in content
        assert "100vh" in content


# ---------------------------------------------------------------------------
# Flow Data JSON Tests
# ---------------------------------------------------------------------------


class TestFlowDataJSON:
    """Tests for flow_data.json structure."""

    def test_data_is_valid_json(self) -> None:
        """flow_data.json is valid JSON."""
        data_path = WEB_DIR / "flow_data.json"
        content = data_path.read_text()
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_has_main_view(self) -> None:
        """flow_data.json has main view."""
        data_path = WEB_DIR / "flow_data.json"
        data = json.loads(data_path.read_text())
        assert "main" in data

    def test_main_has_nodes(self) -> None:
        """Main view has at least one node."""
        data_path = WEB_DIR / "flow_data.json"
        data = json.loads(data_path.read_text())
        main_elements = data["main"]
        nodes = [e for e in main_elements if "source" not in e.get("data", {})]
        assert len(nodes) > 0

    def test_main_has_edges(self) -> None:
        """Main view has at least one edge."""
        data_path = WEB_DIR / "flow_data.json"
        data = json.loads(data_path.read_text())
        main_elements = data["main"]
        edges = [e for e in main_elements if "source" in e.get("data", {})]
        assert len(edges) > 0

    def test_nodes_have_required_fields(self) -> None:
        """Nodes have required data fields."""
        data_path = WEB_DIR / "flow_data.json"
        data = json.loads(data_path.read_text())
        for key, elements in data.items():
            for element in elements:
                node_data = element.get("data", {})
                if "source" not in node_data:  # It's a node, not an edge
                    assert "id" in node_data, f"Node missing 'id' in {key}"
                    assert "label" in node_data, f"Node missing 'label' in {key}"

    def test_edges_have_required_fields(self) -> None:
        """Edges have required source/target fields."""
        data_path = WEB_DIR / "flow_data.json"
        data = json.loads(data_path.read_text())
        for key, elements in data.items():
            for element in elements:
                edge_data = element.get("data", {})
                if "source" in edge_data:  # It's an edge
                    assert "target" in edge_data, f"Edge missing 'target' in {key}"

    def test_has_cli_drilldown(self) -> None:
        """flow_data.json has CLI drill-down view."""
        data_path = WEB_DIR / "flow_data.json"
        data = json.loads(data_path.read_text())
        assert "cli" in data

    def test_has_worker_drilldown(self) -> None:
        """flow_data.json has worker drill-down view."""
        data_path = WEB_DIR / "flow_data.json"
        data = json.loads(data_path.read_text())
        assert "worker" in data

    def test_nodes_have_type(self) -> None:
        """Nodes have type field for styling."""
        data_path = WEB_DIR / "flow_data.json"
        data = json.loads(data_path.read_text())
        valid_types = {"start", "end", "process", "decision", "database"}
        for key, elements in data.items():
            for element in elements:
                node_data = element.get("data", {})
                if "source" not in node_data and "type" in node_data:
                    assert (
                        node_data["type"] in valid_types
                    ), f"Invalid node type '{node_data['type']}' in {key}"
