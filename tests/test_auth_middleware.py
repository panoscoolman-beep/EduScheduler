"""Tests for backend.auth.BearerTokenMiddleware.

These tests run against a minimal app (see conftest.minimal_app) so we
exercise the middleware contract without needing a working database.

The contract:
  - Frontend assets (paths NOT starting with /api/) flow through.
  - Public API endpoints (/api/healthz, /api/_meta) flow through.
  - Same-origin browser requests (Sec-Fetch-Site=same-origin) flow through.
  - Everything else needs Authorization: Bearer <correct token>.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Public paths — never blocked
# ---------------------------------------------------------------------------

def test_root_path_unauthenticated(client):
    """Frontend assets (the SPA) must always load — no auth needed."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["frontend"] == "stub"


def test_static_asset_unauthenticated(client):
    response = client.get("/js/api.js")
    assert response.status_code == 200


def test_api_healthz_unauthenticated(client):
    """/api/healthz is the public health probe — must work without token."""
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Cross-service / curl style — require Bearer
# ---------------------------------------------------------------------------

def test_api_call_without_bearer_returns_401(client):
    response = client.get("/api/dummy")
    assert response.status_code == 401
    assert "Bearer" in response.json()["detail"]


def test_api_call_with_invalid_bearer_returns_401(client):
    response = client.get(
        "/api/dummy",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid bearer token"


def test_api_call_with_valid_bearer_passes_auth(client, auth_headers):
    """A valid token unlocks the API."""
    response = client.get("/api/dummy", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_malformed_authorization_header_returns_401(client):
    """Headers that don't start with 'Bearer ' (e.g. Basic auth) must reject."""
    response = client.get(
        "/api/dummy",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert response.status_code == 401


def test_bearer_with_extra_whitespace_is_handled(client):
    """`Bearer  <token>` (extra spaces) should still authenticate if token matches."""
    import os
    response = client.get(
        "/api/dummy",
        headers={"Authorization": f"Bearer  {os.environ['EDSCHEDULER_API_TOKEN']}"},
    )
    # Either accepted (whitespace tolerated by .strip()) or rejected —
    # the implementation strips, so should pass
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Same-origin browser — bypass via Sec-Fetch-Site
# ---------------------------------------------------------------------------

def test_same_origin_browser_request_bypasses_auth(client):
    """The bundled SPA hits /api/* with Sec-Fetch-Site=same-origin set
    by the browser. No bearer should be required."""
    response = client.get(
        "/api/dummy",
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 200


def test_same_site_browser_request_bypasses_auth(client):
    response = client.get(
        "/api/dummy",
        headers={"Sec-Fetch-Site": "same-site"},
    )
    assert response.status_code == 200


def test_cross_site_browser_request_still_requires_auth(client):
    """A genuine cross-origin browser request gets blocked."""
    response = client.get(
        "/api/dummy",
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert response.status_code == 401


def test_no_sec_fetch_site_means_server_to_server(client):
    """No Sec-Fetch-Site header at all (e.g. curl, requests lib) is
    treated as a non-browser caller and must use Bearer."""
    response = client.get("/api/dummy")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Dev mode — no token configured
# ---------------------------------------------------------------------------

def test_dev_mode_no_token_fails_open(client, monkeypatch):
    """When EDSCHEDULER_API_TOKEN is unset, the middleware fails open
    (with a log warning). Preserves dev workflow."""
    monkeypatch.setenv("EDSCHEDULER_API_TOKEN", "")
    response = client.get("/api/dummy")
    assert response.status_code == 200


def test_dev_mode_empty_token_fails_open(client, monkeypatch):
    """Whitespace-only token also counts as 'unset'."""
    monkeypatch.setenv("EDSCHEDULER_API_TOKEN", "   ")
    response = client.get("/api/dummy")
    assert response.status_code == 200
