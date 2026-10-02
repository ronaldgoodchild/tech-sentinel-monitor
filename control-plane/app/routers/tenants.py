"""Tenant CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_tenant
from app.models import create_tenant, delete_tenant, get_tenant, list_tenants
from app.schemas import TenantCreate, TenantResponse

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_endpoint(body: TenantCreate):
    tenant = await create_tenant(name=body.name, slug=body.slug)
    return tenant


@router.get("/", response_model=list[TenantResponse])
async def list_tenants_endpoint(tenant=Depends(get_current_tenant)):
    """List all tenants. Requires authentication."""
    tenants = await list_tenants()
    # Remove api_key from response for security
    return [{k: v for k, v in t.items() if k != "api_key"} for t in tenants]


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant_endpoint(tenant_id: str):
    """Get a specific tenant's public information (name, slug). API key is excluded."""
    tenant_data = await get_tenant(tenant_id)
    if not tenant_data:
        raise HTTPException(status_code=404, detail="Tenant not found")
    # Remove api_key from response for security
    return {k: v for k, v in tenant_data.items() if k != "api_key"}


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_endpoint(tenant_id: str, tenant=Depends(get_current_tenant)):
    """Delete a tenant. Requires authentication."""
    tenant_data = await get_tenant(tenant_id)
    if not tenant_data:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await delete_tenant(tenant_id)
