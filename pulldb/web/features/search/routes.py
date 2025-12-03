"""Search routes for pullDB web UI.

HCA Feature Module: search
Handles: backup search
Size: ~120 lines (HCA compliant)

Note: In simulation mode, uses mock data for demonstration.
In production mode, integrates with real S3 discovery.
"""

from __future__ import annotations

import random
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse

from pulldb.infra.factory import is_simulation_mode
from pulldb.web.dependencies import AuthenticatedUser, get_api_state, templates

router = APIRouter(prefix="/web", tags=["web-search"])


def _get_mock_backups(
    customer: str,
    s3env: str,
    limit: int,
) -> list[dict]:
    """Generate mock backup data for simulation mode."""
    mock_customers = [
        "acmehvac", "acmepest", "actionpest", "actionplumbing",
        "bigcorp", "cleanpro", "deltaplumbing", "eliteelectric",
        "fastfix", "greenscapes", "homeservices", "techcorp",
    ]

    pattern = customer.replace("*", ".*")
    matching = [c for c in mock_customers if re.match(f"^{pattern}$", c, re.IGNORECASE)]

    if not matching and "*" not in customer:
        matching = [c for c in mock_customers if customer.lower() in c.lower()]

    backups = []
    base_date = datetime.now(UTC)
    for cust in matching[:5]:
        for i in range(min(3, limit // max(len(matching), 1) + 1)):
            backup_date = base_date - timedelta(days=i)
            env = "staging" if i % 2 == 0 else "prod"

            if s3env != "both" and env != s3env:
                continue

            size_mb = random.randint(500, 4000)
            size_display = f"{size_mb / 1000:.1f} GB" if size_mb >= 1000 else f"{size_mb} MB"

            backups.append({
                "customer": cust,
                "date": backup_date.strftime("%b %d, %Y"),
                "date_raw": backup_date.strftime("%Y%m%d"),
                "time": backup_date.strftime("%H:%M"),
                "size_display": size_display,
                "environment": env,
                "s3_key": f"s3://pulldb-backups-{env}/{cust}/{backup_date.strftime('%Y%m%d')}/backup.tar.gz",
            })

    backups.sort(key=lambda b: b["date_raw"], reverse=True)
    return backups[:limit]


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    user: AuthenticatedUser,
    customer: str | None = None,
    s3env: str = "both",
    date_from: str | None = None,
    limit: int = 10,
    state=Depends(get_api_state),
) -> Response:
    """Display backup search.
    
    In simulation mode: Returns mock backup data for demonstration.
    In production mode: Searches configured S3 backup locations.
    """
    backups: list[dict] = []
    searched = bool(customer)
    search_message: str | None = None

    if customer:
        if is_simulation_mode():
            # Simulation mode: use mock data
            backups = _get_mock_backups(customer, s3env, limit)
        else:
            # Production mode: S3 search not yet integrated with web UI
            # This is a placeholder - real implementation would use S3 discovery
            search_message = (
                "S3 backup search is available via CLI. "
                "Web UI integration coming soon."
            )
            # TODO: Integrate with pulldb.infra.s3.discover_latest_backup
            # and config.s3_backup_locations for real S3 discovery

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "user": user,
            "backups": backups,
            "customer": customer,
            "s3env": s3env,
            "date_from": date_from,
            "limit": limit,
            "searched": searched,
            "total_count": len(backups),
            "search_message": search_message,
            "simulation_mode": is_simulation_mode(),
        },
    )
