"""Tenant CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_tenant
from app.models import create_tenant, delete_tenant, get_tenant, list_tenants
from app.schemas import TenantCreate, TenantResponse

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_endpoint(body: TenantCreate):
    """Create a new tenant. Unauthenticated to allow initial bootstrap."""
    new_tenant = await create_tenant(name=body.name, slug=body.slug)
    return new_tenant


@router.get("/", response_model=list[TenantResponse])
async def list_tenants_endpoint(tenant=Depends(get_current_tenant)):
    """List all tenants. Requires authentication to prevent ID enumeration."""
    return await list_tenants()


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant_endpoint(tenant_id: str, tenant=Depends(get_current_tenant)):
    """Get tenant details. Requires authentication to prevent ID enumeration."""
    target_tenant = await get_tenant(tenant_id)
    if not target_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return target_tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_endpoint(tenant_id: str, tenant=Depends(get_current_tenant)):
    """Delete a tenant. Requires authentication and ownership verification."""
    target_tenant = await get_tenant(tenant_id)
    if not target_tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    # Verify that the authenticated tenant is deleting their own tenant
    if target_tenant["id"] != tenant["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete another tenant's account",
        )
    await delete_tenant(tenant_id)
