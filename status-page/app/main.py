"""Status Page — serves dark-themed responsive status pages per customer."""

import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Tech Sentinel Monitor — Status Page", version="1.0.0")

CONTROL_PLANE_URL = os.getenv("TS_CONTROL_PLANE_URL", "http://control-plane:8000")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "status-page"}


@app.get("/status/{slug}", response_class=HTMLResponse)
async def status_page(request: Request, slug: str):
    """Render a status page by slug."""
    async with httpx.AsyncClient(timeout=10) as client:
        # Fetch status page config
        resp = await client.get(f"{CONTROL_PLANE_URL}/api/v1/status-pages/{slug}")
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail="Status page not found")
        page = resp.json()

        # Parse monitor IDs and theme
        monitor_ids = json.loads(page.get("monitor_ids", "[]")) if isinstance(page.get("monitor_ids"), str) else page.get("monitor_ids", [])
        theme = json.loads(page.get("theme", "{}")) if isinstance(page.get("theme"), str) else page.get("theme", {})

        # Fetch tenant info
        tenant_resp = await client.get(f"{CONTROL_PLANE_URL}/api/v1/tenants/{page['tenant_id']}")
        tenant_name = tenant_resp.json().get("name", "Unknown") if tenant_resp.status_code == 200 else "Unknown"

        # Fetch monitor statuses
        monitors = []
        for mid in monitor_ids:
            try:
                m_resp = await client.get(f"{CONTROL_PLANE_URL}/api/v1/monitors/{mid}")
                if m_resp.status_code == 200:
                    monitor = m_resp.json()
                    # Get latest result
                    r_resp = await client.get(
                        f"{CONTROL_PLANE_URL}/api/v1/monitors/{mid}/results",
                        params={"limit": 1},
                    )
                    latest = r_resp.json()[0] if r_resp.status_code == 200 and r_resp.json() else None
                    monitors.append({
                        "name": monitor["name"],
                        "type": monitor["monitor_type"],
                        "target": monitor["target"],
                        "status": latest["status"] if latest else "unknown",
                        "response_time_ms": latest.get("response_time_ms") if latest else None,
                        "last_checked": latest.get("checked_at") if latest else None,
                    })
            except Exception:
                pass

    # Calculate overall status
    statuses = [m["status"] for m in monitors]
    if all(s == "up" for s in statuses):
        overall = "operational"
    elif any(s in ("down", "timeout") for s in statuses):
        overall = "outage"
    elif any(s == "degraded" for s in statuses):
        overall = "degraded"
    else:
        overall = "unknown"

    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "page_name": page["name"],
            "tenant_name": tenant_name,
            "overall_status": overall,
            "monitors": monitors,
            "theme": theme,
        },
    )
