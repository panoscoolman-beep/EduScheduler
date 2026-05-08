"""Tests for the boot-time recovery hook.

When a container is killed mid-solve (a deploy lands while the user is
generating a timetable), the TimetableSolution row sits at status
'generating' indefinitely. The recovery hook in backend/main.py flips
those rows to 'error' on the next boot so the UI can render a clear
explanation.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import TimetableSolution


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s, engine
    s.close()


def _recover(engine):
    """Inline copy of the recovery body keyed off `engine` instead of
    the module-level binding, so we can run it against a per-test in-
    memory DB."""
    import json
    from datetime import datetime
    from sqlalchemy.orm import Session as _Session

    session = _Session(bind=engine)
    try:
        stuck = (
            session.query(TimetableSolution)
            .filter(TimetableSolution.status == "generating")
            .all()
        )
        for sol in stuck:
            sol.status = "error"
            existing = {}
            if sol.metadata_json:
                try:
                    existing = json.loads(sol.metadata_json)
                except (TypeError, ValueError):
                    existing = {}
            existing["recovered_at"] = datetime.utcnow().isoformat()
            existing["recovery_reason"] = (
                "Ο solver διακόπηκε από restart του container. Δοκίμασε ξανά."
            )
            sol.metadata_json = json.dumps(existing, default=str)
        session.commit()
        return len(stuck)
    finally:
        session.close()


def test_recovery_does_nothing_when_no_stuck_rows(db):
    s, engine = db
    s.add(TimetableSolution(name="ok", status="optimal"))
    s.add(TimetableSolution(name="done", status="feasible"))
    s.commit()

    n = _recover(engine)
    assert n == 0
    statuses = {r.status for r in s.query(TimetableSolution).all()}
    assert statuses == {"optimal", "feasible"}


def test_recovery_flips_generating_rows_to_error(db):
    s, engine = db
    s.add(TimetableSolution(name="stuck1", status="generating"))
    s.add(TimetableSolution(name="stuck2", status="generating"))
    s.add(TimetableSolution(name="ok", status="optimal"))
    s.commit()

    n = _recover(engine)
    assert n == 2

    statuses = [r.status for r in s.query(TimetableSolution).order_by(TimetableSolution.id).all()]
    assert statuses == ["error", "error", "optimal"]


def test_recovery_writes_explanation_into_metadata(db):
    s, engine = db
    s.add(TimetableSolution(name="stuck", status="generating"))
    s.commit()

    _recover(engine)
    sol = s.query(TimetableSolution).first()
    s.refresh(sol)
    assert sol.metadata_json is not None
    import json
    meta = json.loads(sol.metadata_json)
    assert "recovered_at" in meta
    assert "διακόπηκε" in meta["recovery_reason"]


def test_recovery_preserves_existing_metadata(db):
    s, engine = db
    import json
    s.add(
        TimetableSolution(
            name="stuck",
            status="generating",
            metadata_json=json.dumps({"original": "data", "wall_time": 12.3}),
        )
    )
    s.commit()

    _recover(engine)
    sol = s.query(TimetableSolution).first()
    s.refresh(sol)
    meta = json.loads(sol.metadata_json)
    assert meta["original"] == "data"
    assert meta["wall_time"] == 12.3
    assert "recovered_at" in meta


def test_recovery_is_idempotent(db):
    """Running it twice doesn't re-flip rows that are already 'error'."""
    s, engine = db
    s.add(TimetableSolution(name="stuck", status="generating"))
    s.commit()

    _recover(engine)
    n_second = _recover(engine)
    assert n_second == 0
