"""Tenant CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_tenant
from app.models import create_tenant, delete_tenant, get_tenant, list_tenants
from app.schemas import TenantCreate, TenantPublicResponse, TenantResponse

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_endpoint(body: TenantCreate):
    """Create a new tenant. Returns the API key once - save it securely."""
    tenant = await create_tenant(name=body.name, slug=body.slug)
    return tenant


@router.get("/", response_model=list[TenantPublicResponse])
async def list_tenants_endpoint(tenant=Depends(get_current_tenant)):
    """List all tenants. Requires authentication. Does not expose API keys."""
    return await list_tenants()


@router.get("/{tenant_id}", response_model=TenantPublicResponse)
async def get_tenant_endpoint(tenant_id: str):
    """Get a specific tenant by ID. Public endpoint but does not expose API key."""
    fetched_tenant = await get_tenant(tenant_id)
    if not fetched_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return fetched_tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_endpoint(tenant_id: str, tenant=Depends(get_current_tenant)):
    """Delete a tenant. Requires authentication."""
    fetched_tenant = await get_tenant(tenant_id)
    if not fetched_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await delete_tenant(tenant_id)
