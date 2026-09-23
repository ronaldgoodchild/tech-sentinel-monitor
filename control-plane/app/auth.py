"""Dual authentication: X-TS-API-Key header OR JWT Bearer token."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings
from app.models import get_tenant_by_api_key

api_key_header = APIKeyHeader(name="X-TS-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(tenant_id: str) -> tuple[str, int]:
    expires_delta = timedelta(minutes=settings.ts_jwt_expire_minutes)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": tenant_id, "exp": expire}
    token = jwt.encode(payload, settings.ts_jwt_secret, algorithm=settings.ts_jwt_algorithm)
    return token, int(expires_delta.total_seconds())


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token, settings.ts_jwt_secret, algorithms=[settings.ts_jwt_algorithm]
        )
        return payload.get("sub")
    except JWTError:
        return None


async def get_current_tenant(
    api_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
):
    # Try API key first
    if api_key:
        tenant = await get_tenant_by_api_key(api_key)
        if tenant:
            return tenant

    # Try JWT bearer
    if bearer:
        tenant_id = decode_token(bearer.credentials)
        if tenant_id:
            from app.models import get_tenant
            tenant = await get_tenant(tenant_id)
            if tenant:
                return tenant

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key or token",
    )


async def get_optional_tenant(
    api_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
):
    """Returns tenant or None — used for public endpoints that optionally authenticate."""
    try:
        return await get_current_tenant(api_key, bearer)
    except HTTPException:
        return None
