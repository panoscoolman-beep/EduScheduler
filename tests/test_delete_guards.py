"""Φραγή καταστροφικών διαγραφών (καθηγητής, μάθημα, τμήμα, αίθουσα).

Χωρίς force: 409 + πλήθη, τίποτα δεν σβήνεται. Με force: ό,τι ίσχυε πριν —
εκτός από την αίθουσα, όπου οι τοποθετημένες ώρες γυρίζουν στην Παλέτα
αντί να μείνουν «τοποθετημένες χωρίς αίθουσα».
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
    Classroom, Lesson, Period, SchoolClass, Student, StudentClassEnrollment,
    Subject, Teacher, TimetableSlot, TimetableSolution,
)
from backend.routers import classes as classes_router
from backend.routers import classrooms as classrooms_router
from backend.routers import subjects as subjects_router
from backend.routers import teachers as teachers_router


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()

    subj = Subject(name="Άλγεβρα", short_name="ΑΛΓ", color="#000")
    teacher = Teacher(name="Καθ <b>Α</b>", short_name="ΚΑ", color="#000")
    cls = SchoolClass(name="Β2", short_name="Β2")
    room = Classroom(name="Αίθ 1", short_name="Α1", room_type="regular")
    period = Period(name="1η", short_name="1", start_time="14:00",
                    end_time="15:00", is_break=False, sort_order=1)
    student = Student(first_name="Νίκος", last_name="Π")
    s.add_all([subj, teacher, cls, room, period, student])
    s.commit()
    for o in (subj, teacher, cls, room, period, student):
        s.refresh(o)
    s.add(StudentClassEnrollment(student_id=student.id, class_id=cls.id))
    sol = TimetableSolution(name="ΧΕΙΜΕΡΙΝΟ", status="optimal")
    s.add(sol)
    s.commit()
    s.refresh(sol)
    lesson = Lesson(subject_id=subj.id, teacher_id=teacher.id, class_id=cls.id,
                    periods_per_week=3, classroom_id=room.id)
    s.add(lesson)
    s.commit()
    s.refresh(lesson)
    for day in (0, 1):
        s.add(TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=day,
                            period_id=period.id, classroom_id=room.id, is_unplaced=False,
                            is_locked=(day == 0)))
    s.add(TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, is_unplaced=True))
    s.commit()

    app = FastAPI()
    app.include_router(teachers_router.router, prefix="/api/teachers")
    app.include_router(subjects_router.router, prefix="/api/subjects")
    app.include_router(classes_router.router, prefix="/api/classes")
    app.include_router(classrooms_router.router, prefix="/api/classrooms")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session = s
    c.ids = {"subject": subj.id, "teacher": teacher.id, "class": cls.id, "room": room.id,
             "lesson": lesson.id, "student": student.id, "solution": sol.id}
    yield c
    s.close()


def _slots(c):
    return c.session.query(TimetableSlot).all()


def _lesson_exists(c):
    return c.session.query(Lesson).filter(Lesson.id == c.ids["lesson"]).first() is not None


@pytest.mark.parametrize("path, key, code, phrase", [
    ("teachers", "teacher", "teacher_in_use", "Ο καθηγητής «Καθ <b>Α</b>» έχει 1 μαθήματα-κάρτες"),
    ("subjects", "subject", "subject_in_use", "Το μάθημα «Άλγεβρα» χρησιμοποιείται σε 1 μαθήματα-κάρτες"),
    ("classes", "class", "class_in_use", "Το τμήμα «Β2» έχει 1 μαθήματα-κάρτες"),
])
def test_delete_in_use_needs_force_and_changes_nothing(env, path, key, code, phrase):
    res = env.delete(f"/api/{path}/{env.ids[key]}")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == code and detail["requires_force"] is True
    assert phrase in detail["message"]
    assert "2 τοποθετημένες ώρες σε 1 πρόγραμμα(τα)" in detail["message"]
    assert detail["usage"]["lessons"] == 1 and detail["usage"]["placed"] == 2
    assert _lesson_exists(env) and len(_slots(env)) == 3          # τίποτα δεν σβήστηκε


@pytest.mark.parametrize("path, key", [("teachers", "teacher"), ("subjects", "subject"), ("classes", "class")])
def test_delete_with_force_removes_lessons_and_their_hours(env, path, key):
    assert env.delete(f"/api/{path}/{env.ids[key]}?force=true").status_code == 204
    assert not _lesson_exists(env)
    assert _slots(env) == []


def test_class_message_mentions_students_and_students_survive(env):
    detail = env.delete(f"/api/classes/{env.ids['class']}").json()["detail"]
    assert detail["usage"]["students"] == 1
    assert "1 εγγεγραμμένους μαθητές" in detail["message"]
    env.delete(f"/api/classes/{env.ids['class']}?force=true")
    assert env.session.query(Student).filter(Student.id == env.ids["student"]).first() is not None


def test_unused_entities_delete_without_force(env):
    extra = Teacher(name="Κανένα μάθημα", short_name="ΚΜ", color="#000")
    env.session.add(extra)
    env.session.commit()
    assert env.delete(f"/api/teachers/{extra.id}").status_code == 204
    assert env.delete("/api/teachers/999").status_code == 404


def test_classroom_in_use_needs_force(env):
    res = env.delete(f"/api/classrooms/{env.ids['room']}")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "classroom_in_use" and detail["requires_force"] is True
    assert "2 ώρες σε 1 πρόγραμμα(τα)" in detail["message"]
    assert "δεν χάνεται καμία ώρα" in detail["message"]
    assert detail["usage"]["preferred_by_lessons"] == 1
    assert sum(1 for s in _slots(env) if not s.is_unplaced) == 2      # ανέγγιχτο


def test_classroom_force_sends_its_hours_back_to_the_palette(env):
    assert env.delete(f"/api/classrooms/{env.ids['room']}?force=true").status_code == 204
    assert env.session.query(Classroom).filter(Classroom.id == env.ids["room"]).first() is None
    slots = _slots(env)
    assert len(slots) == 3 and all(s.is_unplaced for s in slots)       # καμία ώρα δεν χάθηκε
    moved = [s for s in slots if s.unplaced_reason and "Αίθ 1" in s.unplaced_reason]
    assert len(moved) == 2
    assert all(s.day_of_week is None and s.period_id is None and s.classroom_id is None
               and not s.is_locked for s in moved)
    assert _lesson_exists(env)
