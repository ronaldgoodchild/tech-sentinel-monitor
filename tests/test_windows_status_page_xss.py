"""Stored-XSS regression tests for the Windows standalone status/manage pages."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

PAYLOAD = '<script>alert(1)</script>'
ATTR = '"><img src=x onerror=alert(2)>'


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from windows import local_database as db
    from windows.local_status_page import create_status_app

    # The DB layer keeps one thread-local connection; start from a clean slate.
    db._local.conn = None
    db.init_db(str(tmp_path_factory.mktemp("xss") / "t.db"))
    tenant = db.create_tenant(PAYLOAD, "evil")
    mon = db.create_monitor(tenant["id"], PAYLOAD, "http", "javascript:alert(3)", group_name=ATTR)
    with TestClient(create_status_app()) as c:
        yield c, mon
    db._local.conn = None


@pytest.mark.parametrize("path", ["/", "/manage", "/incidents", "/audit", "/files"])
def test_pages_escape_user_data(client, path):
    c, _ = client
    body = c.get(path).text
    assert PAYLOAD not in body
    assert ATTR not in body


def test_detail_and_edit_pages_escape(client):
    c, mon = client
    for path in (f"/monitor/{mon['id']}", f"/manage/edit/{mon['id']}"):
        body = c.get(path).text
        assert PAYLOAD not in body
        assert ATTR not in body


def test_javascript_scheme_never_becomes_link(client):
    from windows.local_status_page import _build_clickable_url

    assert _build_clickable_url("javascript:alert(1)", "http") == ""
    assert _build_clickable_url("https://example.com", "http") == "https://example.com"
