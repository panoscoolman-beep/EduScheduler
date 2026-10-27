"""🧩 «Γέμισε τα κενά»: regenerate με ΟΛΕΣ τις τοποθετημένες ώρες σταθερές,
permissive, σε νέο πρόγραμμα. Ο solver αντικαθίσταται από καταγραφή."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, Subject, Teacher, TimetableSlot, TimetableSolution,
)
from backend.routers import solver as solver_router


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    subj = Subject(name="Φ", short_name="Φ", color="#000000")
    t = Teacher(name="Τ", short_name="Τ", color="#000000")
    c = SchoolClass(name="Β2", short_name="Β2")
    r = Classroom(name="Α", short_name="Α", room_type="regular")
    p = Period(name="1η", short_name="1η", start_time="14:00", end_time="15:00", is_break=False, sort_order=1)
    s.add_all([subj, t, c, r, p])
    s.commit()
    src = TimetableSolution(name="ΧΕΙΜΕΡΙΝΟ", status="optimal")
    lesson = Lesson(subject_id=subj.id, teacher_id=t.id, class_id=c.id, periods_per_week=3)
    s.add_all([src, lesson])
    s.commit()
    s.add_all([
        TimetableSlot(solution_id=src.id, lesson_id=lesson.id, day_of_week=0, period_id=p.id,
                      classroom_id=r.id, is_unplaced=False, is_locked=True),
        TimetableSlot(solution_id=src.id, lesson_id=lesson.id, day_of_week=1, period_id=p.id,
                      classroom_id=r.id, is_unplaced=False, is_locked=False),
        TimetableSlot(solution_id=src.id, lesson_id=lesson.id, is_unplaced=True),
    ])
    s.commit()
    runs = []
    monkeypatch.setattr(solver_router, "_run_generation_job", lambda *a: runs.append(a))
    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.session, client.src, client.runs = s, src, runs
    yield client
    s.close()


def test_fill_gaps_fixes_every_placed_hour_and_forces_permissive(env):
    res = env.post(f"/api/solver/regenerate/{env.src.id}",
                   json={"name": "Συμπλήρωση", "mode": "strict", "lock_all_placed": True})
    assert res.status_code == 200, res.text
    ((solution_id, _max_t, mode, warm, locked, meta),) = env.runs
    assert mode == "permissive"                                   # ό,τι δεν χωρά → Παλέτα
    assert sorted(a["day_of_week"] for a in locked) == [0, 1]     # ΚΑΙ η μη κλειδωμένη
    assert meta == {"locked_from_solution": env.src.id, "locked_count": 2, "fill_gaps": True}
    new = env.session.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    assert new.name == "Συμπλήρωση" and new.id != env.src.id      # νέο πρόγραμμα, όχι αλλαγή


def test_plain_lock_and_regenerate_is_unchanged(env):
    env.post(f"/api/solver/regenerate/{env.src.id}", json={"name": "v2", "mode": "strict"})
    ((_, _, mode, _, locked, meta),) = env.runs
    assert mode == "strict" and [a["day_of_week"] for a in locked] == [0] and meta["fill_gaps"] is False


def _name_of(env, res):
    assert res.status_code == 200, res.text
    sol = env.session.get(TimetableSolution, res.json()["solution_id"])
    sol.status = "optimal"                     # ο solver είναι mock: «τελείωσε» για το επόμενο
    env.session.commit()
    return sol.name


def test_same_name_in_a_scenario_gets_an_automatic_suffix(env):
    from backend.models import Term

    env.session.add(Term(id=1, name="Σενάριο", is_active=True))   # το ενεργό = του ΧΕΙΜΕΡΙΝΟ
    env.session.commit()
    regen = f"/api/solver/regenerate/{env.src.id}"
    assert _name_of(env, env.post(regen, json={"name": "ΧΕΙΜΕΡΙΝΟ"})) == "ΧΕΙΜΕΡΙΝΟ (2)"
    assert _name_of(env, env.post(regen, json={"name": "ΧΕΙΜΕΡΙΝΟ"})) == "ΧΕΙΜΕΡΙΝΟ (3)"
    assert _name_of(env, env.post("/api/solver/generate", json={"name": "Νέο"})) == "Νέο"
    assert _name_of(env, env.post("/api/solver/generate", json={"name": "Νέο"})) == "Νέο (2)"
    # Όνομα 200 χαρακτήρων (το όριο): το « (2)» χωρά, κόβοντας το τέλος του ονόματος.
    long = "Α" * 200
    assert _name_of(env, env.post("/api/solver/generate", json={"name": long})) == long
    assert _name_of(env, env.post("/api/solver/generate", json={"name": long})) == "Α" * 196 + " (2)"


class _FakeDb:
    """Session-στέλεχος: ψεύτικο dialect, καταγράφει τα raw execute, κανένα όνομα πιασμένο."""

    def __init__(self, dialect: str):
        self.dialect, self.executed = dialect, []

    def get_bind(self):
        from types import SimpleNamespace

        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))

    def execute(self, stmt, params=None):
        self.executed.append((str(stmt), params))

    def query(self, *a):
        return self

    def filter(self, *a):
        return self

    def all(self):
        return []


def test_name_choice_locks_the_scenario_only_on_postgres():
    """Δύο generate την ίδια στιγμή: σε Postgres το σενάριο κλειδώνει (advisory
    xact lock) ΠΡΙΝ διαβαστούν τα ονόματα· σε SQLite δεν εκδίδεται τίποτα."""
    pg = _FakeDb("postgresql")
    assert solver_router._unique_solution_name(pg, 7, "ΧΕΙΜΕΡΙΝΟ") == "ΧΕΙΜΕΡΙΝΟ"
    ((sql, params),) = pg.executed
    assert "pg_advisory_xact_lock" in sql
    assert params == {"ns": solver_router._NAME_LOCK_NAMESPACE, "key": 7}

    pg = _FakeDb("postgresql")
    solver_router._unique_solution_name(pg, None, "ΧΕΙΜΕΡΙΝΟ")         # χωρίς σενάριο → κλειδί 0
    assert pg.executed[0][1]["key"] == 0

    lite = _FakeDb("sqlite")
    assert solver_router._unique_solution_name(lite, 7, "ΧΕΙΜΕΡΙΝΟ") == "ΧΕΙΜΕΡΙΝΟ"
    assert lite.executed == []
