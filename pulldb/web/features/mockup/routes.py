"""Mockup routes - Standalone mockup pages for design iteration.

HCA Layer: pages (Layer 4)
These routes serve standalone mockup pages that can be used for design
iteration without modifying production code.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from pulldb.web.dependencies import templates

router = APIRouter(prefix="/mockup", tags=["mockup"])


@router.get("/job-details", response_class=HTMLResponse)
async def job_details_mockup(request: Request):
    """Serve the job details mockup page.
    
    This is a fully standalone HTML page with:
    - Draggable elements (grab any element to reposition)
    - Editable text (click any text to edit in-place)
    - Sample myloader and processlist data at the bottom
    - Export functionality to save your modifications
    
    Access at: /mockup/job-details
    """
    return templates.TemplateResponse(
        "mockup/job-details-mockup.html",
        {"request": request}
    )
