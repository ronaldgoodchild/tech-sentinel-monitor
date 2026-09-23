"""Tests for probe implementations."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHTTPProbe:
    """Test HTTP probe logic."""

    @pytest.mark.asyncio
    async def test_successful_http_probe(self):
        from worker.probes.http_probe import http_probe

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        with patch("worker.probes.http_probe.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.request = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            result = await http_probe("https://example.com", 10)
            assert result["status"] == "up"
            assert result["status_code"] == 200

    @pytest.mark.asyncio
    async def test_http_probe_wrong_status(self):
        from worker.probes.http_probe import http_probe

        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("worker.probes.http_probe.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.request = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            result = await http_probe("https://example.com", 10)
            assert result["status"] == "down"
            assert result["status_code"] == 503

    @pytest.mark.asyncio
    async def test_http_probe_body_match_fail(self):
        import json

        from worker.probes.http_probe import http_probe

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "not what we want"

        with patch("worker.probes.http_probe.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.request = AsyncMock(return_value=mock_response)
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            config = json.dumps({"body_contains": "healthy"})
            result = await http_probe("https://example.com", 10, config)
            assert result["status"] == "down"
            assert "body" in result["error"].lower() or "Body" in result["error"]

    @pytest.mark.asyncio
    async def test_http_probe_timeout(self):
        import httpx as httpx_mod
        from worker.probes.http_probe import http_probe

        with patch("worker.probes.http_probe.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.request = AsyncMock(side_effect=httpx_mod.TimeoutException("timeout"))
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = client_instance

            result = await http_probe("https://example.com", 1)
            assert result["status"] == "timeout"


class TestTCPProbe:
    """Test TCP probe logic."""

    @pytest.mark.asyncio
    async def test_successful_tcp_probe(self):
        from worker.probes.tcp_probe import tcp_probe

        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch("worker.probes.tcp_probe.asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.return_value = (AsyncMock(), mock_writer)
            result = await tcp_probe("localhost:5432", 10)
            assert result["status"] == "up"

    @pytest.mark.asyncio
    async def test_tcp_probe_connection_refused(self):
        from worker.probes.tcp_probe import tcp_probe

        with patch("worker.probes.tcp_probe.asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = ConnectionRefusedError("Connection refused")
            result = await tcp_probe("localhost:9999", 5)
            assert result["status"] == "down"

    @pytest.mark.asyncio
    async def test_tcp_probe_invalid_format(self):
        from worker.probes.tcp_probe import tcp_probe
        result = await tcp_probe("no-port-here", 5)
        assert result["status"] == "down"
        assert "host:port" in result["error"]

    @pytest.mark.asyncio
    async def test_tcp_probe_timeout(self):
        from worker.probes.tcp_probe import tcp_probe

        with patch("worker.probes.tcp_probe.asyncio.open_connection", new_callable=AsyncMock) as mock_conn:
            mock_conn.side_effect = asyncio.TimeoutError()
            with patch("worker.probes.tcp_probe.asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
                mock_wait.side_effect = asyncio.TimeoutError()
                result = await tcp_probe("localhost:5432", 1)
                assert result["status"] == "timeout"


class TestPingProbe:
    """Test ping probe logic."""

    @pytest.mark.asyncio
    async def test_ping_rtt_parse_linux(self):
        from worker.probes.ping_probe import _parse_rtt
        output = "rtt min/avg/max/mdev = 0.123/1.456/2.789/0.012 ms"
        assert _parse_rtt(output) == 1.456

    @pytest.mark.asyncio
    async def test_ping_rtt_parse_windows(self):
        from worker.probes.ping_probe import _parse_rtt
        output = "Minimum = 0ms, Maximum = 1ms, Average = 2ms"
        assert _parse_rtt(output) == 2.0
