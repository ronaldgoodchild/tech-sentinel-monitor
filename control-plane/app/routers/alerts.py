"""Alert channel CRUD and auth token endpoint."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import create_access_token, get_current_tenant
from app.models import (
    create_alert_channel,
    get_tenant_by_api_key,
    list_alert_channels,
)
from app.schemas import (
    AlertChannelCreate,
    AlertChannelResponse,
    TokenRequest,
    TokenResponse,
)

router = APIRouter(prefix="/api/v1", tags=["alerts"])


# ── Alert Channels ───────────────────────────────────────────────────────────

@router.post(
    "/alert-channels/",
    response_model=AlertChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_channel_endpoint(
    body: AlertChannelCreate, tenant=Depends(get_current_tenant)
):
    channel = await create_alert_channel(
        tenant_id=tenant["id"],
        name=body.name,
        channel_type=body.channel_type,
        config=body.config,
        external_id=body.external_id,
    )
    return channel


@router.get("/alert-channels/", response_model=list[AlertChannelResponse])
async def list_channels_endpoint(tenant=Depends(get_current_tenant)):
    return await list_alert_channels(tenant["id"])


# ── Auth Token Exchange ──────────────────────────────────────────────────────

@router.post("/auth/token", response_model=TokenResponse)
async def get_token(body: TokenRequest):
    tenant = await get_tenant_by_api_key(body.api_key)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    token, expires_in = create_access_token(tenant["id"])
    return TokenResponse(access_token=token, expires_in=expires_in)
