"""Shared test fixtures for Tech Sentinel Monitor tests."""

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

# Ensure project root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "control-plane"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "probe-worker"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "provisioner"))


@pytest.fixture
def mock_db_conn():
    """Mock asyncpg connection."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()
    return conn


@pytest.fixture
def mock_db(mock_db_conn):
    """Patch get_db to return a mock connection."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_get_db():
        yield mock_db_conn

    with patch("app.database.get_db", _mock_get_db):
        yield mock_db_conn


@pytest.fixture
def sample_tenant():
    """Sample tenant data."""
    from datetime import datetime, timezone
    return {
        "id": "tenant-001",
        "name": "ACME Corporation",
        "slug": "acme-corp",
        "api_key": "test-api-key-001",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


@pytest.fixture
def sample_monitor():
    """Sample monitor data."""
    from datetime import datetime, timezone
    return {
        "id": "monitor-001",
        "tenant_id": "tenant-001",
        "name": "ACME Website",
        "monitor_type": "http",
        "target": "https://acme.example.com",
        "interval_seconds": 60,
        "timeout_seconds": 10,
        "external_id": "acme-website",
        "config": "{}",
        "status": "active",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


@pytest.fixture
def sample_layout():
    """Sample provisioner layout."""
    return {
        "tenant": {"name": "Test Corp", "slug": "test-corp"},
        "monitors": [
            {
                "name": "Test Website",
                "monitor_type": "http",
                "target": "https://test.example.com",
                "external_id": "test-web",
            },
            {
                "name": "Test DB",
                "monitor_type": "tcp",
                "target": "db.test.com:5432",
                "external_id": "test-db",
            },
        ],
        "alert_channels": [
            {
                "name": "Test Webhook",
                "channel_type": "webhook",
                "config": {"url": "https://hooks.example.com/test"},
                "external_id": "test-webhook",
            },
        ],
        "status_pages": [
            {
                "name": "Test Status",
                "slug": "test-status",
                "external_id": "test-status-page",
                "monitor_refs": ["test-web", "test-db"],
            },
        ],
    }
