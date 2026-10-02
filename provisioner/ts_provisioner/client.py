"""API client for the Tech Sentinel Control Plane."""

import os
import httpx


class TSClient:
    """Synchronous HTTP client for the Control Plane API."""

    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.headers = {}
        if api_key:
            self.headers["X-TS-API-Key"] = api_key
        
        # Enforce HTTPS when credentials are used (unless explicitly disabled)
        require_tls = os.getenv("TS_REQUIRE_TLS", "true").lower() != "false"
        if require_tls and api_key and not self.base_url.startswith("https://"):
            raise ValueError(
                f"Cannot send API key over plaintext HTTP: {self.base_url}\n"
                "Use an HTTPS URL to protect credentials from interception.\n"
                "For local development only, set TS_REQUIRE_TLS=false to disable this check."
            )
        
        self._client = httpx.Client(base_url=self.base_url, headers=self.headers, timeout=30)

    def close(self):
        self._client.close()
    
    def _validate_credential_transport(self, credential: str):
        """Validate that credentials are not sent over plaintext HTTP."""
        require_tls = os.getenv("TS_REQUIRE_TLS", "true").lower() != "false"
        if require_tls and credential and not self.base_url.startswith("https://"):
            raise ValueError(
                f"Cannot send credentials over plaintext HTTP: {self.base_url}\n"
                "Use an HTTPS URL to protect credentials from interception.\n"
                "For local development only, set TS_REQUIRE_TLS=false to disable this check."
            )

    # ── Tenants ──────────────────────────────────────────────────────────────

    def create_tenant(self, name: str, slug: str) -> dict:
        resp = self._client.post("/api/v1/tenants/", json={"name": name, "slug": slug})
        resp.raise_for_status()
        return resp.json()

    def get_tenant_by_slug(self, slug: str) -> dict | None:
        resp = self._client.get("/api/v1/tenants/")
        resp.raise_for_status()
        for t in resp.json():
            if t["slug"] == slug:
                return t
        return None

    def list_tenants(self) -> list[dict]:
        resp = self._client.get("/api/v1/tenants/")
        resp.raise_for_status()
        return resp.json()

    # ── Monitors ─────────────────────────────────────────────────────────────

    def create_monitor(self, tenant_api_key: str, monitor: dict) -> dict:
        self._validate_credential_transport(tenant_api_key)
        headers = {"X-TS-API-Key": tenant_api_key}
        resp = self._client.post("/api/v1/monitors/", json=monitor, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def list_monitors(self, tenant_api_key: str) -> list[dict]:
        self._validate_credential_transport(tenant_api_key)
        headers = {"X-TS-API-Key": tenant_api_key}
        resp = self._client.get("/api/v1/monitors/", headers=headers)
        resp.raise_for_status()
        return resp.json()

    def update_monitor_status(self, tenant_api_key: str, monitor_id: str, status: str) -> dict:
        self._validate_credential_transport(tenant_api_key)
        headers = {"X-TS-API-Key": tenant_api_key}
        resp = self._client.patch(
            f"/api/v1/monitors/{monitor_id}/status",
            json={"status": status},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Alert Channels ───────────────────────────────────────────────────────

    def create_alert_channel(self, tenant_api_key: str, channel: dict) -> dict:
        self._validate_credential_transport(tenant_api_key)
        headers = {"X-TS-API-Key": tenant_api_key}
        resp = self._client.post("/api/v1/alert-channels/", json=channel, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def list_alert_channels(self, tenant_api_key: str) -> list[dict]:
        self._validate_credential_transport(tenant_api_key)
        headers = {"X-TS-API-Key": tenant_api_key}
        resp = self._client.get("/api/v1/alert-channels/", headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ── Status Pages ─────────────────────────────────────────────────────────

    def create_status_page(self, tenant_api_key: str, page: dict) -> dict:
        self._validate_credential_transport(tenant_api_key)
        headers = {"X-TS-API-Key": tenant_api_key}
        resp = self._client.post("/api/v1/status-pages/", json=page, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def get_status_page(self, slug: str) -> dict | None:
        resp = self._client.get(f"/api/v1/status-pages/{slug}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    # ── Health ───────────────────────────────────────────────────────────────

    def health(self) -> dict:
        resp = self._client.get("/health")
        resp.raise_for_status()
        return resp.json()
