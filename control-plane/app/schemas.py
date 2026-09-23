"""Pydantic schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field

# ── Tenants ──────────────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9\-]+$")


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    api_key: str
    created_at: datetime
    updated_at: datetime


# ── Monitors ─────────────────────────────────────────────────────────────────

class MonitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    monitor_type: str = Field(..., pattern=r"^(http|tcp|ping|heartbeat)$")
    target: str = Field(..., min_length=1)
    interval_seconds: int = Field(default=60, ge=10, le=3600)
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    external_id: str | None = None
    config: dict | None = None


class MonitorResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    monitor_type: str
    target: str
    interval_seconds: int
    timeout_seconds: int
    external_id: str | None
    config: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class MonitorStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(active|paused)$")


# ── Alert Channels ───────────────────────────────────────────────────────────

class AlertChannelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    channel_type: str = Field(..., pattern=r"^(webhook|slack|pagerduty|ts_automation)$")
    config: dict = Field(default_factory=dict)
    external_id: str | None = None


class AlertChannelResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    channel_type: str
    config: str
    external_id: str | None
    created_at: datetime
    updated_at: datetime


# ── Status Pages ─────────────────────────────────────────────────────────────

class StatusPageCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9\-]+$")
    theme: dict | None = None
    monitor_ids: list[str] | None = None
    external_id: str | None = None


class StatusPageResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    slug: str
    theme: str | None
    monitor_ids: str | None
    external_id: str | None
    created_at: datetime
    updated_at: datetime


# ── Auth ─────────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    api_key: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ── Check Results ────────────────────────────────────────────────────────────

class CheckResultResponse(BaseModel):
    id: str
    monitor_id: str
    checked_at: datetime
    status: str
    response_time_ms: float | None
    status_code: int | None
    error: str | None


# ── Heartbeat ────────────────────────────────────────────────────────────────

class HeartbeatResponse(BaseModel):
    status: str
    monitor_id: str
    recorded_at: datetime
