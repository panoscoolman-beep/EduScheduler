"""Tests for the substitute teacher finder.

Scenarios covered:
  • zero affected slots when the teacher had nothing scheduled
  • candidate ranking (same-subject > same-class > otherwise)
  • candidates with conflicts (busy / unavailable) excluded
  • reschedule options skip the absence day, busy slots, and unavailable
    slots for the original teacher
  • absent-teacher-not-found surfaces as ValueError
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import (
    Classroom,
    Lesson,
    Period,
    SchoolClass,
    SchoolSettings,
    Subject,
    Teacher,
    TeacherAvailability,
    TimetableSlot,
    TimetableSolution,
)
from backend.services.substitute_finder import find_substitutes


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

    s.add(
        SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio")
    )

    math = Subject(name="Math", short_name="Μ", color="#000")
    physics = Subject(name="Physics", short_name="Φ", color="#000")
    teachers = [
        Teacher(name="Νικολάου", short_name="N", color="#000"),
        Teacher(name="Παπαδόπουλος", short_name="P", color="#000"),
        Teacher(name="Ιωαννίδης", short_name="I", color="#000"),
    ]
    classes = [
        SchoolClass(name="A1", short_name="A1"),
        SchoolClass(name="B1", short_name="B1"),
    ]
    rooms = [
        Classroom(name="Α101", short_name="Α101"),
        Classroom(name="Α102", short_name="Α102"),
    ]
    periods = [
        Period(
            name=f"{i}η",
            short_name=str(i),
            start_time=f"{7+i:02d}:00",
            end_time=f"{7+i:02d}:50",
            is_break=False,
            sort_order=i,
        )
        for i in range(1, 5)
    ]
    s.add_all([math, physics, *teachers, *classes, *rooms, *periods])
    s.commit()
    for o in [math, physics, *teachers, *classes, *rooms, *periods]:
        s.refresh(o)

    # Lessons:
    #   T0 teaches Math to A1 and Physics to B1
    #   T1 teaches Math to A1 and Math to B1   (same-subject candidate)
    #   T2 teaches no Math, no A1              (only "free time" candidate)
    s.add_all([
        Lesson(subject_id=math.id, teacher_id=teachers[0].id, class_id=classes[0].id, periods_per_week=2, duration=1),
        Lesson(subject_id=physics.id, teacher_id=teachers[0].id, class_id=classes[1].id, periods_per_week=1, duration=1),
        Lesson(subject_id=math.id, teacher_id=teachers[1].id, class_id=classes[0].id, periods_per_week=1, duration=1),
        Lesson(subject_id=math.id, teacher_id=teachers[1].id, class_id=classes[1].id, periods_per_week=1, duration=1),
    ])
    s.commit()

    sol = TimetableSolution(name="test-sol", status="feasible")
    s.add(sol)
    s.commit()
    s.refresh(sol)

    # Place T0's two A1-Math slots on Monday morning periods 1 and 2,
    # and T0's B1-Physics on Tuesday period 1.
    lessons = s.query(Lesson).all()
    a1_math = next(l for l in lessons if l.teacher_id == teachers[0].id and l.subject_id == math.id)
    b1_phys = next(l for l in lessons if l.teacher_id == teachers[0].id and l.subject_id == physics.id)

    s.add_all([
        TimetableSlot(
            solution_id=sol.id,
            lesson_id=a1_math.id,
            day_of_week=0,
            period_id=periods[0].id,
            classroom_id=rooms[0].id,
        ),
        TimetableSlot(
            solution_id=sol.id,
            lesson_id=a1_math.id,
            day_of_week=0,
            period_id=periods[1].id,
            classroom_id=rooms[0].id,
        ),
        TimetableSlot(
            solution_id=sol.id,
            lesson_id=b1_phys.id,
            day_of_week=1,
            period_id=periods[0].id,
            classroom_id=rooms[0].id,
        ),
    ])
    s.commit()

    s.test_solution = sol
    s.test_teachers = teachers
    s.test_classes = classes
    s.test_rooms = rooms
    s.test_periods = periods
    yield s
    s.close()


def test_no_slots_for_teacher_returns_empty(db):
    # T2 has no scheduled slots
    result = find_substitutes(db, db.test_solution.id, db.test_teachers[2].id, 0)
    assert result["affected_slots"] == []
    assert result["stats"] == {"affected_count": 0, "with_candidates": 0}


def test_unknown_teacher_raises(db):
    with pytest.raises(ValueError):
        find_substitutes(db, db.test_solution.id, 99999, 0)


def test_finds_t0_two_slots_on_monday(db):
    result = find_substitutes(db, db.test_solution.id, db.test_teachers[0].id, 0)
    assert result["stats"]["affected_count"] == 2
    assert result["stats"]["with_candidates"] == 2


def test_candidates_ranked_by_subject_then_class(db):
    """T1 teaches the same Math subject and the same A1 class → best
    score. T2 teaches neither → ranks below."""
    result = find_substitutes(db, db.test_solution.id, db.test_teachers[0].id, 0)
    slot_payload = result["affected_slots"][0]
    candidates = slot_payload["candidates"]

    assert len(candidates) == 2
    # T1 should rank higher than T2
    assert candidates[0]["teacher_id"] == db.test_teachers[1].id
    assert candidates[1]["teacher_id"] == db.test_teachers[2].id
    assert candidates[0]["score"] > candidates[1]["score"]


def test_candidate_excluded_if_already_busy(db):
    """If T1 is busy that exact slot, they can't be a substitute."""
    # Add a competing slot for T1 at Monday/period_1
    other_class = db.test_classes[1]
    t1_lesson = (
        db.query(Lesson)
        .filter(Lesson.teacher_id == db.test_teachers[1].id, Lesson.class_id == other_class.id)
        .first()
    )
    db.add(
        TimetableSlot(
            solution_id=db.test_solution.id,
            lesson_id=t1_lesson.id,
            day_of_week=0,
            period_id=db.test_periods[0].id,
            classroom_id=db.test_rooms[1].id,
        )
    )
    db.commit()

    result = find_substitutes(db, db.test_solution.id, db.test_teachers[0].id, 0)
    first_slot_candidates = result["affected_slots"][0]["candidates"]
    candidate_ids = {c["teacher_id"] for c in first_slot_candidates}
    # T1 conflicts at period 1 → only T2 should be a candidate
    assert db.test_teachers[1].id not in candidate_ids
    assert db.test_teachers[2].id in candidate_ids


def test_candidate_excluded_if_unavailable(db):
    """If T1 has flagged Monday/period_1 as unavailable, exclude them."""
    db.add(
        TeacherAvailability(
            teacher_id=db.test_teachers[1].id,
            day_of_week=0,
            period_id=db.test_periods[0].id,
            status="unavailable",
        )
    )
    db.commit()

    result = find_substitutes(db, db.test_solution.id, db.test_teachers[0].id, 0)
    first_slot_candidates = result["affected_slots"][0]["candidates"]
    assert all(c["teacher_id"] != db.test_teachers[1].id for c in first_slot_candidates)


def test_reschedule_options_skip_the_absence_day(db):
    result = find_substitutes(db, db.test_solution.id, db.test_teachers[0].id, 0)
    for slot in result["affected_slots"]:
        for opt in slot["reschedule_options"]:
            assert opt["day_of_week"] != 0


def test_reschedule_options_skip_busy_slots_for_original_teacher(db):
    """T0 is already teaching Tuesday/period_1 (B1 Physics), so that
    cell can't appear as a reschedule option for the Monday A1 slots."""
    result = find_substitutes(db, db.test_solution.id, db.test_teachers[0].id, 0)
    a1_slot = result["affected_slots"][0]
    busy_combo = (1, db.test_periods[0].id)
    for opt in a1_slot["reschedule_options"]:
        assert (opt["day_of_week"], opt["period_id"]) != busy_combo


def test_reschedule_options_skip_unavailable_slots_for_absent_teacher(db):
    db.add(
        TeacherAvailability(
            teacher_id=db.test_teachers[0].id,
            day_of_week=2,
            period_id=db.test_periods[0].id,
            status="unavailable",
        )
    )
    db.commit()

    result = find_substitutes(db, db.test_solution.id, db.test_teachers[0].id, 0)
    blocked = (2, db.test_periods[0].id)
    for slot in result["affected_slots"]:
        for opt in slot["reschedule_options"]:
            assert (opt["day_of_week"], opt["period_id"]) != blocked


def test_payload_shape_is_stable(db):
    result = find_substitutes(db, db.test_solution.id, db.test_teachers[0].id, 0)
    slot = result["affected_slots"][0]
    assert {"slot_id", "period_id", "lesson_id", "subject_name",
            "class_name", "candidates", "reschedule_options"}.issubset(slot)
    assert isinstance(slot["candidates"], list)
    assert isinstance(slot["reschedule_options"], list)
    if slot["candidates"]:
        c = slot["candidates"][0]
        assert {"teacher_id", "name", "score", "reasons"}.issubset(c)
