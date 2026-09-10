"""PATCH /api/solver/solutions/{id} — μετονομασία προγράμματος.

Αλλάζει ΜΟΝΟ το όνομα: slots, κλειδώματα και σενάριο μένουν ίδια. Κενό όνομα
→ 422, ανύπαρκτη λύση → 404, διπλό όνομα στο ίδιο σενάριο → 409 (σε άλλο
σενάριο επιτρέπεται).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom,
    Lesson,
    Period,
    SchoolClass,
    Subject,
    Teacher,
    Term,
    TimetableSlot,
    TimetableSolution,
)
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
    subj = Subject(name="Μαθηματικά", short_name="Μ", color="#000")
    teacher = Teacher(name="Τ", short_name="Τ", color="#000")
    klass = SchoolClass(name="Α1", short_name="Α1")
    period = Period(name="1η", short_name="1", start_time="16:00", end_time="17:00",
                    is_break=False, sort_order=1)
    room = Classroom(name="Αίθουσα 1", short_name="Α1")
    s.add_all([t1, t2, subj, teacher, klass, period, room])
    s.commit()
    for o in (t1, t2, subj, teacher, klass, period, room):
        s.refresh(o)

    main = TimetableSolution(name="ΧΕΙΜΕΡΙΝΟ 2025-2026", status="feasible", term_id=t1.id)
    other = TimetableSolution(name="Πρόγραμμα v2", status="feasible", term_id=t1.id)
    elsewhere = TimetableSolution(name="Νέο", status="feasible", term_id=t2.id)
    s.add_all([main, other, elsewhere])
    s.commit()
    for o in (main, other, elsewhere):
        s.refresh(o)

    lesson = Lesson(subject_id=subj.id, teacher_id=teacher.id, class_id=klass.id,
                    periods_per_week=1, duration=1, term_id=t1.id)
    s.add(lesson)
    s.commit()
    s.refresh(lesson)
    # Τοποθετημένο slot ⇒ χρειάζεται αίθουσα (CHECK ck_slot_placement_consistent).
    slot = TimetableSlot(solution_id=main.id, lesson_id=lesson.id, day_of_week=2,
                         period_id=period.id, classroom_id=room.id,
                         is_locked=True, is_unplaced=False)
    s.add(slot)
    s.commit()
    s.refresh(slot)

    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session, c.main, c.other, c.elsewhere, c.slot = s, main, other, elsewhere, slot
    yield c
    s.close()


def _rename(env, solution_id, name):
    return env.patch(f"/api/solver/solutions/{solution_id}", json={"name": name})


def test_rename_changes_only_the_name_and_trims_it(env):
    res = _rename(env, env.main.id, "  Χειμερινό 2026-27 (τελικό)  ")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Χειμερινό 2026-27 (τελικό)"
    assert body["id"] == env.main.id and body["status"] == "feasible"
    assert body["term_id"] == env.main.term_id

    # Τα slots (θέση + κλείδωμα) μένουν ανέγγιχτα.
    env.session.expire_all()
    slot = env.session.get(TimetableSlot, env.slot.id)
    assert (slot.day_of_week, slot.is_locked, slot.solution_id) == (2, True, env.main.id)

    # Η λίστα και η λεπτομέρεια δείχνουν το νέο όνομα.
    names = [s["name"] for s in env.get("/api/solver/solutions").json()]
    assert "Χειμερινό 2026-27 (τελικό)" in names
    assert env.get(f"/api/solver/solutions/{env.main.id}").json()["name"] == "Χειμερινό 2026-27 (τελικό)"


def test_rename_rejects_blank_and_missing(env):
    assert _rename(env, env.main.id, "   ").status_code == 422
    assert _rename(env, env.main.id, "").status_code == 422
    assert env.patch(f"/api/solver/solutions/{env.main.id}", json={}).status_code == 422
    assert _rename(env, 99999, "Κάτι").status_code == 404


def test_rename_rejects_duplicate_in_same_term_but_allows_other_term(env):
    res = _rename(env, env.main.id, "Πρόγραμμα v2")
    assert res.status_code == 409
    assert "Πρόγραμμα v2" in res.json()["detail"]
    env.session.expire_all()
    assert env.session.get(TimetableSolution, env.main.id).name == "ΧΕΙΜΕΡΙΝΟ 2025-2026"

    # Ίδιο όνομα με λύση ΑΛΛΟΥ σεναρίου: επιτρέπεται.
    assert _rename(env, env.main.id, "Νέο").status_code == 200


def test_rename_to_its_own_name_is_a_noop_not_a_conflict(env):
    res = _rename(env, env.main.id, "ΧΕΙΜΕΡΙΝΟ 2025-2026")
    assert res.status_code == 200 and res.json()["name"] == "ΧΕΙΜΕΡΙΝΟ 2025-2026"


def test_rename_rejects_names_over_200_chars(env):
    assert _rename(env, env.main.id, "Α" * 201).status_code == 422
    assert _rename(env, env.main.id, "Α" * 200).status_code == 200
