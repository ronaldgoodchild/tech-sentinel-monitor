"""Tests for the alert engine and webhook dispatcher."""

import json
from unittest.mock import AsyncMock, patch

import pytest


class TestAlertEngine:
    """Test alert evaluation logic."""

    @pytest.mark.asyncio
    async def test_no_alert_below_threshold(self):
        """Alert should NOT fire when failures < threshold."""
        with patch("app.services.alert_engine.get_monitor", new_callable=AsyncMock) as mock_get, \
             patch("app.services.alert_engine.get_consecutive_failures", new_callable=AsyncMock) as mock_fail, \
             patch("app.services.alert_engine.list_alert_channels", new_callable=AsyncMock) as mock_channels, \
             patch("app.services.alert_engine.dispatch_alert", new_callable=AsyncMock) as mock_dispatch:

            mock_get.return_value = {"id": "m1", "tenant_id": "t1", "name": "Test"}
            mock_fail.return_value = 1  # Below default threshold of 3
            mock_channels.return_value = []

            from app.services.alert_engine import evaluate_alert
            await evaluate_alert("m1", "down")
            mock_dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_alert_at_threshold(self):
        """Alert SHOULD fire when failures >= threshold."""
        with patch("app.services.alert_engine.get_monitor", new_callable=AsyncMock) as mock_get, \
             patch("app.services.alert_engine.get_consecutive_failures", new_callable=AsyncMock) as mock_fail, \
             patch("app.services.alert_engine.list_alert_channels", new_callable=AsyncMock) as mock_channels, \
             patch("app.services.alert_engine.dispatch_alert", new_callable=AsyncMock) as mock_dispatch:

            mock_get.return_value = {"id": "m1", "tenant_id": "t1", "name": "Test", "monitor_type": "http", "target": "x.com"}
            mock_fail.return_value = 3  # At threshold
            mock_channels.return_value = [
                {"id": "c1", "name": "Webhook", "channel_type": "webhook", "config": json.dumps({"url": "https://hook.test"})}
            ]

            from app.services.alert_engine import evaluate_alert
            await evaluate_alert("m1", "down")
            mock_dispatch.assert_called_once()

    @pytest.mark.asyncio
    async def test_recovery_notification(self):
        """Recovery should fire when status goes from down to up."""
        with patch("app.services.alert_engine.get_monitor", new_callable=AsyncMock) as mock_get, \
             patch("app.services.alert_engine.get_consecutive_failures", new_callable=AsyncMock) as mock_fail, \
             patch("app.models.get_recent_results", new_callable=AsyncMock) as mock_results, \
             patch("app.services.alert_engine.list_alert_channels", new_callable=AsyncMock) as mock_channels, \
             patch("app.services.alert_engine.dispatch_alert", new_callable=AsyncMock) as mock_dispatch:

            mock_get.return_value = {"id": "m1", "tenant_id": "t1", "name": "Test", "monitor_type": "http", "target": "x.com"}
            mock_fail.return_value = 0  # Now healthy
            mock_results.return_value = [
                {"status": "up"},
                {"status": "down"},  # Was down before
            ]
            mock_channels.return_value = [
                {"id": "c1", "name": "Slack", "channel_type": "slack", "config": "{}"}
            ]

            from app.services.alert_engine import evaluate_alert
            await evaluate_alert("m1", "up")
            mock_dispatch.assert_called_once()
            call_kwargs = mock_dispatch.call_args
            assert call_kwargs[1]["event"] == "recovery" or call_kwargs.kwargs.get("event") == "recovery"

    @pytest.mark.asyncio
    async def test_no_alert_for_unknown_monitor(self):
        """No alert if monitor not found."""
        with patch("app.services.alert_engine.get_monitor", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            from app.services.alert_engine import evaluate_alert
            await evaluate_alert("nonexistent", "down")


class TestWebhookPayload:
    """Test webhook payload construction."""

    def test_alert_payload(self):
        from app.services.webhook_dispatcher import _build_payload
        monitor = {"id": "m1", "name": "Test Monitor", "monitor_type": "http", "target": "https://x.com"}
        payload = _build_payload(monitor, 5, "alert")
        assert payload["event"] == "alert"
        assert payload["monitor_name"] == "Test Monitor"
        assert payload["consecutive_failures"] == 5
        assert "DOWN" in payload["status"]

    def test_recovery_payload(self):
        from app.services.webhook_dispatcher import _build_payload
        monitor = {"id": "m1", "name": "Test Monitor", "monitor_type": "http", "target": "https://x.com"}
        payload = _build_payload(monitor, 0, "recovery")
        assert payload["event"] == "recovery"
        assert "RECOVERED" in payload["status"]

    def test_payload_has_timestamp(self):
        from app.services.webhook_dispatcher import _build_payload
        monitor = {"id": "m1", "name": "X", "monitor_type": "http", "target": "x"}
        payload = _build_payload(monitor, 1, "alert")
        assert "timestamp" in payload
