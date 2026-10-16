"""Tenant CRUD endpoints.

Creating, listing and deleting tenants needs the admin key (X-TS-Admin-Key);
those responses include each tenant's API key. A tenant can read its own record
with its API key/JWT at /me. Public lookups by id never include the API key.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_tenant, require_admin
from app.models import create_tenant, delete_tenant, get_tenant, list_tenants
from app.schemas import TenantCreate, TenantPublic, TenantResponse

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post(
    "/",
    response_model=TenantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_tenant_endpoint(body: TenantCreate):
    tenant = await create_tenant(name=body.name, slug=body.slug)
    return tenant


@router.get("/", response_model=list[TenantResponse], dependencies=[Depends(require_admin)])
async def list_tenants_endpoint():
    return await list_tenants()


@router.get("/me", response_model=TenantResponse)
async def get_own_tenant_endpoint(tenant=Depends(get_current_tenant)):
    return tenant


@router.get("/{tenant_id}", response_model=TenantPublic)
async def get_tenant_endpoint(tenant_id: str):
    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def delete_tenant_endpoint(tenant_id: str):
    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await delete_tenant(tenant_id)
