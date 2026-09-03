"""Ονομαστικά conflicts στη χειροκίνητη τοποθέτηση.

Ο enforcer (resolve_and_validate_target_room) και το placement map πρέπει
να λένε ΠΟΙΟΣ/ΤΙ/ΠΟΥ μπλοκάρει («Ο καθηγητής Τ1 διδάσκει ήδη Μαθηματικά
στο Β2 (αίθ. L1) — Δευτέρα 1η (08:00)») και να δίνουν στο frontend το
slot που φταίει (blocking_slot_id) για highlight. Το `detail` μένει string
(συμβατότητα)· η δομή έρχεται στο κλειδί `conflict` μέσω του handler.
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
    StudentAvailability,
    StudentClassEnrollment,
    Subject,
    Teacher,
    TeacherAvailability,
    TimetableSlot,
    TimetableSolution,
)
from backend.routers import solver as solver_router
from backend.services import placement_conflicts as pc
from backend.services.placement_conflicts import install_conflict_handler
from backend.services.slot_placement import build_placement_map


def _make_env(with_handler: bool):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()

    s.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))
    subj = Subject(name="Μαθηματικά", short_name="Μ", color="#000")
    subj2 = Subject(name="Φυσική", short_name="Φ", color="#000")
    t1 = Teacher(name="Νικολάου", short_name="Ν", color="#000")
    t2 = Teacher(name="Παππά", short_name="Π", color="#000")
    c1 = SchoolClass(name="Α1", short_name="Α1")
    c2 = SchoolClass(name="Β2", short_name="Β2")
    r1 = Classroom(name="Αίθουσα 1", short_name="R1", room_type="regular")
    r2 = Classroom(name="Αίθουσα 2", short_name="R2", room_type="regular")
    p1 = Period(name="1η", short_name="1η", start_time="16:00",
                end_time="16:50", is_break=False, sort_order=1)
    p2 = Period(name="2η", short_name="2η", start_time="17:00",
                end_time="17:50", is_break=False, sort_order=2)
    s.add_all([subj, subj2, t1, t2, c1, c2, r1, r2, p1, p2])
    s.commit()
    for o in [subj, subj2, t1, t2, c1, c2, r1, r2, p1, p2]:
        s.refresh(o)
    sol = TimetableSolution(name="t", status="optimal")
    s.add(sol)
    s.commit()
    s.refresh(sol)

    app = FastAPI()
    if with_handler:
        install_conflict_handler(app)
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.s, client.sol = s, sol
    client.subj, client.subj2 = subj, subj2
    client.t1, client.t2, client.c1, client.c2 = t1, t2, c1, c2
    client.r1, client.r2, client.p1, client.p2 = r1, r2, p1, p2
    return client


@pytest.fixture()
def env():
    c = _make_env(with_handler=True)
    yield c
    c.s.close()


@pytest.fixture()
def bare_env():
    """Χωρίς handler — όπως τα παλιά tests: το detail παραμένει string."""
    c = _make_env(with_handler=False)
    yield c
    c.s.close()


def _lesson(env, teacher, cls, subject=None, room_id=None):
    lesson = Lesson(
        subject_id=(subject or env.subj).id, teacher_id=teacher.id,
        class_id=cls.id, classroom_id=room_id, periods_per_week=2, duration=1,
    )
    env.s.add(lesson)
    env.s.commit()
    env.s.refresh(lesson)
    return lesson


def _slot(env, lesson, day=None, period=None, room=None):
    slot = TimetableSlot(
        solution_id=env.sol.id, lesson_id=lesson.id,
        day_of_week=day, period_id=period.id if period else None,
        classroom_id=room.id if room else None,
        is_unplaced=day is None,
    )
    env.s.add(slot)
    env.s.commit()
    env.s.refresh(slot)
    return slot


def _move(env, slot, day, period, room=None):
    body = {"day_of_week": day, "period_id": period.id}
    if room is not None:
        body["classroom_id"] = room.id
    return env.put(f"/api/solver/solutions/{env.sol.id}/slots/{slot.id}", json=body)


def _student(env, first, last, *classes):
    st = Student(first_name=first, last_name=last)
    env.s.add(st)
    env.s.commit()
    env.s.refresh(st)
    for c in classes:
        env.s.add(StudentClassEnrollment(student_id=st.id, class_id=c.id))
    env.s.commit()
    return st


# ─── enforcer: ονομαστικά μηνύματα + δομή ──────────────────────────────


def test_teacher_conflict_names_who_what_where(env):
    other = _slot(env, _lesson(env, env.t1, env.c2, subject=env.subj2), 0, env.p1, env.r2)
    moving = _slot(env, _lesson(env, env.t1, env.c1))

    res = _move(env, moving, 0, env.p1)
    assert res.status_code == 400
    body = res.json()
    msg = body["detail"]
    assert isinstance(msg, str)
    for needle in ("Νικολάου", "διδάσκει ήδη", "Φυσική", "Β2", "Αίθουσα 2", "Δευτέρα", "1η (16:00)"):
        assert needle in msg, f"{needle!r} missing from {msg!r}"

    conflict = body["conflict"]
    assert conflict["code"] == pc.TEACHER_BUSY
    assert conflict["blocking_slot_id"] == other.id
    assert conflict["blocking"]["teacher"] == "Νικολάου"
    assert conflict["blocking"]["class_name"] == "Β2"
    assert conflict["day_of_week"] == 0 and conflict["period_id"] == env.p1.id
    assert conflict["moving_slot_id"] == moving.id


def test_class_conflict_names_subject_and_teacher(env):
    other = _slot(env, _lesson(env, env.t2, env.c1, subject=env.subj2), 1, env.p2, env.r1)
    moving = _slot(env, _lesson(env, env.t1, env.c1))

    res = _move(env, moving, 1, env.p2)
    assert res.status_code == 400
    msg = res.json()["detail"]
    for needle in ("τμήμα Α1", "Φυσική", "Παππά", "Τρίτη", "2η (17:00)"):
        assert needle in msg, msg
    assert res.json()["conflict"]["code"] == pc.CLASS_BUSY
    assert res.json()["conflict"]["blocking_slot_id"] == other.id


def test_explicit_room_conflict_names_room_and_occupant(env):
    other = _slot(env, _lesson(env, env.t2, env.c2), 2, env.p1, env.r1)
    moving = _slot(env, _lesson(env, env.t1, env.c1))

    res = _move(env, moving, 2, env.p1, room=env.r1)
    assert res.status_code == 400
    msg = res.json()["detail"]
    assert "Αίθουσα 1" in msg and "κατειλημμένη" in msg  # παλιό keyword διατηρείται
    assert "Β2" in msg and "Παππά" in msg and "Τετάρτη" in msg
    assert res.json()["conflict"]["code"] == pc.ROOM_BUSY
    assert res.json()["conflict"]["blocking_slot_id"] == other.id


def test_rooms_exhausted_lists_occupants(env):
    _slot(env, _lesson(env, env.t2, env.c2), 0, env.p2, env.r1)
    t3 = Teacher(name="Τ3", short_name="Τ3", color="#000")
    c3 = SchoolClass(name="Γ3", short_name="Γ3")
    env.s.add_all([t3, c3])
    env.s.commit()
    _slot(env, _lesson(env, t3, c3), 0, env.p2, env.r2)
    moving = _slot(env, _lesson(env, env.t1, env.c1))

    res = _move(env, moving, 0, env.p2)
    assert res.status_code == 400
    msg = res.json()["detail"]
    assert "Όλες οι αίθουσες" in msg
    assert "Αίθουσα 1: Β2" in msg and "Αίθουσα 2: Γ3" in msg
    assert res.json()["conflict"]["code"] == pc.ROOMS_EXHAUSTED


def test_teacher_unavailability_names_teacher(env):
    env.s.add(TeacherAvailability(teacher_id=env.t1.id, day_of_week=3,
                                  period_id=env.p1.id, status="unavailable"))
    env.s.commit()
    moving = _slot(env, _lesson(env, env.t1, env.c1))
    res = _move(env, moving, 3, env.p1)
    assert res.status_code == 400
    msg = res.json()["detail"]
    assert "Νικολάου" in msg and "κώλυμα" in msg and "Πέμπτη" in msg
    assert res.json()["conflict"]["code"] == pc.TEACHER_UNAVAILABLE
    assert res.json()["conflict"]["teacher_id"] == env.t1.id


def test_student_unavailability_names_students(env):
    a = _student(env, "Γιάννης", "Αλεξίου", env.c1)
    b = _student(env, "Μαρία", "Βασιλείου", env.c1)
    env.s.add_all([
        StudentAvailability(student_id=a.id, day_of_week=4, period_id=env.p1.id, status="unavailable"),
        StudentAvailability(student_id=b.id, day_of_week=4, period_id=env.p1.id, status="unavailable"),
    ])
    env.s.commit()
    moving = _slot(env, _lesson(env, env.t1, env.c1))
    res = _move(env, moving, 4, env.p1)
    assert res.status_code == 400
    msg = res.json()["detail"]
    assert "Οι μαθητές" in msg and "Αλεξίου Γιάννης" in msg and "Βασιλείου Μαρία" in msg
    assert "Παρασκευή" in msg
    assert sorted(res.json()["conflict"]["student_ids"]) == sorted([a.id, b.id])


def test_shared_student_names_student_and_other_class(env):
    st = _student(env, "Κώστας", "Δήμου", env.c1, env.c2)
    other = _slot(env, _lesson(env, env.t2, env.c2, subject=env.subj2), 0, env.p1, env.r2)
    moving = _slot(env, _lesson(env, env.t1, env.c1))

    res = _move(env, moving, 0, env.p1)
    assert res.status_code == 400
    msg = res.json()["detail"]
    assert msg.startswith("Κοινός μαθητής")  # παλιό keyword διατηρείται
    assert "Δήμου Κώστας" in msg and "Β2" in msg and "Φυσική" in msg and "Παππά" in msg
    conflict = res.json()["conflict"]
    assert conflict["code"] == pc.SHARED_STUDENT
    assert conflict["blocking_slot_id"] == other.id
    assert conflict["student_id"] == st.id


def test_detail_stays_a_string_without_handler(bare_env):
    env = bare_env
    _slot(env, _lesson(env, env.t1, env.c2), 0, env.p1, env.r2)
    moving = _slot(env, _lesson(env, env.t1, env.c1))
    res = _move(env, moving, 0, env.p1)
    assert res.status_code == 400
    assert isinstance(res.json()["detail"], str)
    assert "Νικολάου" in res.json()["detail"]
    assert "conflict" not in res.json()


# ─── swap: ποια κάρτα δεν χωράει ───────────────────────────────────────


def test_swap_failure_names_the_card_that_does_not_fit(env):
    # Α (t1, c1) στο (0,p1)· Β (t2, c2) στο (1,p1). Ο t1 έχει κώλυμα στο
    # (1,p1) → η κάρτα Α δεν χωράει στη θέση της Β.
    a = _slot(env, _lesson(env, env.t1, env.c1), 0, env.p1, env.r1)
    b = _slot(env, _lesson(env, env.t2, env.c2, subject=env.subj2), 1, env.p1, env.r2)
    env.s.add(TeacherAvailability(teacher_id=env.t1.id, day_of_week=1,
                                  period_id=env.p1.id, status="unavailable"))
    env.s.commit()

    res = env.post(f"/api/solver/solutions/{env.sol.id}/slots/swap",
                   json={"slot_a_id": a.id, "slot_b_id": b.id})
    assert res.status_code == 400
    msg = res.json()["detail"]
    assert msg.startswith("Η κάρτα «Μαθηματικά στο Α1")
    assert "Νικολάου" in msg and "κώλυμα" in msg and "Τρίτη" in msg
    assert res.json()["conflict"]["card_slot_id"] == a.id
    assert res.json()["conflict"]["code"] == pc.TEACHER_UNAVAILABLE


# ─── placement map: ονομαστικές αιτίες + short labels ──────────────────


def test_placement_map_cells_carry_names_short_label_and_blocking_slot(env):
    other = _slot(env, _lesson(env, env.t1, env.c2, subject=env.subj2), 0, env.p1, env.r2)
    same_class = _slot(env, _lesson(env, env.t2, env.c1, subject=env.subj2), 1, env.p2, env.r1)
    env.s.add(TeacherAvailability(teacher_id=env.t1.id, day_of_week=2,
                                  period_id=env.p1.id, status="unavailable"))
    st = _student(env, "Ελένη", "Ζήση", env.c1)
    env.s.add(StudentAvailability(student_id=st.id, day_of_week=3,
                                  period_id=env.p1.id, status="unavailable"))
    env.s.commit()
    moving = _slot(env, _lesson(env, env.t1, env.c1))

    m = build_placement_map(env.s, moving)
    by = {(c["day"], c["period_id"]): c for c in m["cells"]}

    c = by[(0, env.p1.id)]
    assert c["code"] == pc.TEACHER_BUSY and c["blocking_slot_id"] == other.id
    assert "Νικολάου" in c["reason"] and "Φυσική" in c["reason"] and "Β2" in c["reason"]
    assert c["short"] == "👤 Β2"

    c = by[(1, env.p2.id)]
    assert c["code"] == pc.CLASS_BUSY and c["blocking_slot_id"] == same_class.id
    assert "Α1" in c["reason"] and "Παππά" in c["reason"]
    assert c["short"].startswith("🏫")

    c = by[(2, env.p1.id)]
    assert c["code"] == pc.TEACHER_UNAVAILABLE and "Νικολάου" in c["reason"]
    assert c["short"] == "⛔ Ν"  # συντομογραφία, όπως οι κάρτες

    c = by[(3, env.p1.id)]
    assert c["code"] == pc.STUDENT_UNAVAILABLE and "Ζήση Ελένη" in c["reason"]
    assert c["short"].startswith("🎓 Ζήση")

    ok = by[(4, env.p2.id)]
    assert ok["ok"] and ok["code"] is None and ok["short"] is None and ok["blocking_slot_id"] is None


def test_placement_map_shared_student_and_room_exhaustion_named(env):
    st = _student(env, "Πέτρος", "Ηλία", env.c1, env.c2)
    other = _slot(env, _lesson(env, env.t2, env.c2, subject=env.subj2), 0, env.p1, env.r2)
    # (1,p1): και οι δύο αίθουσες πιασμένες από άσχετους
    t3 = Teacher(name="Τ3", short_name="Τ3", color="#000")
    c3 = SchoolClass(name="Γ3", short_name="Γ3")
    c4 = SchoolClass(name="Δ4", short_name="Δ4")
    env.s.add_all([t3, c3, c4])
    env.s.commit()
    _slot(env, _lesson(env, env.t2, c3), 1, env.p1, env.r1)
    _slot(env, _lesson(env, t3, c4), 1, env.p1, env.r2)
    moving = _slot(env, _lesson(env, env.t1, env.c1))

    m = build_placement_map(env.s, moving)
    by = {(c["day"], c["period_id"]): c for c in m["cells"]}

    c = by[(0, env.p1.id)]
    assert c["code"] == pc.SHARED_STUDENT and c["blocking_slot_id"] == other.id
    assert "Ηλία Πέτρος" in c["reason"] and "Β2" in c["reason"] and "Φυσική" in c["reason"]
    assert c["short"] == "👥 Β2"

    c = by[(1, env.p1.id)]
    assert c["code"] == pc.ROOMS_EXHAUSTED
    assert "Αίθουσα 1: Γ3" in c["reason"] and "Αίθουσα 2: Δ4" in c["reason"]
    assert c["short"] == "🚪 πλήρες"


def test_placement_map_endpoint_exposes_new_fields(env):
    _slot(env, _lesson(env, env.t1, env.c2), 0, env.p1, env.r2)
    moving = _slot(env, _lesson(env, env.t1, env.c1))
    res = env.get(f"/api/solver/solutions/{env.sol.id}/slots/{moving.id}/placement-map")
    assert res.status_code == 200
    cell = next(c for c in res.json()["cells"] if c["day"] == 0 and c["period_id"] == env.p1.id)
    assert set(cell) >= {"ok", "reason", "code", "short", "blocking_slot_id"}
    assert cell["ok"] is False and cell["code"] == pc.TEACHER_BUSY


# ─── helpers ───────────────────────────────────────────────────────────


def test_join_names_truncates():
    assert pc.join_names([]) == ""
    assert pc.join_names(["Α", "Β"]) == "Α, Β"
    assert pc.join_names(["Α", "Β", "Γ", "Δ", "Ε"]) == "Α, Β, Γ και 2 ακόμα"
    assert pc.join_names(["Α", "", None]) == "Α"


def test_prefixed_keeps_code_and_extra():
    exc = pc.PlacementConflict(pc.CLASS_BUSY, "μήνυμα", blocking_slot_id=7)
    p = exc.prefixed("Κάρτα Χ: ", card_slot_id=3)
    assert p.status_code == 400
    assert p.detail == "Κάρτα Χ: μήνυμα"
    assert p.conflict == {"code": pc.CLASS_BUSY, "message": "Κάρτα Χ: μήνυμα",
                          "blocking_slot_id": 7, "card_slot_id": 3}
