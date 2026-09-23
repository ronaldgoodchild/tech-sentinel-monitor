"""Tenant CRUD endpoints."""

from fastapi import APIRouter, HTTPException, status

from app.models import create_tenant, delete_tenant, get_tenant, list_tenants
from app.schemas import TenantCreate, TenantResponse

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_endpoint(body: TenantCreate):
    tenant = await create_tenant(name=body.name, slug=body.slug)
    return tenant


@router.get("/", response_model=list[TenantResponse])
async def list_tenants_endpoint():
    return await list_tenants()


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant_endpoint(tenant_id: str):
    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_endpoint(tenant_id: str):
    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await delete_tenant(tenant_id)
