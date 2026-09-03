"""GET /api/solver/solutions?term_id=X — λίστα λύσεων ΑΛΛΟΥ σεναρίου χωρίς
να αλλάξει το ενεργό (το CRM/bot διαλέγει έτσι «ποιο πρόγραμμα βλέπει»).
Κάθε λύση φέρει πλέον `term_id`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import Term, TimetableSolution
from backend.routers import solver as solver_router


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    t1 = Term(name="2025-26", short_name="25", is_active=True)
    t2 = Term(name="2026-27", short_name="26", is_active=False)
    s.add_all([t1, t2])
    s.commit()
    s.refresh(t1)
    s.refresh(t2)
    s.add_all([
        TimetableSolution(name="old", status="feasible", term_id=t1.id),
        TimetableSolution(name="new-term", status="optimal", term_id=t2.id),
    ])
    s.commit()

    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.t1, client.t2 = t1, t2
    yield client
    s.close()


def test_default_lists_active_term_only_with_term_id(env):
    res = env.get("/api/solver/solutions")
    assert res.status_code == 200
    body = res.json()
    assert [x["name"] for x in body] == ["old"]
    assert body[0]["term_id"] == env.t1.id


def test_term_id_filter_lists_other_term(env):
    res = env.get(f"/api/solver/solutions?term_id={env.t2.id}")
    assert res.status_code == 200
    body = res.json()
    assert [x["name"] for x in body] == ["new-term"]
    assert body[0]["term_id"] == env.t2.id
    # ξένο/ανύπαρκτο σενάριο → άδεια λίστα, όχι σφάλμα
    assert env.get("/api/solver/solutions?term_id=999").json() == []


def test_get_solution_exposes_term_id(env):
    sid = env.get(f"/api/solver/solutions?term_id={env.t2.id}").json()[0]["id"]
    res = env.get(f"/api/solver/solutions/{sid}")
    assert res.status_code == 200
    assert res.json()["term_id"] == env.t2.id
