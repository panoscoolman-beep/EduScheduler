"""«⚙️ Φόρτωση Προεπιλεγμένων» περιορισμών (POST /constraints/seed-defaults).

Από 2/10/2026 το seed δεν φτιάχνει πια το «Αποφυγή πολλών συνεχόμενων»
(max_consecutive): ο solver δεν έχει τέτοιον κανόνα, άρα η γραμμή δεν έκανε
τίποτα. Γραμμές που υπάρχουν ήδη στη βάση ΔΕΝ αγγίζονται — το seed τρέχει μόνο
σε άδειο πίνακα (αλλιώς 409) και τίποτα δεν σβήνεται ή ξαναφτιάχνεται.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import Constraint
from backend.routers import constraints as constraints_router
from backend.solver.hard_rules import BUILTIN_TYPES, ENFORCEABLE_TYPES, SOFT_ONLY_TYPES


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    app = FastAPI()
    app.include_router(constraints_router.router, prefix="/api/constraints")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.s = s
    yield client
    s.close()


def _types(rows):
    return [json.loads(r["rule"] if isinstance(r, dict) else r.rule)["type"] for r in rows]


def test_seed_has_no_max_consecutive_and_only_rules_the_solver_understands(env):
    res = env.post("/api/constraints/seed-defaults")
    assert res.status_code == 201, res.text
    rows = res.json()
    types = _types(rows)
    assert "max_consecutive" not in types
    assert "Αποφυγή πολλών συνεχόμενων" not in [r["name"] for r in rows]
    for row, rtype in zip(rows, types):
        if row["constraint_type"] == "hard":
            assert rtype in BUILTIN_TYPES                     # ετικέτες κανόνων που ισχύουν πάντα
        else:
            assert rtype in SOFT_ONLY_TYPES | ENFORCEABLE_TYPES   # ο solver τους εφαρμόζει
    assert len(rows) == 9 and len(env.s.query(Constraint).all()) == 9


def test_reseed_on_existing_rows_changes_nothing(env):
    """Παλιά βάση με το max_consecutive ήδη μέσα: το seed απορρίπτεται (409) και
    καμία γραμμή δεν σβήνεται, δεν αλλάζει, δεν ξαναφτιάχνεται."""
    env.s.add_all([
        Constraint(name="Αποφυγή πολλών συνεχόμενων", constraint_type="soft", category="general",
                   rule='{"type": "max_consecutive"}', weight=60, is_active=True),
        Constraint(name="Δικός μου", constraint_type="hard", category="teacher",
                   rule='{"type": "teacher_preferred_days", "teacher_id": 1, "days": [0]}',
                   weight=40, is_active=False),
    ])
    env.s.commit()

    def snapshot():
        env.s.expire_all()
        return sorted((c.id, c.name, c.constraint_type, c.category, c.rule, c.weight, c.is_active)
                      for c in env.s.query(Constraint).all())

    before = snapshot()
    res = env.post("/api/constraints/seed-defaults")
    assert res.status_code == 409
    assert snapshot() == before
