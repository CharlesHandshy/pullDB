#!/usr/bin/env python3
"""Development server with mocked data.

Run this to start the web UI without needing a real MySQL database.
Uses the unified pulldb.simulation infrastructure and the real API endpoints
with dependency_overrides for simulation state.
"""

from __future__ import annotations

# CRITICAL: Set simulation mode and auth mode BEFORE any pulldb imports
# This ensures is_simulation_mode() returns True everywhere
# and auth mode supports session tokens (web UI authentication)
import os
os.environ["PULLDB_MODE"] = "SIMULATION"
os.environ["PULLDB_AUTH_MODE"] = "both"  # Support both trusted headers and session tokens

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pulldb.domain.models import JobStatus


# =============================================================================
# Simulation-based Dev API State (New unified approach)
# =============================================================================


class DevAPIState:
    """Dev API state using unified simulation infrastructure.
    
    This replaces MockAPIState by using the pulldb.simulation module,
    ensuring dev server uses the same mock implementations as tests
    and PULLDB_MODE=SIMULATION deployments.
    """
    
    # Available scenarios (same as MockAPIState for compatibility)
    SCENARIOS = {
        "minimal": {
            "name": "Minimal",
            "description": "Infrastructure only (users, hosts, settings) - no jobs",
        },
        "dev_mocks": {
            "name": "Dev Server Mocks",
            "description": "Large dataset for stress testing (800 jobs)",
        },
        "empty": {
            "name": "Empty State",
            "description": "Alias for minimal - no jobs",
        },
        "busy": {
            "name": "Busy System",
            "description": "Many concurrent running jobs",
        },
        "all_failed": {
            "name": "All Failed",
            "description": "Multiple failed jobs for error testing",
        },
        "queue_backlog": {
            "name": "Queue Backlog",
            "description": "Many jobs waiting in queue",
        },
    }
    
    def __init__(self, scenario: str = "minimal") -> None:
        from pulldb.api.main import _initialize_simulation_state
        from pulldb.simulation import (
            get_simulation_state,
            reset_simulation,
            seed_dev_scenario,
        )
        
        self.current_scenario = scenario
        
        # Reset and seed simulation state
        reset_simulation()
        state = get_simulation_state()
        seed_dev_scenario(state, scenario)
        
        # Seed auth credentials for dev users (password: PullDB_Dev2025!)
        self._seed_auth_credentials(state)
        
        # Get APIState from simulation infrastructure
        api_state = _initialize_simulation_state()
        
        # Expose repos for compatibility with existing dev endpoints
        self.config = api_state.config
        self.job_repo = api_state.job_repo
        self.user_repo = api_state.user_repo
        self.host_repo = api_state.host_repo
        self.settings_repo = api_state.settings_repo
        self.auth_repo = api_state.auth_repo
        self.audit_repo = api_state.audit_repo
    
    def _seed_auth_credentials(self, state) -> None:
        """Seed auth credentials for dev users.
        
        Password: PullDB_Dev2025! (bcrypt hash)
        """
        # Pre-computed bcrypt hash for "PullDB_Dev2025!"
        test_hash = "$2b$12$XnisilncYSnbIvEinwVYTePMF/DMiVUwpUSv8BuOWSlPH5sRam.zG"
        
        with state.lock:
            for user_id in ["usr-001", "usr-002", "usr-003"]:
                state.auth_credentials[user_id] = {
                    "password_hash": test_hash,
                    "totp_secret": None,
                    "failed_attempts": 0,
                    "locked_until": None,
                }
    
    def switch_scenario(self, scenario: str) -> dict:
        """Switch to a different scenario."""
        from pulldb.simulation import (
            get_simulation_state,
            reset_simulation,
            seed_dev_scenario,
        )
        from pulldb.api.main import _initialize_simulation_state
        
        if scenario not in self.SCENARIOS:
            return {"error": f"Unknown scenario: {scenario}"}
        
        self.current_scenario = scenario
        
        # Reset and reseed
        reset_simulation()
        state = get_simulation_state()
        seed_dev_scenario(state, scenario)
        self._seed_auth_credentials(state)
        
        # Refresh repos
        api_state = _initialize_simulation_state()
        self.job_repo = api_state.job_repo
        self.user_repo = api_state.user_repo
        self.host_repo = api_state.host_repo
        self.settings_repo = api_state.settings_repo
        self.auth_repo = api_state.auth_repo
        self.audit_repo = api_state.audit_repo
        
        return {
            "status": "success",
            "scenario": scenario,
            "scenario_name": self.SCENARIOS[scenario]["name"],
        }


# =============================================================================
# Application Setup
# =============================================================================


def create_dev_app():
    """Create dev app by extending the real API app with dev-specific routes.
    
    This imports the real FastAPI app from pulldb.api.main and adds:
    - dependency_overrides for simulation state
    - Dev-specific mock endpoints (customer search, backup search)
    - Simulation control endpoints (scenarios, reset)
    - Static file mounts for dev resources
    
    All real API endpoints (jobs, admin, manager, etc.) are inherited from main.py.
    """
    from fastapi import Request
    from fastapi.responses import RedirectResponse
    from fastapi.staticfiles import StaticFiles
    
    # Import the REAL API app - this has all the endpoints we need
    from pulldb.api.main import app, get_api_state
    
    # Initialize dev state using unified simulation infrastructure
    # Use "busy" scenario by default for testing (has active jobs and history)
    dev_state = DevAPIState(scenario="busy")
    
    # Store dev state for access by dev-specific endpoints
    app.state.dev_api_state = dev_state
    
    # Override get_api_state dependency to return our dev state
    # This makes all real API endpoints use our simulation data
    def _dev_get_api_state():
        """Return dev simulation state for all API endpoints."""
        from pulldb.api.main import _initialize_simulation_state
        return _initialize_simulation_state()
    
    app.dependency_overrides[get_api_state] = _dev_get_api_state

    # Mount widgets directory for JS/CSS FIRST (single source of truth)
    # Must be before /static mount so /static/widgets/ resolves to widgets dir
    widgets_dir = Path(__file__).parent.parent / "pulldb" / "web" / "static" / "widgets"
    if widgets_dir.exists():
        # Check if already mounted (avoid duplicate mounts on reload)
        if "widgets" not in [r.name for r in app.routes if hasattr(r, 'name')]:
            app.mount("/static/widgets", StaticFiles(directory=str(widgets_dir)), name="widgets")
    
    # Mount images from pulldb/images
    images_dir = Path(__file__).parent.parent / "pulldb" / "images"
    if images_dir.exists():
        if "static-images" not in [r.name for r in app.routes if hasattr(r, 'name')]:
            app.mount("/static/images", StaticFiles(directory=str(images_dir)), name="static-images")

    # Mount static files (CSS, JS, etc.) - unified location
    static_dir = Path(__file__).parent.parent / "pulldb" / "web" / "static"
    if static_dir.exists():
        if "static" not in [r.name for r in app.routes if hasattr(r, 'name')]:
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # === DEV-SPECIFIC MOCK ENDPOINTS ===
    # These are dev-only endpoints that don't exist in the real API
    
    @app.get("/web/restore/search-customers")
    async def mock_search_customers(q: str = "", limit: int = 100):
        """Mock customer search for dev server.
        
        Returns mock customers matching the query.
        Supports prefix-based caching: fetch once per 3-char prefix.
        """
        if len(q) < 3:
            return {"results": [], "total": 0, "prefix": q}
        
        # Mock customers - match the simulation list
        mock_customers = [
            "actionpest",
            "actionplumbing", 
            "acmehvac",
            "bigcorp",
            "cleanpro",
            "deltaplumbing",
            "eliteelectric",
            "fastfix",
            "greenscapes",
            "homeservices",
            "techcorp",
            "globalretail",
            "healthnet",
            "autoparts",
            "buildpro",
            "foodmart",
            "energyco",
            "finserve",
            "edulearn",
            "medisys",
        ]
        
        q_lower = q.lower()
        matches = [c for c in mock_customers if q_lower in c.lower()]
        matches = sorted(matches)[:limit]
        
        return {
            "results": [{"value": c, "label": c} for c in matches],
            "total": len(matches),
            "prefix": q[:3] if len(q) >= 3 else q,
        }
    
    @app.get("/web/restore/search-backups")
    async def mock_search_backups(request: Request, customer: str = "", env: str = "both"):
        """Mock backup search for dev server."""
        from datetime import datetime, timedelta
        from fastapi.responses import HTMLResponse as HTMLResp
        import random
        
        if not customer:
            return HTMLResp(
                '<div class="alert alert-warning">Please select a customer first.</div>'
            )
        
        # Generate mock backups for the customer
        backups = []
        now = datetime.now()
        
        for i in range(random.randint(3, 8)):
            days_ago = random.randint(1, 90)
            timestamp = now - timedelta(days=days_ago, hours=random.randint(0, 23))
            backup_env = random.choice(["staging", "prod"]) if env == "both" else env
            
            # Skip if env filter doesn't match
            if env != "both" and backup_env != env:
                continue
                
            backups.append({
                "customer": customer,
                "timestamp": timestamp,
                "date": timestamp.strftime("%Y%m%d"),
                "size_mb": round(random.uniform(50, 2000), 1),
                "environment": backup_env,
                "key": f"s3://backups/{backup_env}/{customer}/{timestamp.strftime('%Y%m%d_%H%M%S')}.sql.gz",
                "bucket": f"pulldb-backups-{backup_env}",
            })
        
        # Sort by timestamp (most recent first)
        backups.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Generate HTML directly
        if not backups:
            return HTMLResp('''
                <div class="alert alert-warning" style="margin-top: 1rem; padding: 1rem; background: var(--warning-50); border: 1px solid var(--warning-200); border-radius: var(--radius-md); color: var(--warning-700);">
                    <strong>No backups found.</strong>
                    <p style="margin: 0.5rem 0 0 0;">No backups are available for this customer in the selected environment.</p>
                </div>
            ''')
        
        rows_html = ""
        for i, backup in enumerate(backups):
            badge_class = "badge-primary" if backup["environment"] == "prod" else "badge-neutral"
            timestamp_str = backup["timestamp"].strftime('%Y-%m-%d %H:%M')
            size_str = f"{backup['size_mb']:.1f} MB"
            
            rows_html += f'''
            <tr data-backup-key="{backup["key"]}" 
                onclick="selectBackup('{backup["key"]}', '{backup["environment"]}', '{timestamp_str}', '{size_str}')">
                <td>{timestamp_str}</td>
                <td>
                    <span class="badge {badge_class}">
                        {backup["environment"]}
                    </span>
                </td>
                <td>{size_str}</td>
            </tr>
            '''
        
        html = f'''
        <table class="backup-table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Environment</th>
                    <th>Size</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        '''
        
        return HTMLResp(html)

    # Dropdown search API endpoints for searchable dropdowns
    @app.get("/api/dropdown/customers")
    async def dropdown_search_customers(q: str = "", limit: int = 20):
        """Search customers for dropdown."""
        if len(q) < 5:
            return {"results": [], "total": 0}
        
        # Mock customers
        mock_customers = [
            {"id": "acmehvac", "name": "ACME HVAC Services"},
            {"id": "techcorp", "name": "TechCorp Industries"},
            {"id": "fastlogistics", "name": "Fast Logistics LLC"},
            {"id": "globalretail", "name": "Global Retail Inc"},
            {"id": "healthnet", "name": "HealthNet Medical"},
            {"id": "autoparts", "name": "AutoParts Express"},
            {"id": "buildpro", "name": "BuildPro Construction"},
            {"id": "foodmart", "name": "FoodMart Groceries"},
            {"id": "energyco", "name": "EnergyCo Power"},
            {"id": "finserve", "name": "FinServe Banking"},
            {"id": "edulearn", "name": "EduLearn Academy"},
            {"id": "medisys", "name": "MediSys Healthcare"},
        ]
        
        q_lower = q.lower()
        matches = [c for c in mock_customers if q_lower in c["id"].lower() or q_lower in c["name"].lower()]
        return {
            "results": [{"value": c["id"], "label": c["id"], "sublabel": c["name"]} for c in matches[:limit]],
            "total": len(matches)
        }

    @app.get("/api/dropdown/users")
    async def dropdown_search_users(q: str = "", limit: int = 15):
        """Search users for dropdown."""
        if len(q) < 2:
            return {"results": [], "total": 0}
        
        # Mock users
        mock_users = [
            {"username": "devuser", "user_code": "devusr", "role": "user"},
            {"username": "devadmin", "user_code": "devadm", "role": "admin"},
            {"username": "testuser", "user_code": "tstusr", "role": "user"},
            {"username": "qamanager", "user_code": "qamgr", "role": "manager"},
        ]
        
        q_lower = q.lower()
        matches = [u for u in mock_users if q_lower in u["username"].lower() or q_lower in u["user_code"].lower()]
        return {
            "results": [{"value": u["username"], "label": u["username"], "sublabel": f"{u['user_code']} ({u['role']})"} for u in matches[:limit]],
            "total": len(matches)
        }

    @app.get("/api/dropdown/hosts")
    async def dropdown_search_hosts(q: str = "", limit: int = 10):
        """Search hosts for dropdown."""
        if len(q) < 2:
            return {"results": [], "total": 0}
        
        # Mock hosts
        mock_hosts = [
            {"hostname": "mysql-staging-01.example.com", "status": "enabled"},
            {"hostname": "mysql-staging-02.example.com", "status": "enabled"},
            {"hostname": "mysql-staging-03.example.com", "status": "disabled"},
            {"hostname": "mysql-prod-01.example.com", "status": "enabled"},
        ]
        
        q_lower = q.lower()
        matches = [h for h in mock_hosts if q_lower in h["hostname"].lower()]
        return {
            "results": [{"value": h["hostname"], "label": h["hostname"], "sublabel": h["status"]} for h in matches[:limit]],
            "total": len(matches)
        }

    # Redirect root to login
    @app.get("/", include_in_schema=False)
    async def root():  # noqa: RUF029
        return RedirectResponse(url="/web/login")

    # =============================================================================
    # Simulation Mode Endpoints
    # =============================================================================
    # These provide mock data for the dev toolbar's simulation debug panel.
    
    @app.get("/simulation/status")
    async def simulation_status(request: Request):
        """Get current simulation state for debug panel."""
        state: DevAPIState = request.app.state.dev_api_state
        scenario_info = DevAPIState.SCENARIOS.get(state.current_scenario, {})
        return {
            "current_scenario": scenario_info.get("name", state.current_scenario),
            "job_count": len(state.job_repo.active_jobs) + len(state.job_repo.history_jobs),
            "user_count": len(state.user_repo.users),
            "host_count": len(state.host_repo.hosts),
            "s3_bucket_count": 1,
            "event_count": len(state.job_repo.events),
        }
    
    @app.get("/simulation/scenarios")
    async def simulation_scenarios(request: Request):
        """Get available simulation scenarios."""
        state: DevAPIState = request.app.state.dev_api_state
        return {
            "current": state.current_scenario,
            "scenarios": [
                {"type": key, "name": val["name"], "description": val["description"]}
                for key, val in DevAPIState.SCENARIOS.items()
            ]
        }
    
    @app.post("/simulation/scenarios/activate")
    async def simulation_scenarios_activate(request: Request):
        """Activate a simulation scenario - actually switches the mock data!"""
        body = await request.json()
        scenario_type = body.get("scenario_type", "dev_mocks")
        
        state: DevAPIState = request.app.state.dev_api_state
        result = state.switch_scenario(scenario_type)
        
        if "error" in result:
            return {"status": "error", "message": result["error"]}
        
        return {
            "status": "success", 
            "scenario_name": result["scenario_name"],
            "message": f"Switched to {result['scenario_name']} scenario. Refresh the page to see changes."
        }
    
    @app.get("/simulation/events")
    async def simulation_events(request: Request, limit: int = 20):
        """Get recent simulation events."""
        state: DevAPIState = request.app.state.dev_api_state
        events = []
        
        # Flatten all events from the job_repo
        all_events = []
        for job_id, job_events in state.job_repo.events.items():
            all_events.extend(job_events)
        
        # Sort by timestamp descending and take limit
        all_events.sort(key=lambda e: e.logged_at, reverse=True)
        
        for event in all_events[:limit]:
            events.append({
                "timestamp": event.logged_at.isoformat(),
                "event_type": event.event_type,
                "source": "dev_server",
                "job_id": event.job_id,
            })
        
        return {"events": events}
    
    @app.get("/simulation/activate")
    async def simulation_activate(redirect: str = "/web/dashboard"):
        """Activate simulation mode (no-op in dev server - already using mocks)."""
        return RedirectResponse(url=redirect, status_code=302)
    
    @app.get("/simulation/deactivate")
    async def simulation_deactivate(redirect: str = "/web/dashboard"):
        """Deactivate simulation mode (no-op in dev server)."""
        return RedirectResponse(url=redirect, status_code=302)
    
    @app.post("/simulation/reset")
    async def simulation_reset(request: Request):
        """Reset simulation state to default scenario."""
        state: DevAPIState = request.app.state.dev_api_state
        state.switch_scenario("dev_mocks")
        return {"status": "success", "message": "Simulation reset to default. Page will reload."}

    # =============================================================================
    # Background Queue Runner
    # =============================================================================
    # Process one queued job every 15 seconds to simulate worker behavior

    async def queue_runner_loop() -> None:
        """Background task that processes queued jobs periodically."""
        from pulldb.simulation import SimulatedJobRepository
        from pulldb.simulation.core.queue_runner import MockQueueRunner, MockRunnerConfig

        job_repo = SimulatedJobRepository()
        # 10% failure rate for realistic simulation
        config = MockRunnerConfig(failure_rate=0.1)
        runner = MockQueueRunner(job_repo, config)

        print("  [Queue Runner] Started - processing jobs every 15 seconds")

        while True:
            await asyncio.sleep(15)
            try:
                job = runner.process_next()
                if job:
                    status_emoji = {
                        "complete": "✓",
                        "failed": "✗",
                        "canceled": "⊘",
                    }.get(job.status.value, "?")
                    print(
                        f"  [Queue Runner] {status_emoji} Job {job.id[:8]} -> {job.status.value}"
                    )
            except Exception as e:
                print(f"  [Queue Runner] Error: {e}")

    async def start_queue_runner() -> None:
        """Start the background queue runner on app startup."""
        asyncio.create_task(queue_runner_loop())

    # Use app.router.on_startup.append() instead of @app.on_event("startup")
    # to avoid FastAPI deprecation warning about lifespan event handlers
    app.router.on_startup.append(start_queue_runner)

    return app


def _load_dev_extensions() -> str:
    """Load the dev extensions HTML from the dev_templates directory.
    
    This contains all dev-only UI components:
    - Dev toolbar (viewport testing, grid overlay, color palette)
    - Simulation debug panel (scenarios, event history, state)
    
    Returns the raw HTML/CSS/JS to be injected into templates.
    """
    dev_templates_dir = Path(__file__).parent / "dev_templates"
    dev_extensions_file = dev_templates_dir / "dev_extensions.html"
    
    if not dev_extensions_file.exists():
        print(f"WARNING: Dev extensions file not found: {dev_extensions_file}")
        return "<!-- Dev extensions not found -->"
    
    return dev_extensions_file.read_text()


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> None:
    """Run the development server."""
    from pulldb.web.dependencies import templates

    # Security: Refuse to enable dev mode in production environment
    if os.environ.get("PULLDB_ENV", "").lower() == "production":
        print("ERROR: Cannot run dev_server.py in production environment!")
        print("       PULLDB_ENV is set to 'production'")
        sys.exit(1)
    
    # Load dev extensions (toolbar, simulation panel, etc.)
    dev_extensions_html = _load_dev_extensions()
    
    # Inject dev extensions into all templates
    # This is the ONLY place dev-specific UI is added
    templates.env.globals["dev_extensions"] = dev_extensions_html
    
    # Keep these for any template logic that checks dev mode
    templates.env.globals["dev_mode"] = True
    templates.env.globals["simulation_mode"] = lambda: True
    templates.env.globals["simulation_scenario_name"] = lambda: "Dev Server Mocks"

    print("\n" + "=" * 60)
    print("  pullDB Development Server")
    print("=" * 60)
    print("\n  Login credentials (password: PullDB_Dev2025!):")
    print("    devuser    - USER role")
    print("    devmanager - MANAGER role")
    print("    devadmin   - ADMIN role")
    print("\n  Open: http://127.0.0.1:8000/web/login")
    print("  Dev toolbar: Press Ctrl+` to toggle")
    print("=" * 60 + "\n")

    # Create app using the real API app with dependency overrides
    app = create_dev_app()

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
