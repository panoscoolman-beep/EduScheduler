"""Tests for POST /solutions/{sid}/slots/swap — ανταλλαγή δύο καρτών.

Το swap πρέπει: να ελέγχει τον καθένα στο κελί του άλλου ΑΓΝΟΩΝΤΑΣ τον
άλλον (αδειάζει ταυτόχρονα), να κρατά τις αίθουσες όταν χωράνε, να
είναι ατομικό στα σφάλματα, και να γράφει δύο βήματα undo.
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
    SchoolSettings,
    Student,
    StudentClassEnrollment,
    Subject,
    Teacher,
    TeacherAvailability,
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
    Session = sessionmaker(bind=engine)
    s = Session()

    s.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))
    subj = Subject(name="Μ", short_name="Μ", color="#000")
    t1 = Teacher(name="Τ1", short_name="Τ1", color="#000")
    t2 = Teacher(name="Τ2", short_name="Τ2", color="#000")
    c1 = SchoolClass(name="Α1", short_name="Α1")
    c2 = SchoolClass(name="Β2", short_name="Β2")
    r1 = Classroom(name="R1", short_name="R1", room_type="regular")
    r2 = Classroom(name="R2", short_name="R2", room_type="regular")
    p1 = Period(name="1η", short_name="1", start_time="08:00",
                end_time="08:50", is_break=False, sort_order=1)
    p2 = Period(name="2η", short_name="2", start_time="09:00",
                end_time="09:50", is_break=False, sort_order=2)
    s.add_all([subj, t1, t2, c1, c2, r1, r2, p1, p2])
    s.commit()
    for o in [subj, t1, t2, c1, c2, r1, r2, p1, p2]:
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
    client = TestClient(app)
    client.s = s
    client.sol = sol
    client.subj = subj
    client.t1, client.t2 = t1, t2
    client.c1, client.c2 = c1, c2
    client.r1, client.r2 = r1, r2
    client.p1, client.p2 = p1, p2
    yield client
    s.close()


def _lesson(env, teacher, cls):
    lesson = Lesson(
        subject_id=env.subj.id, teacher_id=teacher.id, class_id=cls.id,
        periods_per_week=2, duration=1,
    )
    env.s.add(lesson)
    env.s.commit()
    env.s.refresh(lesson)
    return lesson


def _slot(env, lesson, day, period, room, locked=False):
    slot = TimetableSlot(
        solution_id=env.sol.id, lesson_id=lesson.id, day_of_week=day,
        period_id=period.id, classroom_id=room.id,
        is_unplaced=False, is_locked=locked,
    )
    env.s.add(slot)
    env.s.commit()
    env.s.refresh(slot)
    return slot


def _swap(env, a, b):
    return env.post(
        f"/api/solver/solutions/{env.sol.id}/slots/swap",
        json={"slot_a_id": a.id, "slot_b_id": b.id},
    )


def test_simple_swap_exchanges_cells_and_keeps_rooms(env):
    a = _slot(env, _lesson(env, env.t1, env.c1), 0, env.p1, env.r1)
    b = _slot(env, _lesson(env, env.t2, env.c2), 2, env.p2, env.r2)

    res = _swap(env, a, b)
    assert res.status_code == 200
    body = res.json()
    assert body["slot_a"]["day_of_week"] == 2
    assert body["slot_a"]["period_id"] == env.p2.id
    assert body["slot_b"]["day_of_week"] == 0
    assert body["slot_b"]["period_id"] == env.p1.id
    # Δικές τους αίθουσες — και οι δύο χωρούσαν στα νέα κελιά
    assert body["slot_a"]["classroom_id"] == env.r1.id
    assert body["slot_b"]["classroom_id"] == env.r2.id


def test_swap_same_teacher_cards_is_legal(env):
    """Δύο μαθήματα του ΙΔΙΟΥ καθηγητή ανταλλάσσουν ώρες — ο απλός
    έλεγχος μετακίνησης θα έβλεπε 'διδάσκει ήδη'· το swap όχι, γιατί
    ο άλλος αδειάζει ταυτόχρονα."""
    lesson1 = _lesson(env, env.t1, env.c1)
    lesson2 = _lesson(env, env.t1, env.c2)   # ίδιος καθηγητής
    a = _slot(env, lesson1, 0, env.p1, env.r1)
    b = _slot(env, lesson2, 0, env.p2, env.r1)  # ίδια μέρα, άλλη ώρα, ίδια αίθουσα

    res = _swap(env, a, b)
    assert res.status_code == 200
    env.s.refresh(a)
    env.s.refresh(b)
    assert (a.day_of_week, a.period_id) == (0, env.p2.id)
    assert (b.day_of_week, b.period_id) == (0, env.p1.id)


def test_swap_blocked_by_availability_changes_nothing(env):
    # Ο Τ1 έχει κώλυμα στο κελί του Β — το swap πρέπει να αποτύχει ΚΑΙ
    # να μη μετακινηθεί κανείς (ατομικότητα).
    env.s.add(TeacherAvailability(
        teacher_id=env.t1.id, day_of_week=3, period_id=env.p2.id,
        status="unavailable",
    ))
    env.s.commit()
    a = _slot(env, _lesson(env, env.t1, env.c1), 0, env.p1, env.r1)
    b = _slot(env, _lesson(env, env.t2, env.c2), 3, env.p2, env.r2)

    res = _swap(env, a, b)
    assert res.status_code == 400
    env.s.refresh(a)
    env.s.refresh(b)
    assert (a.day_of_week, a.period_id) == (0, env.p1.id)
    assert (b.day_of_week, b.period_id) == (3, env.p2.id)


def test_swap_blocked_by_h7_shared_student_with_third_card(env):
    # Στο κελί του Β υπάρχει και τρίτη κάρτα C τμήματος που μοιράζεται
    # μαθητή με το τμήμα του Α → ο Α δεν χωρά εκεί ούτε με swap.
    st = Student(first_name="Ν", last_name="Κ")
    env.s.add(st)
    env.s.commit()
    env.s.refresh(st)
    c3 = SchoolClass(name="Γ3", short_name="Γ3")
    t3 = Teacher(name="Τ3", short_name="Τ3", color="#000")
    r3 = Classroom(name="R3", short_name="R3", room_type="regular")
    env.s.add_all([c3, t3, r3])
    env.s.commit()
    for o in [c3, t3, r3]:
        env.s.refresh(o)
    env.s.add_all([
        StudentClassEnrollment(student_id=st.id, class_id=env.c1.id),
        StudentClassEnrollment(student_id=st.id, class_id=c3.id),
    ])
    env.s.commit()

    a = _slot(env, _lesson(env, env.t1, env.c1), 0, env.p1, env.r1)
    b = _slot(env, _lesson(env, env.t2, env.c2), 2, env.p2, env.r2)
    _slot(env, _lesson(env, t3, c3), 2, env.p2, r3)     # η τρίτη κάρτα

    res = _swap(env, a, b)
    assert res.status_code == 400
    assert "μαθητής" in res.json()["detail"].lower()


def test_swap_reassigns_room_when_own_room_taken_by_third_card(env):
    # Στο κελί του Β η R1 (αίθουσα του Α) είναι πιασμένη από τρίτη κάρτα
    # → ο Α παίρνει αυτόματα άλλη ελεύθερη. Η R2 του Β μετρά ως ελεύθερη
    # εκεί (ο Β αδειάζει το κελί με το swap) — ίδια αίθουσα σε
    # διαφορετικές ώρες είναι νόμιμη, οπότε ο Α παίρνει την R2 και ο Β
    # την κρατά στη δική του νέα ώρα.
    t3 = Teacher(name="Τ3", short_name="Τ3", color="#000")
    c3 = SchoolClass(name="Γ3", short_name="Γ3")
    env.s.add_all([t3, c3])
    env.s.commit()
    for o in [t3, c3]:
        env.s.refresh(o)

    a = _slot(env, _lesson(env, env.t1, env.c1), 0, env.p1, env.r1)
    b = _slot(env, _lesson(env, env.t2, env.c2), 2, env.p2, env.r2)
    _slot(env, _lesson(env, t3, c3), 2, env.p2, env.r1)  # R1 πιασμένη στο κελί του Β

    res = _swap(env, a, b)
    assert res.status_code == 200
    env.s.refresh(a)
    env.s.refresh(b)
    assert a.classroom_id == env.r2.id   # όχι R1 (πιασμένη από τρίτη κάρτα)
    assert (a.day_of_week, a.period_id) == (2, env.p2.id)
    assert b.classroom_id == env.r2.id   # ίδια αίθουσα, άλλη ώρα — νόμιμο
    assert (b.day_of_week, b.period_id) == (0, env.p1.id)


def test_swap_refuses_locked_unplaced_same_cell_and_missing(env):
    lesson1 = _lesson(env, env.t1, env.c1)
    lesson2 = _lesson(env, env.t2, env.c2)
    a = _slot(env, lesson1, 0, env.p1, env.r1)
    locked = _slot(env, lesson2, 1, env.p2, env.r2, locked=True)
    assert _swap(env, a, locked).status_code == 400

    unplaced = TimetableSlot(
        solution_id=env.sol.id, lesson_id=lesson2.id,
        day_of_week=None, period_id=None, classroom_id=None, is_unplaced=True,
    )
    env.s.add(unplaced)
    env.s.commit()
    env.s.refresh(unplaced)
    assert _swap(env, a, unplaced).status_code == 400

    res = env.post(
        f"/api/solver/solutions/{env.sol.id}/slots/swap",
        json={"slot_a_id": a.id, "slot_b_id": a.id},
    )
    assert res.status_code == 400

    assert env.post(
        f"/api/solver/solutions/{env.sol.id}/slots/swap",
        json={"slot_a_id": a.id, "slot_b_id": 9999},
    ).status_code == 404


def test_swap_writes_two_undo_steps_that_fully_revert(env):
    a = _slot(env, _lesson(env, env.t1, env.c1), 0, env.p1, env.r1)
    b = _slot(env, _lesson(env, env.t2, env.c2), 2, env.p2, env.r2)
    assert _swap(env, a, b).status_code == 200

    assert env.post(f"/api/solver/solutions/{env.sol.id}/undo").status_code == 200
    assert env.post(f"/api/solver/solutions/{env.sol.id}/undo").status_code == 200
    env.s.refresh(a)
    env.s.refresh(b)
    assert (a.day_of_week, a.period_id, a.classroom_id) == (0, env.p1.id, env.r1.id)
    assert (b.day_of_week, b.period_id, b.classroom_id) == (2, env.p2.id, env.r2.id)
