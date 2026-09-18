"""«Τι επηρεάζει αυτή η ώρα;» + ασφαλές καθάρισμα/διαγραφή μαθήματος-κάρτας.

Η Παλέτα δείχνει ώρες που δεν μπήκαν ακόμα στο πρόγραμμα. Πριν τις σβήσει ο
χρήστης πρέπει να βλέπει πού χρησιμοποιείται το μάθημα — και το σβήσιμο δεν
επιτρέπεται ποτέ να πάρει μαζί του τοποθετημένη ώρα χωρίς ρητή έγκριση.
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
    Student,
    StudentClassEnrollment,
    Subject,
    Teacher,
    TimetableSlot,
    TimetableSolution,
)
from backend.routers import lessons as lessons_router


@pytest.fixture()
def client():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()

    subj = Subject(name="Άλγεβρα", short_name="ΑΛΓ", color="#000")
    teacher = Teacher(name="Καθ Α", short_name="ΚΑ", color="#000")
    cls = SchoolClass(name="Β2", short_name="Β2")
    room = Classroom(name="Αίθ 1", short_name="Α1", room_type="regular")
    period = Period(name="1η", short_name="1", start_time="14:00",
                    end_time="15:00", is_break=False, sort_order=1)
    s.add_all([subj, teacher, cls, room, period])
    s.commit()
    for o in (subj, teacher, cls, room, period):
        s.refresh(o)

    for first in ("Νίκος", "Μαρία"):
        st = Student(first_name=first, last_name="Δοκιμή")
        s.add(st)
        s.commit()
        s.refresh(st)
        s.add(StudentClassEnrollment(student_id=st.id, class_id=cls.id))
    s.commit()

    app = FastAPI()
    app.include_router(lessons_router.router, prefix="/api/lessons")
    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session, c.subj, c.teacher, c.cls, c.room, c.period = s, subj, teacher, cls, room, period
    yield c
    s.close()


def _lesson(c, ppw=4):
    lesson = Lesson(subject_id=c.subj.id, teacher_id=c.teacher.id,
                    class_id=c.cls.id, periods_per_week=ppw)
    c.session.add(lesson)
    c.session.commit()
    c.session.refresh(lesson)
    return lesson


def _solution(c, name):
    sol = TimetableSolution(name=name, status="optimal")
    c.session.add(sol)
    c.session.commit()
    c.session.refresh(sol)
    return sol


def _slots(c, sol, lesson, placed=0, unplaced=0):
    for i in range(placed):
        c.session.add(TimetableSlot(solution_id=sol.id, lesson_id=lesson.id,
                                    day_of_week=i % 5, period_id=c.period.id,
                                    classroom_id=c.room.id, is_unplaced=False))
    for _ in range(unplaced):
        c.session.add(TimetableSlot(solution_id=sol.id, lesson_id=lesson.id,
                                    is_unplaced=True))
    c.session.commit()


def _counts(c, sol_id, lesson_id):
    rows = c.session.query(TimetableSlot).filter(
        TimetableSlot.solution_id == sol_id, TimetableSlot.lesson_id == lesson_id).all()
    return (sum(1 for r in rows if not r.is_unplaced), sum(1 for r in rows if r.is_unplaced))


@pytest.fixture()
def scenario(client):
    """4 ώρες/εβδ.: πρόγραμμα Α με 3 τοποθετημένες, Β με 1."""
    lesson = _lesson(client, ppw=4)
    sol_a, sol_b = _solution(client, "Πρόγραμμα Α"), _solution(client, "Πρόγραμμα Β")
    _slots(client, sol_a, lesson, placed=3, unplaced=1)
    _slots(client, sol_b, lesson, placed=1, unplaced=3)
    return client, lesson, sol_a, sol_b


def test_impact_shows_where_the_lesson_is_used(scenario):
    c, lesson, sol_a, sol_b = scenario
    body = c.get(f"/api/lessons/{lesson.id}/impact").json()

    assert body["lesson"]["subject_name"] == "Άλγεβρα"
    assert body["lesson"]["class_name"] == "Β2" and body["lesson"]["class_students"] == 2
    assert body["lesson"]["periods_per_week"] == 4
    rows = {r["solution_name"]: r for r in body["solutions"]}
    assert rows["Πρόγραμμα Α"]["placed"] == 3 and rows["Πρόγραμμα Α"]["unplaced"] == 1
    assert rows["Πρόγραμμα Β"]["placed"] == 1 and rows["Πρόγραμμα Β"]["unplaced"] == 3
    assert body["totals"] == {"solutions": 2, "placed": 4, "unplaced": 4, "max_placed": 3}
    # Καθάρισμα μέχρι τις τοποθετημένες του «γεμάτου» προγράμματος — ποτέ πιο κάτω.
    assert body["trim"] == {"can_trim": True, "trim_to": 3, "would_remove": 1, "blocked_reason": None}
    assert body["delete"] == {"placed_total": 4, "solutions_with_placed": 2, "requires_force": True}


def test_impact_404_for_unknown_lesson(client):
    assert client.get("/api/lessons/999/impact").status_code == 404


def test_trim_removes_only_palette_hours(scenario):
    c, lesson, sol_a, sol_b = scenario
    res = c.post(f"/api/lessons/{lesson.id}/trim-unplaced")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["periods_per_week"] == 3 and body["removed"] == 2
    assert "καμία τοποθετημένη ώρα" in body["message"].lower()

    assert _counts(c, sol_a.id, lesson.id) == (3, 0)      # έμεινε ό,τι ήταν τοποθετημένο
    assert _counts(c, sol_b.id, lesson.id) == (1, 2)
    c.session.refresh(lesson)
    assert lesson.periods_per_week == 3


def test_trim_refuses_when_the_palette_is_empty(scenario):
    c, lesson, *_ = scenario
    c.post(f"/api/lessons/{lesson.id}/trim-unplaced")
    again = c.post(f"/api/lessons/{lesson.id}/trim-unplaced")
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "nothing_to_trim"


def test_trim_refuses_when_nothing_is_placed_and_points_to_delete(client):
    lesson = _lesson(client, ppw=2)
    sol = _solution(client, "Μόνο παλέτα")
    _slots(client, sol, lesson, placed=0, unplaced=2)

    res = client.post(f"/api/lessons/{lesson.id}/trim-unplaced")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "no_placed_hours"
    assert "διάγραψε" in detail["message"].lower()
    assert detail["impact"]["lesson"]["id"] == lesson.id


def test_delete_needs_explicit_force_when_hours_are_placed(scenario):
    c, lesson, sol_a, _sol_b = scenario
    res = c.delete(f"/api/lessons/{lesson.id}")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["requires_force"] is True and detail["code"] == "lesson_has_placed_slots"
    assert "4 τοποθετημένες ώρες" in detail["message"]
    assert _counts(c, sol_a.id, lesson.id) == (3, 1)          # τίποτα δεν σβήστηκε
    assert c.session.query(Lesson).filter(Lesson.id == lesson.id).first() is not None


def test_delete_with_force_removes_the_lesson_everywhere(scenario):
    c, lesson, sol_a, sol_b = scenario
    assert c.delete(f"/api/lessons/{lesson.id}?force=true").status_code == 204
    assert c.session.query(Lesson).filter(Lesson.id == lesson.id).first() is None
    assert _counts(c, sol_a.id, lesson.id) == (0, 0)
    assert _counts(c, sol_b.id, lesson.id) == (0, 0)


def test_delete_without_placed_hours_needs_no_force(client):
    lesson = _lesson(client, ppw=2)
    sol = _solution(client, "Μόνο παλέτα")
    _slots(client, sol, lesson, placed=0, unplaced=2)
    assert client.delete(f"/api/lessons/{lesson.id}").status_code == 204
    assert client.session.query(Lesson).filter(Lesson.id == lesson.id).first() is None


# ─── 🧹 μαζικό καθάρισμα Παλέτας ──────────────────────────────────────


@pytest.fixture()
def cleanup_env(client):
    """l1: περισσεύει 1 ώρα (trim)· l2: μόνο Παλέτα (delete)· l3: τις κρατά
    άλλο πρόγραμμα (keep)· l4: όλες τοποθετημένες (εκτός λίστας)·
    l5: ώρες Παλέτας μόνο σε ΑΡΧΕΙΟΘΕΤΗΜΕΝΟ πρόγραμμα (εκτός λίστας)."""
    from backend.models import TimetableSolution as TS
    import datetime as _dt

    c = client
    a, b = _solution(c, "Α"), _solution(c, "Β")
    old = _solution(c, "Παλιό")
    old.archived_at = _dt.datetime(2026, 9, 18)
    c.session.commit()
    l1, l2, l3, l4, l5 = _lesson(c, 4), _lesson(c, 2), _lesson(c, 3), _lesson(c, 2), _lesson(c, 1)
    _slots(c, a, l1, placed=3, unplaced=1)
    _slots(c, b, l1, placed=1, unplaced=3)
    _slots(c, a, l2, unplaced=2)
    _slots(c, a, l3, unplaced=3)
    _slots(c, b, l3, placed=3)
    _slots(c, a, l4, placed=2)
    _slots(c, old, l5, unplaced=1)
    assert c.session.query(TS).count() == 3
    return c, {"l1": l1.id, "l2": l2.id, "l3": l3.id, "l4": l4.id, "l5": l5.id, "a": a.id, "b": b.id}


def test_palette_review_suggests_only_safe_actions(cleanup_env):
    c, ids = cleanup_env
    review = c.get("/api/lessons/palette-review?term_id=1").json()
    by = {i["lesson_id"]: i for i in review["items"]}
    assert set(by) == {ids["l1"], ids["l2"], ids["l3"]}          # όχι l4 (όλα μέσα), όχι l5 (αρχείο)
    assert by[ids["l1"]]["suggestion"] == "trim" and by[ids["l1"]]["trim"]["would_remove"] == 1
    assert by[ids["l2"]]["suggestion"] == "delete"
    assert by[ids["l3"]]["suggestion"] == "keep"
    assert [i["suggestion"] for i in review["items"]] == ["trim", "delete", "keep"]
    assert review["totals"] == {"lessons": 3, "palette_hours": 9, "trim_hours": 1, "deletable": 1}


def test_palette_cleanup_never_touches_placed_hours(cleanup_env):
    c, ids = cleanup_env
    res = c.post("/api/lessons/palette-cleanup", json={
        "trim_ids": [ids["l1"], ids["l3"]], "delete_ids": [ids["l2"], ids["l3"], 999]}).json()
    assert (res["trimmed"], res["deleted"]) == (1, 1)
    assert res["hours_removed"] == 2                             # 1 ώρα × 2 προγράμματα Παλέτας
    skipped = {s["lesson_id"]: s["reason"] for s in res["skipped"]}
    assert "Δεν περισσεύουν" in skipped[ids["l3"]] or "τοποθετημένες" in skipped[ids["l3"]]
    assert "Δεν βρέθηκε" in skipped[999]

    assert _counts(c, ids["a"], ids["l1"]) == (3, 0)             # τοποθετημένες ανέγγιχτες
    assert _counts(c, ids["b"], ids["l1"]) == (1, 2)
    assert c.session.query(Lesson).filter(Lesson.id == ids["l2"]).first() is None
    assert _counts(c, ids["b"], ids["l3"]) == (3, 0)             # το l3 δεν σβήστηκε
    assert c.session.query(Lesson).filter(Lesson.id == ids["l3"]).first() is not None
