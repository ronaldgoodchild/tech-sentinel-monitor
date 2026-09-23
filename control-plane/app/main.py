"""Tech Sentinel Monitor — Control Plane API entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import close_connections, get_pool
from app.routers import alerts, heartbeat, monitors, status_pages, tenants
from app.services.monitor_service import schedule_all_active_monitors

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ts.control_plane")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Tech Sentinel Control Plane...")
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

# Register routers
app.include_router(tenants.router)
app.include_router(monitors.router)
app.include_router(alerts.router)
app.include_router(heartbeat.router)
app.include_router(status_pages.router)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok", "service": "control-plane"}
