"""Admin logo management routes for pullDB web UI.

HCA Feature Module: admin/logo
Handles: logo configuration and upload
Size: ~150 lines (HCA compliant)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from pulldb.web.dependencies import require_admin, templates

if TYPE_CHECKING:
    from pulldb.auth.models import User

router = APIRouter(prefix="/web/admin", tags=["web-admin-logo"])

# Logo configuration file path
LOGO_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "images" / "logo_config.json"
LOGO_UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "images"


def _get_logo_config() -> dict:
    """Load logo configuration from JSON file."""
    default_label_style = {
        "x": 0,
        "y": 0,
        "font": "system-ui, -apple-system, sans-serif",
        "size": 20,
        "weight": "700",
        "style": "normal",
        "color": "#1f2937",
        "rotation": 0,
        "spacing": 0,
        "transform": "none",
    }

    default_config = {
        "path": "/static/images/pullDB_logo.mp4",
        "type": "video",
        "label": "",
        "logo_scale": 100,
        "crop_top": 13,
        "crop_bottom": 17,
        "crop_left": 0,
        "crop_right": 0,
        "label_style": default_label_style,
    }

    if LOGO_CONFIG_PATH.exists():
        try:
            with open(LOGO_CONFIG_PATH) as f:
                config = json.load(f)
                label_style = config.get("labelStyle", {})
                return {
                    "path": config.get("path", default_config["path"]),
                    "type": config.get("type", default_config["type"]),
                    "label": config.get("label", default_config["label"]),
                    "logo_scale": config.get("logoScale", default_config["logo_scale"]),
                    "crop_top": config.get("crop", {}).get("top", default_config["crop_top"]),
                    "crop_bottom": config.get("crop", {}).get("bottom", default_config["crop_bottom"]),
                    "crop_left": config.get("crop", {}).get("left", default_config["crop_left"]),
                    "crop_right": config.get("crop", {}).get("right", default_config["crop_right"]),
                    "label_style": {
                        "x": label_style.get("x", default_label_style["x"]),
                        "y": label_style.get("y", default_label_style["y"]),
                        "font": label_style.get("font", default_label_style["font"]),
                        "size": label_style.get("size", default_label_style["size"]),
                        "weight": label_style.get("weight", default_label_style["weight"]),
                        "style": label_style.get("style", default_label_style["style"]),
                        "color": label_style.get("color", default_label_style["color"]),
                        "rotation": label_style.get("rotation", default_label_style["rotation"]),
                        "spacing": label_style.get("spacing", default_label_style["spacing"]),
                        "transform": label_style.get("transform", default_label_style["transform"]),
                    },
                }
        except Exception:
            pass

    return default_config


@router.get("/logo", response_class=HTMLResponse)
async def admin_logo_page(
    request: Request,
    user: "User" = Depends(require_admin),
) -> Response:
    """Display logo management screen."""
    logo_config = _get_logo_config()

    return templates.TemplateResponse(
        request=request,
        name="admin/logo.html",
        context={"user": user, "logo_config": logo_config},
    )


@router.post("/logo")
async def save_logo_config(
    request: Request,
    user: "User" = Depends(require_admin),
) -> dict:
    """Save logo configuration to JSON file."""
    data = await request.json()

    LOGO_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(LOGO_CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)

    return {"status": "success", "message": "Logo configuration saved"}


@router.post("/logo/upload")
async def upload_logo(
    user: "User" = Depends(require_admin),
    file: UploadFile = File(...),
) -> JSONResponse:
    """Upload a new logo file."""
    allowed_types = [
        "video/mp4",
        "video/webm",
        "image/png",
        "image/jpeg",
        "image/svg+xml",
        "image/gif",
    ]
    if file.content_type not in allowed_types:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Invalid file type: {file.content_type}. "
                f"Allowed: {', '.join(allowed_types)}"
            },
        )

    LOGO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    filename = file.filename or "logo"
    safe_filename = "".join(c for c in filename if c.isalnum() or c in ".-_")
    if not safe_filename:
        safe_filename = "uploaded_logo"

    ext_map = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/svg+xml": ".svg",
        "image/gif": ".gif",
    }
    if not any(safe_filename.lower().endswith(e) for e in ext_map.values()):
        safe_filename += ext_map.get(file.content_type, "")

    file_path = LOGO_UPLOAD_DIR / safe_filename
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    file_type = "video" if file.content_type.startswith("video/") else "image"
    return JSONResponse(
        content={
            "status": "success",
            "path": f"/static/images/{safe_filename}",
            "filename": safe_filename,
            "type": file_type,
        }
    )
