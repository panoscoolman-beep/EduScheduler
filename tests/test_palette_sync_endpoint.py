"""Tests for POST /solutions/{sid}/lessons/{lid}/sync-slots.

Η Παλέτα Μαθημάτων βασίζεται στο ότι κάθε μάθημα έχει slots (placed +
unplaced) σε κάθε ενεργή λύση. Για λύσεις παλαιότερες από το
parking-lot sync, ώρες μπορεί να λείπουν εντελώς — το endpoint τις
υλοποιεί ως unplaced ώστε να εμφανιστούν draggable κάρτες.
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
    TimetableSlot,
    TimetableSolution,
)
from backend.routers import solver as solver_router


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    subj = Subject(name="M", short_name="M", color="#000")
    teacher = Teacher(name="T", short_name="T", color="#000")
    cls = SchoolClass(name="A1", short_name="A1")
    room = Classroom(name="R1", short_name="R1", room_type="regular")
    period = Period(
        name="1η", short_name="1", start_time="08:00",
        end_time="08:50", is_break=False, sort_order=1,
    )
    s.add_all([subj, teacher, cls, room, period])
    s.commit()
    for o in [subj, teacher, cls, room, period]:
        s.refresh(o)

    sol = TimetableSolution(name="t", status="optimal")
    s.add(sol)
    s.commit()
    s.refresh(sol)

    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    test_client = TestClient(app)
    test_client.session = s
    test_client.sol = sol
    test_client.subj = subj
    test_client.teacher = teacher
    test_client.cls = cls
    test_client.period = period
    test_client.room = room
    yield test_client
    s.close()


def _make_lesson(client, ppw=3, term_id=1):
    lesson = Lesson(
        subject_id=client.subj.id,
        teacher_id=client.teacher.id,
        class_id=client.cls.id,
        periods_per_week=ppw,
        duration=1,
        term_id=term_id,
    )
    client.session.add(lesson)
    client.session.commit()
    client.session.refresh(lesson)
    return lesson


def _slots_for(client, lesson_id):
    return (
        client.session.query(TimetableSlot)
        .filter(
            TimetableSlot.solution_id == client.sol.id,
            TimetableSlot.lesson_id == lesson_id,
        )
        .all()
    )


def test_materializes_all_missing_hours_as_unplaced(client):
    lesson = _make_lesson(client, ppw=4)
    # The solution predates the lesson — zero slots exist.
    assert _slots_for(client, lesson.id) == []

    res = client.post(
        f"/api/solver/solutions/{client.sol.id}/lessons/{lesson.id}/sync-slots"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["added"] == 4

    slots = _slots_for(client, lesson.id)
    assert len(slots) == 4
    assert all(s.is_unplaced for s in slots)
    assert all(s.day_of_week is None for s in slots)


def test_partial_deficit_adds_only_the_difference(client):
    lesson = _make_lesson(client, ppw=3)
    # One hour already placed manually, one unplaced — one missing.
    client.session.add_all([
        TimetableSlot(
            solution_id=client.sol.id, lesson_id=lesson.id,
            day_of_week=0, period_id=client.period.id,
            classroom_id=client.room.id, is_unplaced=False,
        ),
        TimetableSlot(
            solution_id=client.sol.id, lesson_id=lesson.id,
            day_of_week=None, period_id=None, classroom_id=None,
            is_unplaced=True,
        ),
    ])
    client.session.commit()

    res = client.post(
        f"/api/solver/solutions/{client.sol.id}/lessons/{lesson.id}/sync-slots"
    )
    assert res.status_code == 200
    assert res.json()["added"] == 1

    slots = _slots_for(client, lesson.id)
    assert len(slots) == 3
    placed = [s for s in slots if not s.is_unplaced]
    assert len(placed) == 1  # placed slot untouched


def test_idempotent_when_nothing_missing(client):
    lesson = _make_lesson(client, ppw=2)
    client.post(
        f"/api/solver/solutions/{client.sol.id}/lessons/{lesson.id}/sync-slots"
    )
    res = client.post(
        f"/api/solver/solutions/{client.sol.id}/lessons/{lesson.id}/sync-slots"
    )
    assert res.status_code == 200
    assert res.json()["added"] == 0
    assert len(_slots_for(client, lesson.id)) == 2


def test_404_on_unknown_solution_or_lesson(client):
    lesson = _make_lesson(client)
    assert client.post(
        f"/api/solver/solutions/999/lessons/{lesson.id}/sync-slots"
    ).status_code == 404
    assert client.post(
        f"/api/solver/solutions/{client.sol.id}/lessons/999/sync-slots"
    ).status_code == 404


def test_400_on_cross_term_lesson(client):
    lesson = _make_lesson(client, term_id=2)  # solution is term 1
    res = client.post(
        f"/api/solver/solutions/{client.sol.id}/lessons/{lesson.id}/sync-slots"
    )
    assert res.status_code == 400


def test_409_on_inactive_solution(client):
    lesson = _make_lesson(client)
    client.sol.status = "draft"
    client.session.commit()
    res = client.post(
        f"/api/solver/solutions/{client.sol.id}/lessons/{lesson.id}/sync-slots"
    )
    assert res.status_code == 409
