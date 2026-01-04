"""Tests for web routes in pullDB.

Tests cover:
- Router registry structure
- HCA-compliant feature routers
- Page and feature module organization
"""

from __future__ import annotations

from pathlib import Path


# Base paths for web module
WEB_DIR = Path(__file__).parent.parent.parent.parent / "pulldb" / "web"
ROUTER_REGISTRY = WEB_DIR / "router_registry.py"
FEATURES_DIR = WEB_DIR / "features"
PAGES_DIR = WEB_DIR / "pages"


# ---------------------------------------------------------------------------
# Router Registry Tests
# ---------------------------------------------------------------------------


class TestRouterRegistryExists:
    """Tests that router_registry module exists and has expected structure."""

    def test_router_registry_file_exists(self) -> None:
        """router_registry.py file exists."""
        assert ROUTER_REGISTRY.exists()

    def test_exports_main_router(self) -> None:
        """Router registry exports main_router."""
        content = ROUTER_REGISTRY.read_text()
        assert "main_router = APIRouter" in content

    def test_has_all_export(self) -> None:
        """Router registry has __all__ with main_router."""
        content = ROUTER_REGISTRY.read_text()
        assert '__all__ = ["main_router"]' in content

    def test_imports_apirouter(self) -> None:
        """Router registry imports APIRouter from fastapi."""
        content = ROUTER_REGISTRY.read_text()
        assert "from fastapi import APIRouter" in content


# ---------------------------------------------------------------------------
# Feature Router Import Tests
# ---------------------------------------------------------------------------


class TestFeatureRouterImports:
    """Tests that router_registry imports all feature routers."""

    def test_imports_admin_router(self) -> None:
        """Admin feature router is imported."""
        content = ROUTER_REGISTRY.read_text()
        assert "from pulldb.web.features.admin.routes import router as admin_router" in content

    def test_imports_audit_router(self) -> None:
        """Audit feature router is imported."""
        content = ROUTER_REGISTRY.read_text()
        assert "from pulldb.web.features.audit.routes import router as audit_router" in content

    def test_imports_auth_router(self) -> None:
        """Auth feature router is imported."""
        content = ROUTER_REGISTRY.read_text()
        assert "from pulldb.web.features.auth.routes import router as auth_router" in content

    def test_imports_dashboard_router(self) -> None:
        """Dashboard feature router is imported."""
        content = ROUTER_REGISTRY.read_text()
        assert "from pulldb.web.features.dashboard.routes import router as dashboard_router" in content

    def test_imports_jobs_router(self) -> None:
        """Jobs feature router is imported."""
        content = ROUTER_REGISTRY.read_text()
        assert "from pulldb.web.features.jobs.routes import router as jobs_router" in content

    def test_imports_manager_router(self) -> None:
        """Manager feature router is imported."""
        content = ROUTER_REGISTRY.read_text()
        assert "from pulldb.web.features.manager.routes import router as manager_router" in content

    def test_imports_restore_router(self) -> None:
        """Restore feature router is imported."""
        content = ROUTER_REGISTRY.read_text()
        assert "from pulldb.web.features.restore.routes import router as restore_router" in content


# ---------------------------------------------------------------------------
# Feature Router Inclusion Tests
# ---------------------------------------------------------------------------


class TestFeatureRouterInclusion:
    """Tests that main_router includes all feature routers."""

    def test_includes_auth_router(self) -> None:
        """Auth router is included in main_router."""
        content = ROUTER_REGISTRY.read_text()
        assert "main_router.include_router(auth_router)" in content

    def test_includes_dashboard_router(self) -> None:
        """Dashboard router is included in main_router."""
        content = ROUTER_REGISTRY.read_text()
        assert "main_router.include_router(dashboard_router)" in content

    def test_includes_jobs_router(self) -> None:
        """Jobs router is included in main_router."""
        content = ROUTER_REGISTRY.read_text()
        assert "main_router.include_router(jobs_router)" in content

    def test_includes_restore_router(self) -> None:
        """Restore router is included in main_router."""
        content = ROUTER_REGISTRY.read_text()
        assert "main_router.include_router(restore_router)" in content

    def test_includes_admin_router(self) -> None:
        """Admin router is included in main_router."""
        content = ROUTER_REGISTRY.read_text()
        assert "main_router.include_router(admin_router)" in content

    def test_includes_audit_router(self) -> None:
        """Audit router is included in main_router."""
        content = ROUTER_REGISTRY.read_text()
        assert "main_router.include_router(audit_router)" in content

    def test_includes_manager_router(self) -> None:
        """Manager router is included in main_router."""
        content = ROUTER_REGISTRY.read_text()
        assert "main_router.include_router(manager_router)" in content


# ---------------------------------------------------------------------------
# HCA Feature Directory Structure Tests
# ---------------------------------------------------------------------------


class TestFeaturesDirectoryStructure:
    """Tests that features directory has expected HCA structure."""

    def test_features_dir_exists(self) -> None:
        """Features directory exists."""
        assert FEATURES_DIR.exists()
        assert FEATURES_DIR.is_dir()

    def test_admin_feature_exists(self) -> None:
        """Admin feature directory exists."""
        assert (FEATURES_DIR / "admin").exists()
        assert (FEATURES_DIR / "admin").is_dir()

    def test_audit_feature_exists(self) -> None:
        """Audit feature directory exists."""
        assert (FEATURES_DIR / "audit").exists()
        assert (FEATURES_DIR / "audit").is_dir()

    def test_auth_feature_exists(self) -> None:
        """Auth feature directory exists."""
        assert (FEATURES_DIR / "auth").exists()
        assert (FEATURES_DIR / "auth").is_dir()

    def test_dashboard_feature_exists(self) -> None:
        """Dashboard feature directory exists."""
        assert (FEATURES_DIR / "dashboard").exists()
        assert (FEATURES_DIR / "dashboard").is_dir()

    def test_jobs_feature_exists(self) -> None:
        """Jobs feature directory exists."""
        assert (FEATURES_DIR / "jobs").exists()
        assert (FEATURES_DIR / "jobs").is_dir()

    def test_manager_feature_exists(self) -> None:
        """Manager feature directory exists."""
        assert (FEATURES_DIR / "manager").exists()
        assert (FEATURES_DIR / "manager").is_dir()

    def test_restore_feature_exists(self) -> None:
        """Restore feature directory exists."""
        assert (FEATURES_DIR / "restore").exists()
        assert (FEATURES_DIR / "restore").is_dir()


class TestFeatureRouteFiles:
    """Tests that each feature has a routes.py file."""

    def test_admin_has_routes(self) -> None:
        """Admin feature has routes.py."""
        assert (FEATURES_DIR / "admin" / "routes.py").exists()

    def test_audit_has_routes(self) -> None:
        """Audit feature has routes.py."""
        assert (FEATURES_DIR / "audit" / "routes.py").exists()

    def test_auth_has_routes(self) -> None:
        """Auth feature has routes.py."""
        assert (FEATURES_DIR / "auth" / "routes.py").exists()

    def test_dashboard_has_routes(self) -> None:
        """Dashboard feature has routes.py."""
        assert (FEATURES_DIR / "dashboard" / "routes.py").exists()

    def test_jobs_has_routes(self) -> None:
        """Jobs feature has routes.py."""
        assert (FEATURES_DIR / "jobs" / "routes.py").exists()

    def test_manager_has_routes(self) -> None:
        """Manager feature has routes.py."""
        assert (FEATURES_DIR / "manager" / "routes.py").exists()

    def test_restore_has_routes(self) -> None:
        """Restore feature has routes.py."""
        assert (FEATURES_DIR / "restore" / "routes.py").exists()


# ---------------------------------------------------------------------------
# Web Module Init Tests
# ---------------------------------------------------------------------------


class TestWebModuleInit:
    """Tests that web module __init__.py has expected exports."""

    def test_web_init_exists(self) -> None:
        """Web module __init__.py exists."""
        assert (WEB_DIR / "__init__.py").exists()

    def test_exports_router_from_registry(self) -> None:
        """Web module exports router from router_registry."""
        content = (WEB_DIR / "__init__.py").read_text()
        assert "from pulldb.web.router_registry import main_router as router" in content

    def test_exports_templates(self) -> None:
        """Web module exports templates."""
        content = (WEB_DIR / "__init__.py").read_text()
        assert "templates" in content

    def test_exports_templates_dir(self) -> None:
        """Web module exports TEMPLATES_DIR."""
        content = (WEB_DIR / "__init__.py").read_text()
        assert "TEMPLATES_DIR" in content


# ---------------------------------------------------------------------------
# Pages Directory Tests
# ---------------------------------------------------------------------------


class TestPagesDirectory:
    """Tests for HCA pages directory structure."""

    def test_pages_dir_exists(self) -> None:
        """Pages directory exists."""
        assert PAGES_DIR.exists()
        assert PAGES_DIR.is_dir()

    def test_pages_has_readme(self) -> None:
        """Pages directory has README."""
        assert (PAGES_DIR / "README.md").exists()
