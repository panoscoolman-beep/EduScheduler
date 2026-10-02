"""🔓 Ξεκλείδωμα κάρτας που το κελί της «χάλασε» αργότερα (2/10/2026).

Πριν: το PUT του slot ξαναέλεγχε ΠΑΝΤΑ τη θέση, ακόμα κι όταν μόνο
ξεκλείδωνε. Αν μετά το 🔒 δηλωνόταν κώλυμα καθηγητή/μαθητή σε εκείνη την ώρα,
το 🔓 έδινε 400 — και η κάρτα δεν μετακινούνταν, δεν έβγαινε στην Παλέτα, δεν
ξεκλείδωνε ποτέ. Τώρα το σκέτο ξεκλείδωμα (ίδιο κελί, ίδια αίθουσα) δεν
ελέγχει θέση· κλείδωμα και κάθε μετακίνηση περνούν πάντα τον πλήρη έλεγχο.
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
    Classroom, Lesson, Period, SchoolClass, Student, StudentAvailability, StudentClassEnrollment,
    Subject, Teacher, TeacherAvailability, Term, TimetableSlot, TimetableSlotHistory,
    TimetableSolution,
)
from backend.routers import solver as solver_router


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    term = Term(name="Σενάριο", is_active=True)
    subj = Subject(name="Μαθηματικά", short_name="ΜΑΘ", color="#000000")
    t1 = Teacher(name="Τ1 Παπαδόπουλος", short_name="Τ1", color="#000000")
    t2 = Teacher(name="Τ2 Γεωργίου", short_name="Τ2", color="#000000")
    c1, c2 = SchoolClass(name="Α1", short_name="Α1"), SchoolClass(name="Β1", short_name="Β1")
    r1, r2 = Classroom(name="R1", short_name="R1"), Classroom(name="R2", short_name="R2")
    p = [Period(name=f"{i}η", short_name=f"{i}η", start_time=f"{13 + i:02d}:00",
                end_time=f"{14 + i:02d}:00", is_break=False, sort_order=i) for i in (1, 2)]
    s.add_all([term, subj, t1, t2, c1, c2, r1, r2, *p])
    s.commit()
    sol = TimetableSolution(name="Πρόγραμμα", status="optimal", term_id=term.id)
    l1 = Lesson(term_id=term.id, subject_id=subj.id, teacher_id=t1.id, class_id=c1.id, periods_per_week=1)
    l2 = Lesson(term_id=term.id, subject_id=subj.id, teacher_id=t2.id, class_id=c2.id, periods_per_week=1)
    s.add_all([sol, l1, l2])
    s.commit()
    slot = TimetableSlot(solution_id=sol.id, lesson_id=l1.id, day_of_week=0, period_id=p[0].id,
                         classroom_id=r1.id, is_unplaced=False, is_locked=True)
    other = TimetableSlot(solution_id=sol.id, lesson_id=l2.id, day_of_week=0, period_id=p[1].id,
                          classroom_id=r2.id, is_unplaced=False, is_locked=False)
    s.add_all([slot, other])
    s.commit()
    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.s, client.sol, client.term, client.p = s, sol, term, p
    client.t1, client.c1, client.r1, client.r2 = t1, c1, r1, r2
    client.slot, client.other = slot, other
    yield client
    s.close()


def _url(env, slot=None):
    return f"/api/solver/solutions/{env.sol.id}/slots/{(slot or env.slot).id}"


def _toggle(env, locked, slot=None, **over):
    """Ό,τι στέλνει το 🔒/🔓 του πλέγματος (TimetableGrid.toggleLock)."""
    s = slot or env.slot
    body = {"day_of_week": s.day_of_week, "period_id": s.period_id,
            "classroom_id": s.classroom_id, "is_locked": locked}
    body.update(over)
    return env.put(_url(env, s), json=body)


def _teacher_unavailable_now(env):
    env.s.add(TeacherAvailability(term_id=env.term.id, teacher_id=env.t1.id, day_of_week=0,
                                  period_id=env.p[0].id, status="unavailable"))
    env.s.commit()


def test_unlock_works_after_a_new_teacher_unavailability(env):
    _teacher_unavailable_now(env)
    res = _toggle(env, False)
    assert res.status_code == 200, res.text                       # πριν: 400 «έχει δηλώσει κώλυμα»
    env.s.expire_all()
    slot = env.s.get(TimetableSlot, env.slot.id)
    assert slot.is_locked is False
    assert (slot.day_of_week, slot.period_id, slot.classroom_id) == (0, env.p[0].id, env.r1.id)
    entry = env.s.query(TimetableSlotHistory).filter_by(slot_id=slot.id).one()
    assert entry.prev_is_locked is True and entry.new_is_locked is False
    # …και τώρα φεύγει κανονικά στην Παλέτα, και το undo το ξανακλειδώνει.
    assert env.post(f"/api/solver/solutions/{env.sol.id}/slots/{slot.id}/unplace").status_code == 200
    assert env.post(f"/api/solver/solutions/{env.sol.id}/undo").status_code == 200
    assert env.post(f"/api/solver/solutions/{env.sol.id}/undo").status_code == 200
    env.s.expire_all()
    assert env.s.get(TimetableSlot, env.slot.id).is_locked is True


def test_unlock_works_after_a_new_student_unavailability(env):
    st = Student(first_name="Άννα", last_name="Χ")
    env.s.add(st)
    env.s.commit()
    env.s.add(StudentClassEnrollment(student_id=st.id, class_id=env.c1.id))
    env.s.add(StudentAvailability(student_id=st.id, term_id=env.term.id, day_of_week=0,
                                  period_id=env.p[0].id, status="unavailable"))
    env.s.commit()
    res = _toggle(env, False, classroom_id=None)                  # χωρίς ρητή αίθουσα = ίδια
    assert res.status_code == 200, res.text
    assert res.json()["slot"]["is_locked"] is False and res.json()["slot"]["classroom_id"] == env.r1.id


def test_locking_an_invalid_cell_is_still_refused(env):
    _toggle(env, False)
    _teacher_unavailable_now(env)
    res = _toggle(env, True)
    assert res.status_code == 400 and "κώλυμα" in res.json()["detail"]


def test_unlock_with_a_move_or_room_change_is_still_validated(env):
    _teacher_unavailable_now(env)
    # μετακίνηση πάνω σε άλλη κάρτα της ίδιας αίθουσας → έλεγχος → 400
    moved = _toggle(env, False, period_id=env.p[1].id, classroom_id=env.r2.id)
    assert moved.status_code == 400
    # αλλαγή αίθουσας στο ίδιο κελί → πλήρης έλεγχος (κώλυμα) → 400
    room = _toggle(env, False, classroom_id=env.r2.id)
    assert room.status_code == 400 and "κώλυμα" in room.json()["detail"]
    env.s.expire_all()
    assert env.s.get(TimetableSlot, env.slot.id).is_locked is True
