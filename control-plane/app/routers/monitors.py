"""Monitor CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_tenant
from app.models import (
    create_monitor,
    delete_monitor,
    get_monitor,
    get_recent_results,
    list_monitors,
    update_monitor_status,
)
from app.schemas import (
    CheckResultResponse,
    MonitorCreate,
    MonitorResponse,
    MonitorStatusUpdate,
)
from app.services.monitor_service import schedule_monitor

router = APIRouter(prefix="/api/v1/monitors", tags=["monitors"])


@router.post("/", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
async def create_monitor_endpoint(body: MonitorCreate, tenant=Depends(get_current_tenant)):
    monitor = await create_monitor(
        tenant_id=tenant["id"],
        name=body.name,
        monitor_type=body.monitor_type,
        target=body.target,
        interval_seconds=body.interval_seconds,
        timeout_seconds=body.timeout_seconds,
        external_id=body.external_id,
        config=body.config,
    )
    await schedule_monitor(monitor)
    return monitor


@router.get("/", response_model=list[MonitorResponse])
async def list_monitors_endpoint(tenant=Depends(get_current_tenant)):
    return await list_monitors(tenant["id"])


@router.get("/{monitor_id}", response_model=MonitorResponse)
async def get_monitor_endpoint(monitor_id: str, tenant=Depends(get_current_tenant)):
    monitor = await get_monitor(monitor_id)
    if not monitor or monitor["tenant_id"] != tenant["id"]:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return monitor


@router.patch("/{monitor_id}/status", response_model=MonitorResponse)
async def update_monitor_status_endpoint(
    monitor_id: str, body: MonitorStatusUpdate, tenant=Depends(get_current_tenant)
):
    monitor = await get_monitor(monitor_id)
    if not monitor or monitor["tenant_id"] != tenant["id"]:
        raise HTTPException(status_code=404, detail="Monitor not found")
    await update_monitor_status(monitor_id, body.status)
    monitor["status"] = body.status
    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor_endpoint(monitor_id: str, tenant=Depends(get_current_tenant)):
    monitor = await get_monitor(monitor_id)
    if not monitor or monitor["tenant_id"] != tenant["id"]:
        raise HTTPException(status_code=404, detail="Monitor not found")
    await delete_monitor(monitor_id)


@router.get("/{monitor_id}/results", response_model=list[CheckResultResponse])
async def get_results_endpoint(
    monitor_id: str, limit: int = 10, tenant=Depends(get_current_tenant)
):
    monitor = await get_monitor(monitor_id)
    if not monitor or monitor["tenant_id"] != tenant["id"]:
        raise HTTPException(status_code=404, detail="Monitor not found")
    return await get_recent_results(monitor_id, limit=min(limit, 100))
