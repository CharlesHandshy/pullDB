# Appendix A — Theme CSS Endpoint

> Implementation for `/web/theme.css` dynamic endpoint.

```python
# pulldb/web/routes/theme.py

from fastapi import APIRouter, Response
from pulldb.domain.settings import get_setting
import hashlib

router = APIRouter()

@router.get("/theme.css")
async def get_theme_css():
    """Generate CSS custom properties from admin settings."""
    
    primary_hue = get_setting("primary_color_hue", 217)
    accent_hue = get_setting("accent_color_hue", 142)
    
    css = f"""
:root {{
    --primary-hue: {primary_hue};
    --accent-hue: {accent_hue};
    
    /* Generated primary colors */
    --primary-50: hsl({primary_hue}, 100%, 97%);
    --primary-100: hsl({primary_hue}, 96%, 90%);
    --primary-200: hsl({primary_hue}, 94%, 80%);
    --primary-300: hsl({primary_hue}, 94%, 68%);
    --primary-400: hsl({primary_hue}, 92%, 58%);
    --primary-500: hsl({primary_hue}, 91%, 50%);
    --primary-600: hsl({primary_hue}, 91%, 45%);
    --primary-700: hsl({primary_hue}, 88%, 38%);
    --primary-800: hsl({primary_hue}, 84%, 32%);
    --primary-900: hsl({primary_hue}, 78%, 26%);
    
    /* Generated accent colors */
    --accent-50: hsl({accent_hue}, 76%, 97%);
    --accent-100: hsl({accent_hue}, 76%, 90%);
    --accent-500: hsl({accent_hue}, 71%, 45%);
    --accent-600: hsl({accent_hue}, 76%, 36%);
}}
"""
    
    # Generate ETag from settings values
    etag = hashlib.sha256(f"{primary_hue}:{accent_hue}".encode()).hexdigest()[:16]
    
    return Response(
        content=css,
        media_type="text/css",
        headers={
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
            "ETag": f'"{etag}"',
        }
    )
```

## Registration

Add to `pulldb/web/routes/__init__.py`:

```python
from pulldb.web.routes.theme import router as theme_router

app.include_router(theme_router, prefix="/web")
```

## Usage in base.html

```html
<head>
    <link rel="stylesheet" href="/web/theme.css">
</head>
```
