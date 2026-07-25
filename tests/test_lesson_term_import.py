"""Tests for selective lesson import from another term.

GET /lessons/?term_id=X (λίστα άλλου σεναρίου για τον picker) και
POST /lessons/import-from-term (επιλεκτική αντιγραφή στο ενεργό, με
dedup σε subject+teacher+class και πάρκινγκ των νέων ωρών στις
ανοιχτές λύσεις ΜΟΝΟ του ενεργού σεναρίου).
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
    SchoolClass,
    Subject,
    Teacher,
    Term,
    TimetableSlot,
    TimetableSolution,
)
from backend.routers import lessons as lessons_router


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    # Term 1 = ενεργό (target), Term 2 = παλιό σενάριο (source)
    t_active = Term(id=1, name="Νέο", is_active=True)
    t_old = Term(id=2, name="Παλιό", is_active=False)
    subj = Subject(name="Μαθηματικά", short_name="Μ", color="#000")
    subj2 = Subject(name="Φυσική", short_name="Φ", color="#000")
    teacher = Teacher(name="Τ1", short_name="Τ1", color="#000")
    cls = SchoolClass(name="Α1", short_name="Α1")
    room = Classroom(name="R1", short_name="R1", room_type="regular")
    s.add_all([t_active, t_old, subj, subj2, teacher, cls, room])
    s.commit()
    for o in [subj, subj2, teacher, cls, room]:
        s.refresh(o)

    def make_lesson(term_id, subject, ppw=3, distribution=None):
        lesson = Lesson(
            term_id=term_id, subject_id=subject.id, teacher_id=teacher.id,
            class_id=cls.id, classroom_id=room.id,
            periods_per_week=ppw, duration=1, distribution=distribution,
        )
        s.add(lesson)
        s.commit()
        s.refresh(lesson)
        return lesson

    app = FastAPI()
    app.include_router(lessons_router.router, prefix="/api/lessons")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.s = s
    client.make_lesson = make_lesson
    client.subj, client.subj2 = subj, subj2
    client.teacher, client.cls = teacher, cls
    yield client
    s.close()


def test_list_lessons_scopes_by_term_param(env):
    env.make_lesson(term_id=1, subject=env.subj)
    old = env.make_lesson(term_id=2, subject=env.subj2)

    default = env.get("/api/lessons/").json()
    assert [l["subject_name"] for l in default] == ["Μαθηματικά"]  # active only

    other = env.get("/api/lessons/?term_id=2").json()
    assert [l["id"] for l in other] == [old.id]

    assert env.get("/api/lessons/?term_id=99").status_code == 404


def test_import_copies_fields_and_dedups(env):
    src_math = env.make_lesson(term_id=2, subject=env.subj, ppw=4, distribution="2,2")
    src_phys = env.make_lesson(term_id=2, subject=env.subj2, ppw=3)
    # Το ενεργό έχει ήδη ΙΔΙΟ (subject+teacher+class) με το src_math
    env.make_lesson(term_id=1, subject=env.subj, ppw=5)

    res = env.post("/api/lessons/import-from-term", json={
        "source_term_id": 2,
        "lesson_ids": [src_math.id, src_phys.id, 9999],
    })
    assert res.status_code == 200
    body = res.json()
    assert body["created"] == 1                      # μόνο η Φυσική
    reasons = {s["lesson_id"]: s["reason"] for s in body["skipped"]}
    assert reasons[src_math.id] == "already_exists"
    assert reasons[9999] == "not_in_source_term"

    imported = (
        env.s.query(Lesson)
        .filter(Lesson.term_id == 1, Lesson.subject_id == env.subj2.id)
        .one()
    )
    assert imported.periods_per_week == 3
    assert imported.classroom_id is not None
    # Το source παραμένει άθικτο στο δικό του σενάριο
    env.s.refresh(src_phys)
    assert src_phys.term_id == 2


def test_import_parks_hours_only_in_active_term_solutions(env):
    sol_active = TimetableSolution(name="a", status="optimal", term_id=1)
    sol_old = TimetableSolution(name="b", status="optimal", term_id=2)
    env.s.add_all([sol_active, sol_old])
    env.s.commit()
    env.s.refresh(sol_active)
    env.s.refresh(sol_old)

    src = env.make_lesson(term_id=2, subject=env.subj2, ppw=2)
    res = env.post("/api/lessons/import-from-term", json={
        "source_term_id": 2, "lesson_ids": [src.id],
    })
    assert res.status_code == 200
    new_id = res.json()["created_ids"][0]

    in_active = (
        env.s.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == sol_active.id,
                TimetableSlot.lesson_id == new_id)
        .count()
    )
    in_old = (
        env.s.query(TimetableSlot)
        .filter(TimetableSlot.solution_id == sol_old.id)
        .count()
    )
    assert in_active == 2      # ×2 ώρες στην Παλέτα της ενεργής λύσης
    assert in_old == 0         # το παλιό σενάριο δεν αγγίχτηκε


def test_import_rejects_same_or_missing_source_term(env):
    lesson = env.make_lesson(term_id=1, subject=env.subj)
    assert env.post("/api/lessons/import-from-term", json={
        "source_term_id": 1, "lesson_ids": [lesson.id],
    }).status_code == 400
    assert env.post("/api/lessons/import-from-term", json={
        "source_term_id": 99, "lesson_ids": [1],
    }).status_code == 404
