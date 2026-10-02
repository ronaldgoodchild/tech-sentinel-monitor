"""Tenant CRUD endpoints."""

from asyncpg.exceptions import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_tenant
from app.models import create_tenant, delete_tenant, get_tenant, list_tenants
from app.schemas import TenantCreate, TenantPublicResponse, TenantResponse

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_endpoint(body: TenantCreate):
    """Create a new tenant. Returns API key only on initial creation."""
    try:
        tenant = await create_tenant(name=body.name, slug=body.slug)
        return tenant
    except UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant with slug '{body.slug}' already exists",
        )


@router.get("/", response_model=list[TenantPublicResponse])
async def list_tenants_endpoint(tenant=Depends(get_current_tenant)):
    """List all tenants. Requires authentication. Does not expose API keys."""
    return await list_tenants()


@router.get("/{tenant_id}", response_model=TenantPublicResponse)
async def get_tenant_endpoint(tenant_id: str, tenant=Depends(get_current_tenant)):
    """Get tenant by ID. Requires authentication. Does not expose API key."""
    result = await get_tenant(tenant_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return result


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_endpoint(tenant_id: str, tenant=Depends(get_current_tenant)):
    """Delete a tenant. Requires authentication."""
    result = await get_tenant(tenant_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await delete_tenant(tenant_id)
