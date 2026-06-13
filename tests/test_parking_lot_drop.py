"""Tests for the parking-lot → grid drop flow.

Covers the auto-classroom-resolution that lets the drag-drop UI place
a parking-lot card without forcing the user to pick a room first.
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
    Subject,
    Teacher,
    TimetableSlot,
    TimetableSolution,
)
from backend.routers import solver as solver_router


@pytest.fixture()
def client():
    """Spin up a FastAPI app with only the solver router so we can
    drive the PUT slot endpoint through HTTP."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    s.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))

    subj = Subject(name="M", short_name="M", color="#000")
    lab_subj = Subject(
        name="Φυσική", short_name="Φ", color="#000",
        requires_special_room=True, special_room_type="lab",
    )
    teacher = Teacher(name="T", short_name="T", color="#000")
    cls = SchoolClass(name="A1", short_name="A1")
    regular = Classroom(name="R1", short_name="R1", room_type="regular")
    lab = Classroom(name="L1", short_name="L1", room_type="lab")
    period = Period(
        name="1η", short_name="1", start_time="08:00",
        end_time="08:50", is_break=False, sort_order=1,
    )
    s.add_all([subj, lab_subj, teacher, cls, regular, lab, period])
    s.commit()
    for o in [subj, lab_subj, teacher, cls, regular, lab, period]:
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
    test_client.subj = subj
    test_client.lab_subj = lab_subj
    test_client.teacher = teacher
    test_client.cls = cls
    test_client.regular = regular
    test_client.lab = lab
    test_client.period = period
    test_client.sol = sol
    yield test_client
    s.close()


def _make_unplaced_slot(client, lesson):
    slot = TimetableSlot(
        solution_id=client.sol.id,
        lesson_id=lesson.id,
        day_of_week=None,
        period_id=None,
        classroom_id=None,
        is_unplaced=True,
        unplaced_reason="testing",
    )
    client.session.add(slot)
    client.session.commit()
    client.session.refresh(slot)
    return slot


def test_parking_drop_without_classroom_uses_lesson_classroom(client):
    lesson = Lesson(
        subject_id=client.subj.id, teacher_id=client.teacher.id,
        class_id=client.cls.id, classroom_id=client.regular.id,
        periods_per_week=1, duration=1,
    )
    client.session.add(lesson)
    client.session.commit()
    client.session.refresh(lesson)

    slot = _make_unplaced_slot(client, lesson)

    res = client.put(
        f"/api/solver/solutions/{client.sol.id}/slots/{slot.id}",
        json={"day_of_week": 0, "period_id": client.period.id},
    )
    assert res.status_code == 200, res.text
    client.session.refresh(slot)
    assert slot.is_unplaced is False
    assert slot.classroom_id == client.regular.id


def test_parking_drop_falls_back_to_first_regular_room(client):
    """Lesson without a pinned classroom → backend picks the first
    regular room."""
    lesson = Lesson(
        subject_id=client.subj.id, teacher_id=client.teacher.id,
        class_id=client.cls.id, classroom_id=None,
        periods_per_week=1, duration=1,
    )
    client.session.add(lesson)
    client.session.commit()
    client.session.refresh(lesson)

    slot = _make_unplaced_slot(client, lesson)

    res = client.put(
        f"/api/solver/solutions/{client.sol.id}/slots/{slot.id}",
        json={"day_of_week": 0, "period_id": client.period.id},
    )
    assert res.status_code == 200, res.text
    client.session.refresh(slot)
    assert slot.classroom_id == client.regular.id


def test_parking_drop_for_lab_subject_picks_a_lab(client):
    """If the subject requires a lab, only lab rooms are acceptable."""
    lesson = Lesson(
        subject_id=client.lab_subj.id, teacher_id=client.teacher.id,
        class_id=client.cls.id, classroom_id=None,
        periods_per_week=1, duration=1,
    )
    client.session.add(lesson)
    client.session.commit()
    client.session.refresh(lesson)

    slot = _make_unplaced_slot(client, lesson)

    res = client.put(
        f"/api/solver/solutions/{client.sol.id}/slots/{slot.id}",
        json={"day_of_week": 0, "period_id": client.period.id},
    )
    assert res.status_code == 200, res.text
    client.session.refresh(slot)
    assert slot.classroom_id == client.lab.id


def test_parking_drop_skips_busy_room_if_alternatives_exist(client):
    """If the lesson has no pinned room and the auto-picked one is
    occupied (by a DIFFERENT teacher and class), the backend should
    retry with a different free room."""
    # Add a 2nd regular room
    other_room = Classroom(name="R2", short_name="R2", room_type="regular")
    other_teacher = Teacher(name="T2", short_name="T2", color="#000")
    other_class = SchoolClass(name="A2", short_name="A2")
    client.session.add_all([other_room, other_teacher, other_class])
    client.session.commit()
    for o in [other_room, other_teacher, other_class]:
        client.session.refresh(o)

    # Our parking-lot lesson — no pinned room
    lesson = Lesson(
        subject_id=client.subj.id, teacher_id=client.teacher.id,
        class_id=client.cls.id, classroom_id=None,
        periods_per_week=1, duration=1,
    )
    client.session.add(lesson)
    client.session.commit()
    client.session.refresh(lesson)

    # Blocker: different teacher + different class, occupies R1 at
    # the target slot
    blocker_lesson = Lesson(
        subject_id=client.subj.id, teacher_id=other_teacher.id,
        class_id=other_class.id, classroom_id=client.regular.id,
        periods_per_week=1, duration=1,
    )
    client.session.add(blocker_lesson)
    client.session.commit()
    client.session.refresh(blocker_lesson)

    client.session.add(
        TimetableSlot(
            solution_id=client.sol.id,
            lesson_id=blocker_lesson.id,
            day_of_week=0,
            period_id=client.period.id,
            classroom_id=client.regular.id,
            is_unplaced=False,
        )
    )
    client.session.commit()

    slot = _make_unplaced_slot(client, lesson)

    res = client.put(
        f"/api/solver/solutions/{client.sol.id}/slots/{slot.id}",
        json={"day_of_week": 0, "period_id": client.period.id},
    )
    assert res.status_code == 200, res.text
    client.session.refresh(slot)
    # R1 was busy → backend should have fallen back to R2
    assert slot.classroom_id == other_room.id


def test_grid_to_grid_drop_keeps_existing_classroom(client):
    """Moving a placed card preserves its classroom_id when the body
    doesn't specify one."""
    lesson = Lesson(
        subject_id=client.subj.id, teacher_id=client.teacher.id,
        class_id=client.cls.id, classroom_id=None,
        periods_per_week=1, duration=1,
    )
    client.session.add(lesson)
    client.session.commit()
    client.session.refresh(lesson)

    placed = TimetableSlot(
        solution_id=client.sol.id,
        lesson_id=lesson.id,
        day_of_week=0,
        period_id=client.period.id,
        classroom_id=client.lab.id,  # arbitrary
        is_unplaced=False,
    )
    client.session.add(placed)
    client.session.commit()
    client.session.refresh(placed)

    # Add a new period to drop into
    p2 = Period(
        name="2η", short_name="2", start_time="09:00",
        end_time="09:50", is_break=False, sort_order=2,
    )
    client.session.add(p2)
    client.session.commit()
    client.session.refresh(p2)

    res = client.put(
        f"/api/solver/solutions/{client.sol.id}/slots/{placed.id}",
        json={"day_of_week": 1, "period_id": p2.id},
    )
    assert res.status_code == 200, res.text
    client.session.refresh(placed)
    # Classroom should be preserved
    assert placed.classroom_id == client.lab.id
    assert placed.day_of_week == 1
    assert placed.period_id == p2.id


# ---------------------------------------------------------------------------
# H7 — shared-student conflict on manual move
# ---------------------------------------------------------------------------

def test_manual_move_rejects_shared_student_overlap(client):
    """Two different classes that share a student must not be placeable at
    the same (day, period) via drag-drop — even with different teacher and
    room (which would otherwise pass every other check). This is the
    manual-editor enforcement of solver hard-constraint H7."""
    from backend.models import Student, StudentClassEnrollment

    s = client.session

    # Second teacher / class / room so teacher & room checks don't fire.
    teacher2 = Teacher(name="T2", short_name="T2", color="#111")
    cls2 = SchoolClass(name="B1", short_name="B1")
    room2 = Classroom(name="R2", short_name="R2", room_type="regular")
    shared = Student(first_name="Κοινός", last_name="Μαθητής")
    s.add_all([teacher2, cls2, room2, shared])
    s.commit()
    for o in (teacher2, cls2, room2, shared):
        s.refresh(o)

    # The shared student belongs to BOTH classes.
    s.add_all([
        StudentClassEnrollment(student_id=shared.id, class_id=client.cls.id),
        StudentClassEnrollment(student_id=shared.id, class_id=cls2.id),
    ])

    lesson_a = Lesson(subject_id=client.subj.id, teacher_id=client.teacher.id,
                      class_id=client.cls.id, classroom_id=client.regular.id,
                      periods_per_week=1, duration=1)
    lesson_b = Lesson(subject_id=client.subj.id, teacher_id=teacher2.id,
                      class_id=cls2.id, classroom_id=room2.id,
                      periods_per_week=1, duration=1)
    s.add_all([lesson_a, lesson_b])
    s.commit()
    s.refresh(lesson_a)
    s.refresh(lesson_b)

    # Class B already placed at (day 0, period 1).
    placed_b = TimetableSlot(solution_id=client.sol.id, lesson_id=lesson_b.id,
                             day_of_week=0, period_id=client.period.id,
                             classroom_id=room2.id, is_unplaced=False)
    # Class A sits elsewhere; we try to drag it onto B's slot.
    slot_a = TimetableSlot(solution_id=client.sol.id, lesson_id=lesson_a.id,
                           day_of_week=2, period_id=client.period.id,
                           classroom_id=client.regular.id, is_unplaced=False)
    s.add_all([placed_b, slot_a])
    s.commit()
    s.refresh(slot_a)

    res = client.put(
        f"/api/solver/solutions/{client.sol.id}/slots/{slot_a.id}",
        json={"day_of_week": 0, "period_id": client.period.id},
    )
    assert res.status_code == 400
    assert "Κοινός μαθητής" in res.json()["detail"]


def test_manual_move_allows_unrelated_classes_same_slot(client):
    """Two classes with NO shared student CAN run at the same time — the
    H7 check must not over-block legitimate parallel classes."""
    from backend.models import StudentClassEnrollment, Student

    s = client.session
    teacher2 = Teacher(name="T3", short_name="T3", color="#222")
    cls2 = SchoolClass(name="C1", short_name="C1")
    room2 = Classroom(name="R3", short_name="R3", room_type="regular")
    st_a = Student(first_name="Α", last_name="Α")
    st_b = Student(first_name="Β", last_name="Β")
    s.add_all([teacher2, cls2, room2, st_a, st_b])
    s.commit()
    for o in (teacher2, cls2, room2, st_a, st_b):
        s.refresh(o)
    s.add_all([
        StudentClassEnrollment(student_id=st_a.id, class_id=client.cls.id),
        StudentClassEnrollment(student_id=st_b.id, class_id=cls2.id),
    ])

    lesson_a = Lesson(subject_id=client.subj.id, teacher_id=client.teacher.id,
                      class_id=client.cls.id, classroom_id=client.regular.id,
                      periods_per_week=1, duration=1)
    lesson_b = Lesson(subject_id=client.subj.id, teacher_id=teacher2.id,
                      class_id=cls2.id, classroom_id=room2.id,
                      periods_per_week=1, duration=1)
    s.add_all([lesson_a, lesson_b])
    s.commit()
    s.refresh(lesson_a)
    s.refresh(lesson_b)

    placed_b = TimetableSlot(solution_id=client.sol.id, lesson_id=lesson_b.id,
                             day_of_week=0, period_id=client.period.id,
                             classroom_id=room2.id, is_unplaced=False)
    slot_a = TimetableSlot(solution_id=client.sol.id, lesson_id=lesson_a.id,
                           day_of_week=2, period_id=client.period.id,
                           classroom_id=client.regular.id, is_unplaced=False)
    s.add_all([placed_b, slot_a])
    s.commit()
    s.refresh(slot_a)

    res = client.put(
        f"/api/solver/solutions/{client.sol.id}/slots/{slot_a.id}",
        json={"day_of_week": 0, "period_id": client.period.id},
    )
    assert res.status_code == 200, res.text
