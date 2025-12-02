"""Search routes for pullDB web UI.

HCA Feature Module: search
Handles: backup search
Size: ~90 lines (HCA compliant)
"""

from __future__ import annotations

import random
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from pulldb.web.dependencies import AuthenticatedUser, templates

if TYPE_CHECKING:
    from pulldb.api.main import APIState

router = APIRouter(prefix="/web", tags=["web-search"])


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    user: AuthenticatedUser,
    customer: str | None = None,
    s3env: str = "both",
    date_from: str | None = None,
    limit: int = 10,
) -> Response:
    """Display backup search."""
    backups = []
    searched = bool(customer)

    if customer:
        mock_customers = [
            "acmehvac", "acmepest", "actionpest", "actionplumbing",
            "bigcorp", "cleanpro", "deltaplumbing", "eliteelectric",
            "fastfix", "greenscapes", "homeservices", "techcorp",
        ]

        pattern = customer.replace("*", ".*")
        matching = [c for c in mock_customers if re.match(f"^{pattern}$", c, re.IGNORECASE)]

        if not matching and "*" not in customer:
            matching = [c for c in mock_customers if customer.lower() in c.lower()]

        base_date = datetime.now(UTC)
        for cust in matching[:5]:
            for i in range(min(3, limit // len(matching) + 1)):
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
        backups = backups[:limit]

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
        },
    )
