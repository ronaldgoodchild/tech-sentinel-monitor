"""Tenant endpoints must not be open: admin key for management, no API-key leaks."""
from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("jose")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import auth  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import tenants  # noqa: E402

NOW = datetime.now(timezone.utc)
ALICE = {"id": "t-alice", "name": "Alice", "slug": "alice", "api_key": "alice-key",
         "created_at": NOW, "updated_at": NOW}
BOB = {"id": "t-bob", "name": "Bob", "slug": "bob", "api_key": "bob-key",
       "created_at": NOW, "updated_at": NOW}
ADMIN = {"X-TS-Admin-Key": "s3cret-admin"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "ts_api_key", "s3cret-admin")
    db = {ALICE["id"]: dict(ALICE), BOB["id"]: dict(BOB)}

    async def _list():
        return list(db.values())

    async def _get(tid):
        return db.get(tid)

    async def _create(name, slug, api_key=None):
        return {**ALICE, "id": "t-new", "name": name, "slug": slug}

    async def _delete(tid):
        db.pop(tid, None)

    async def _by_key(key):
        return next((t for t in db.values() if t["api_key"] == key), None)

    monkeypatch.setattr(tenants, "list_tenants", _list)
    monkeypatch.setattr(tenants, "get_tenant", _get)
    monkeypatch.setattr(tenants, "create_tenant", _create)
    monkeypatch.setattr(tenants, "delete_tenant", _delete)
    monkeypatch.setattr(auth, "get_tenant_by_api_key", _by_key)
    app = FastAPI()
    app.include_router(tenants.router)
    return TestClient(app)


def test_list_requires_admin_key(client):
    assert client.get("/api/v1/tenants/").status_code == 401
    assert client.get("/api/v1/tenants/", headers={"X-TS-Admin-Key": "wrong"}).status_code == 401
    # a tenant's own API key is not an admin key
    assert client.get("/api/v1/tenants/", headers={"X-TS-API-Key": "alice-key"}).status_code == 401
    r = client.get("/api/v1/tenants/", headers=ADMIN)
    assert r.status_code == 200 and len(r.json()) == 2


def test_create_and_delete_require_admin_key(client):
    body = {"name": "New", "slug": "new"}
    assert client.post("/api/v1/tenants/", json=body).status_code == 401
    assert client.post("/api/v1/tenants/", json=body, headers=ADMIN).status_code == 201
    assert client.delete("/api/v1/tenants/t-bob").status_code == 401
    assert client.delete("/api/v1/tenants/t-bob", headers=ADMIN).status_code == 204


def test_endpoints_disabled_when_no_admin_key_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "ts_api_key", "")
    # even an empty header must not unlock it
    assert client.get("/api/v1/tenants/", headers={"X-TS-Admin-Key": ""}).status_code == 503
    assert client.get("/api/v1/tenants/", headers=ADMIN).status_code == 503


def test_public_lookup_never_returns_api_key(client):
    r = client.get("/api/v1/tenants/t-alice")
    assert r.status_code == 200
    assert "api_key" not in r.json() and r.json()["name"] == "Alice"


def test_me_returns_only_own_tenant(client):
    assert client.get("/api/v1/tenants/me").status_code == 401
    r = client.get("/api/v1/tenants/me", headers={"X-TS-API-Key": "bob-key"})
    assert r.status_code == 200 and r.json()["id"] == "t-bob"
