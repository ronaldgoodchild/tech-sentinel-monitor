"""Tests for TLS enforcement middleware and client-side validation."""

import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_tls_enabled():
    """FastAPI app with TLS enforcement enabled."""
    with patch.dict(os.environ, {"TS_REQUIRE_TLS": "true"}):
        from app.main import app

        yield app


@pytest.fixture
def app_with_tls_disabled():
    """FastAPI app with TLS enforcement disabled."""
    with patch.dict(os.environ, {"TS_REQUIRE_TLS": "false"}):
        from app.main import app

        yield app


class TestTLSEnforcementMiddleware:
    """Test the TLS enforcement middleware in the control plane."""

    def test_health_endpoint_allowed_over_http(self, app_with_tls_enabled):
        """Public health endpoint should work over HTTP even with TLS enforcement."""
        client = TestClient(app_with_tls_enabled)
        response = client.get("/health")
        assert response.status_code == 200

    def test_api_key_rejected_over_http(self, app_with_tls_enabled):
        """API key in header should be rejected over plaintext HTTP."""
        client = TestClient(app_with_tls_enabled)
        response = client.get(
            "/api/v1/monitors/", headers={"X-TS-API-Key": "test-key-123"}
        )
        assert response.status_code == 400
        assert "plaintext HTTP" in response.json()["detail"]
        assert "HTTPS" in response.json()["detail"]

    def test_bearer_token_rejected_over_http(self, app_with_tls_enabled):
        """Bearer token should be rejected over plaintext HTTP."""
        client = TestClient(app_with_tls_enabled)
        response = client.get(
            "/api/v1/monitors/", headers={"Authorization": "Bearer test-token-123"}
        )
        assert response.status_code == 400
        assert "plaintext HTTP" in response.json()["detail"]

    def test_token_endpoint_rejected_over_http(self, app_with_tls_enabled):
        """Token exchange endpoint should be rejected over plaintext HTTP."""
        client = TestClient(app_with_tls_enabled)
        response = client.post("/api/v1/auth/token", json={"api_key": "test-key-123"})
        assert response.status_code == 400
        assert "plaintext HTTP" in response.json()["detail"]

    def test_api_key_allowed_over_https(self, app_with_tls_enabled):
        """API key should be allowed over HTTPS (simulated via X-Forwarded-Proto)."""
        client = TestClient(app_with_tls_enabled)
        # Simulate HTTPS via reverse proxy header
        response = client.get(
            "/api/v1/monitors/",
            headers={"X-TS-API-Key": "test-key-123", "X-Forwarded-Proto": "https"},
        )
        # Will fail auth (401) but not TLS check (400)
        assert response.status_code == 401

    def test_credentials_allowed_when_tls_disabled(self, app_with_tls_disabled):
        """Credentials should be allowed over HTTP when TLS enforcement is disabled."""
        client = TestClient(app_with_tls_disabled)
        response = client.get(
            "/api/v1/monitors/", headers={"X-TS-API-Key": "test-key-123"}
        )
        # Will fail auth (401) but not TLS check (400)
        assert response.status_code == 401


class TestProvisionerClientValidation:
    """Test client-side TLS validation in the provisioner."""

    def test_client_rejects_http_with_api_key(self):
        """TSClient should reject HTTP URL when API key is provided."""
        with patch.dict(os.environ, {"TS_REQUIRE_TLS": "true"}):
            from ts_provisioner.client import TSClient

            with pytest.raises(ValueError) as exc_info:
                TSClient("http://localhost:8000", api_key="test-key")

            assert "plaintext HTTP" in str(exc_info.value)
            assert "HTTPS" in str(exc_info.value)

    def test_client_allows_http_without_api_key(self):
        """TSClient should allow HTTP URL when no API key is provided."""
        with patch.dict(os.environ, {"TS_REQUIRE_TLS": "true"}):
            from ts_provisioner.client import TSClient

            # Should not raise
            client = TSClient("http://localhost:8000")
            client.close()

    def test_client_allows_https_with_api_key(self):
        """TSClient should allow HTTPS URL with API key."""
        with patch.dict(os.environ, {"TS_REQUIRE_TLS": "true"}):
            from ts_provisioner.client import TSClient

            # Should not raise
            client = TSClient("https://api.example.com", api_key="test-key")
            client.close()

    def test_client_allows_http_when_tls_disabled(self):
        """TSClient should allow HTTP with API key when TLS enforcement is disabled."""
        with patch.dict(os.environ, {"TS_REQUIRE_TLS": "false"}):
            from ts_provisioner.client import TSClient

            # Should not raise
            client = TSClient("http://localhost:8000", api_key="test-key")
            client.close()

    def test_credential_methods_validate_transport(self):
        """Methods that accept tenant API keys should validate transport."""
        with patch.dict(os.environ, {"TS_REQUIRE_TLS": "true"}):
            from ts_provisioner.client import TSClient

            # Create client without initial API key (allowed)
            client = TSClient("http://localhost:8000")

            # But passing credentials to methods should fail
            with pytest.raises(ValueError) as exc_info:
                client.create_monitor("tenant-key", {"name": "test"})

            assert "plaintext HTTP" in str(exc_info.value)
            client.close()
