"""Heartbeat endpoint — monitors call this to report they're alive."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.models import get_monitor, insert_check_result
from app.schemas import HeartbeatResponse

router = APIRouter(prefix="/api/v1/heartbeat", tags=["heartbeat"])


@router.post("/{monitor_id}", response_model=HeartbeatResponse)
async def receive_heartbeat(monitor_id: str):
    monitor = await get_monitor(monitor_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    if monitor["monitor_type"] != "heartbeat":
        raise HTTPException(status_code=400, detail="Monitor is not a heartbeat type")

    now = datetime.now(timezone.utc)
    await insert_check_result(
        monitor_id=monitor_id,
        status="up",
        response_time_ms=0,
    )
    return HeartbeatResponse(status="ok", monitor_id=monitor_id, recorded_at=now)
