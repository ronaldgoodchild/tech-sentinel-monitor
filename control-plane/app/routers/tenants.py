"""Tenant CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_tenant
from app.models import create_tenant, delete_tenant, get_tenant, list_tenants
from app.schemas import TenantCreate, TenantCreateResponse, TenantResponse

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post(
    "/", response_model=TenantCreateResponse, status_code=status.HTTP_201_CREATED
)
async def create_tenant_endpoint(body: TenantCreate):
    """Create a new tenant. Returns api_key only at creation time for bootstrapping."""
    tenant = await create_tenant(name=body.name, slug=body.slug)
    return tenant


@router.get("/", response_model=list[TenantResponse])
async def list_tenants_endpoint(tenant=Depends(get_current_tenant)):
    """List all tenants. Requires authentication. Only returns current tenant."""
    # Return only the authenticated tenant to prevent enumeration
    return [tenant]


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant_endpoint(tenant_id: str, tenant=Depends(get_current_tenant)):
    """Get tenant details. Requires authentication. Only returns current tenant."""
    # Only allow retrieving the authenticated tenant
    if tenant["id"] != tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_endpoint(tenant_id: str, tenant=Depends(get_current_tenant)):
    """Delete a tenant. Requires authentication. Only allows deleting current tenant."""
    # Only allow deleting the authenticated tenant
    if tenant["id"] != tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await delete_tenant(tenant_id)
