"""Tech Sentinel Monitor — Control Plane API entry point."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import close_connections, get_pool
from app.routers import alerts, heartbeat, monitors, status_pages, tenants
from app.services.monitor_service import schedule_all_active_monitors

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ts.control_plane")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Tech Sentinel Control Plane...")
    
    # Warn if running without TLS enforcement in production
    if os.getenv("TS_REQUIRE_TLS", "true").lower() != "false":
        logger.warning(
            "⚠️  TLS enforcement is enabled. Credential-bearing requests over plaintext HTTP will be rejected. "
            "Set TS_REQUIRE_TLS=false to disable (NOT recommended for production)."
        )
    else:
        logger.warning(
            "🔓 TLS enforcement is DISABLED. API keys and tokens will be accepted over plaintext HTTP. "
            "This is INSECURE for production deployments!"
        )
    
    await get_pool()
    logger.info("Database pool ready")
    try:
        await schedule_all_active_monitors()
        logger.info("Active monitors re-queued")
    except Exception as e:
        logger.warning(f"Could not re-queue monitors on startup (Redis may not be ready): {e}")
    yield
    logger.info("Shutting down...")
    await close_connections()


app = FastAPI(
    title="Tech Sentinel Monitor — Control Plane",
    description="Multi-tenant uptime monitoring platform by REGTeches",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── TLS Enforcement Middleware ───────────────────────────────────────────────
# Reject credential-bearing requests over plaintext HTTP to prevent credential
# capture by on-path attackers. This middleware runs before authentication.

CREDENTIAL_HEADERS = {"x-ts-api-key", "authorization"}
CREDENTIAL_PATHS = {"/api/v1/auth/token"}
PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}


@app.middleware("http")
async def enforce_tls_for_credentials(request: Request, call_next):
    """Reject credential-bearing requests over plaintext HTTP."""
    # Allow opt-out for local development (default: enabled)
    if os.getenv("TS_REQUIRE_TLS", "true").lower() == "false":
        return await call_next(request)
    
    # Check if request is over HTTPS
    # In production behind a reverse proxy, check X-Forwarded-Proto header
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    is_secure = request.url.scheme == "https" or forwarded_proto == "https"
    
    # Allow public endpoints over HTTP
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    
    # Check if request contains credentials
    has_credentials = False
    
    # Check for credential headers
    for header in CREDENTIAL_HEADERS:
        if header in request.headers:
            has_credentials = True
            break
    
    # Check for credential-bearing paths (token exchange endpoint)
    if request.url.path in CREDENTIAL_PATHS:
        has_credentials = True
    
    # Reject credential-bearing requests over plaintext
    if has_credentials and not is_secure:
        logger.warning(
            f"Rejected plaintext credential request: {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "detail": (
                    "Credentials cannot be transmitted over plaintext HTTP. "
                    "Use HTTPS to protect API keys and tokens from interception. "
                    "For local development only, set TS_REQUIRE_TLS=false."
                )
            },
        )
    
    return await call_next(request)

# Register routers
app.include_router(tenants.router)
app.include_router(monitors.router)
app.include_router(alerts.router)
app.include_router(heartbeat.router)
app.include_router(status_pages.router)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "control-plane"}
