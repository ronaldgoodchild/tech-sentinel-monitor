"""Tests for monitor CRUD operations."""


import pytest
from pydantic import ValidationError


class TestMonitorSchemas:
    """Test monitor schema validation."""

    def test_valid_http_monitor(self):
        from app.schemas import MonitorCreate
        m = MonitorCreate(
            name="Test HTTP",
            monitor_type="http",
            target="https://example.com",
        )
        assert m.name == "Test HTTP"
        assert m.monitor_type == "http"
        assert m.interval_seconds == 60
        assert m.timeout_seconds == 10

    def test_valid_tcp_monitor(self):
        from app.schemas import MonitorCreate
        m = MonitorCreate(
            name="Test TCP",
            monitor_type="tcp",
            target="db.example.com:5432",
        )
        assert m.monitor_type == "tcp"

    def test_valid_ping_monitor(self):
        from app.schemas import MonitorCreate
        m = MonitorCreate(
            name="Test Ping",
            monitor_type="ping",
            target="192.168.1.1",
        )
        assert m.monitor_type == "ping"

    def test_valid_heartbeat_monitor(self):
        from app.schemas import MonitorCreate
        m = MonitorCreate(
            name="Test Heartbeat",
            monitor_type="heartbeat",
            target="service-xyz",
        )
        assert m.monitor_type == "heartbeat"

    def test_invalid_monitor_type(self):
        from app.schemas import MonitorCreate
        with pytest.raises(ValidationError):
            MonitorCreate(
                name="Bad Monitor",
                monitor_type="invalid",
                target="example.com",
            )

    def test_interval_bounds(self):
        from app.schemas import MonitorCreate
        # Too low
        with pytest.raises(ValidationError):
            MonitorCreate(name="X", monitor_type="http", target="x.com", interval_seconds=5)
        # Too high
        with pytest.raises(ValidationError):
            MonitorCreate(name="X", monitor_type="http", target="x.com", interval_seconds=9999)

    def test_monitor_with_config(self):
        from app.schemas import MonitorCreate
        m = MonitorCreate(
            name="API Check",
            monitor_type="http",
            target="https://api.example.com/health",
            config={"method": "GET", "expected_status": 200, "body_contains": "ok"},
        )
        assert m.config["body_contains"] == "ok"

    def test_status_update_valid(self):
        from app.schemas import MonitorStatusUpdate
        u = MonitorStatusUpdate(status="paused")
        assert u.status == "paused"

    def test_status_update_invalid(self):
        from app.schemas import MonitorStatusUpdate
        with pytest.raises(ValidationError):
            MonitorStatusUpdate(status="deleted")
