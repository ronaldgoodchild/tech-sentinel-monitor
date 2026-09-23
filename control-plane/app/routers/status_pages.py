"""Status page CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_tenant
from app.models import create_status_page, get_status_page_by_slug
from app.schemas import StatusPageCreate, StatusPageResponse

router = APIRouter(prefix="/api/v1/status-pages", tags=["status-pages"])


@router.post("/", response_model=StatusPageResponse, status_code=status.HTTP_201_CREATED)
async def create_status_page_endpoint(
    body: StatusPageCreate, tenant=Depends(get_current_tenant)
):
    page = await create_status_page(
        tenant_id=tenant["id"],
        name=body.name,
        slug=body.slug,
        theme=body.theme,
        monitor_ids=body.monitor_ids,
        external_id=body.external_id,
    )
    return page


@router.get("/{slug}", response_model=StatusPageResponse)
async def get_status_page_endpoint(slug: str):
    page = await get_status_page_by_slug(slug)
    if not page:
        raise HTTPException(status_code=404, detail="Status page not found")
    return page
