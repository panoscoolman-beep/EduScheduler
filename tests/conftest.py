"""Shared pytest fixtures for the EduScheduler test suite."""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# Predictable token for tests
os.environ.setdefault("EDSCHEDULER_API_TOKEN", "test-token-please-rotate")


@pytest.fixture()
def auth_headers():
    """Bearer header carrying the canonical test token."""
    return {"Authorization": f"Bearer {os.environ['EDSCHEDULER_API_TOKEN']}"}


# ---------------------------------------------------------------------------
# Minimal app for middleware tests — avoids the prod app's Postgres init
# ---------------------------------------------------------------------------

@pytest.fixture()
def minimal_app():
    """A FastAPI app that wires *only* the auth middleware in front of
    a couple of dummy endpoints. Lets us assert middleware behavior
    without dragging in the database dependency tree."""
    from backend.auth import BearerTokenMiddleware

    app = FastAPI()
    app.add_middleware(BearerTokenMiddleware)

    @app.get("/api/dummy")
    def _dummy():
        return {"ok": True}

    @app.get("/api/healthz")
    def _healthz():
        return {"status": "ok"}

    @app.get("/")
    def _root():
        return {"frontend": "stub"}

    @app.get("/js/api.js")
    def _static_asset():
        return {"asset": "stub"}

    return app


@pytest.fixture()
def client(minimal_app):
    with TestClient(minimal_app) as c:
        yield c
