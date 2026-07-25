"""Tests for the placement map (γκρίζα κελιά κατά το σύρσιμο).

build_placement_map πρέπει να συμφωνεί ΠΑΝΤΑ με τον enforcer του drop
(resolve_and_validate_target_room μέσω PUT slot): ό,τι δείχνει «ok»
δέχεται το PUT, ό,τι δείχνει μπλοκαρισμένο απορρίπτεται με 400. Τα
agreement tests στο τέλος κλειδώνουν αυτή τη συμφωνία.
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
from backend.services.slot_placement import build_placement_map


@pytest.fixture()
def env():
    """Sqlite app with 2 teaching periods, 5 days, 2 rooms (regular+lab)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    s.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))
    subj = Subject(name="Μαθηματικά", short_name="Μ", color="#000")
    lab_subj = Subject(
        name="Φυσική", short_name="Φ", color="#000",
        requires_special_room=True, special_room_type="lab",
    )
    t1 = Teacher(name="Τ1", short_name="Τ1", color="#000")
    t2 = Teacher(name="Τ2", short_name="Τ2", color="#000")
    c1 = SchoolClass(name="Α1", short_name="Α1")
    c2 = SchoolClass(name="Β2", short_name="Β2")
    regular = Classroom(name="R1", short_name="R1", room_type="regular")
    lab = Classroom(name="L1", short_name="L1", room_type="lab")
    p1 = Period(name="1η", short_name="1", start_time="08:00",
                end_time="08:50", is_break=False, sort_order=1)
    p2 = Period(name="2η", short_name="2", start_time="09:00",
                end_time="09:50", is_break=False, sort_order=2)
    br = Period(name="Δ", short_name="Δ", start_time="08:50",
                end_time="09:00", is_break=True, sort_order=10)
    s.add_all([subj, lab_subj, t1, t2, c1, c2, regular, lab, p1, p2, br])
    s.commit()
    for o in [subj, lab_subj, t1, t2, c1, c2, regular, lab, p1, p2]:
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
    client.subj, client.lab_subj = subj, lab_subj
    client.t1, client.t2 = t1, t2
    client.c1, client.c2 = c1, c2
    client.regular, client.lab = regular, lab
    client.p1, client.p2 = p1, p2
    yield client
    s.close()


def _lesson(env, teacher, cls, subject=None, room_id=None):
    lesson = Lesson(
        subject_id=(subject or env.subj).id,
        teacher_id=teacher.id,
        class_id=cls.id,
        classroom_id=room_id,
        periods_per_week=2,
        duration=1,
    )
    env.s.add(lesson)
    env.s.commit()
    env.s.refresh(lesson)
    return lesson


def _slot(env, lesson, day=None, period=None, room=None):
    placed = day is not None
    slot = TimetableSlot(
        solution_id=env.sol.id,
        lesson_id=lesson.id,
        day_of_week=day,
        period_id=period.id if period else None,
        classroom_id=room.id if room else None,
        is_unplaced=not placed,
        unplaced_reason=None if placed else "test",
    )
    env.s.add(slot)
    env.s.commit()
    env.s.refresh(slot)
    return slot


def _cell(map_, day, period):
    return next(
        c for c in map_["cells"] if c["day"] == day and c["period_id"] == period.id
    )


def test_shape_days_and_teaching_periods_only(env):
    slot = _slot(env, _lesson(env, env.t1, env.c1))
    m = build_placement_map(env.s, slot)
    assert m["days"] == 5
    assert len(m["cells"]) == 5 * 2  # break period excluded
    assert all(c["ok"] for c in m["cells"])  # empty grid — everything fits


def test_teacher_and_class_conflicts_block_cells(env):
    other = _lesson(env, env.t1, env.c2)              # same teacher, other class
    _slot(env, other, day=0, period=env.p1, room=env.lab)
    same_class = _lesson(env, env.t2, env.c1)         # other teacher, same class
    _slot(env, same_class, day=1, period=env.p2, room=env.lab)

    slot = _slot(env, _lesson(env, env.t1, env.c1))   # t1 + c1
    m = build_placement_map(env.s, slot)

    assert _cell(m, 0, env.p1)["ok"] is False         # teacher busy
    assert "καθηγητής" in _cell(m, 0, env.p1)["reason"].lower()
    assert _cell(m, 1, env.p2)["ok"] is False         # class busy
    assert "τμήμα" in _cell(m, 1, env.p2)["reason"].lower()
    assert _cell(m, 2, env.p1)["ok"] is True


def test_availability_blocks_and_is_term_scoped(env):
    env.s.add_all([
        TeacherAvailability(teacher_id=env.t1.id, day_of_week=0,
                            period_id=env.p1.id, status="unavailable"),
        # Κώλυμα σε ΑΛΛΟ σενάριο — δεν πρέπει να μετρήσει (λύση: term 1).
        TeacherAvailability(teacher_id=env.t1.id, day_of_week=1,
                            period_id=env.p1.id, status="unavailable", term_id=2),
    ])
    env.s.commit()

    slot = _slot(env, _lesson(env, env.t1, env.c1))
    m = build_placement_map(env.s, slot)
    assert _cell(m, 0, env.p1)["ok"] is False
    assert "κώλυμα" in _cell(m, 0, env.p1)["reason"].lower()
    assert _cell(m, 1, env.p1)["ok"] is True          # other-term ignored


def test_student_unavailability_and_h7_shared_student(env):
    st = Student(first_name="Νίκος", last_name="Π")
    env.s.add(st)
    env.s.commit()
    env.s.refresh(st)
    env.s.add_all([
        StudentClassEnrollment(student_id=st.id, class_id=env.c1.id),
        StudentClassEnrollment(student_id=st.id, class_id=env.c2.id),
        StudentAvailability(student_id=st.id, day_of_week=2,
                            period_id=env.p2.id, status="unavailable"),
    ])
    env.s.commit()

    # c2 (που μοιράζεται τον μαθητή) έχει μάθημα Δευτέρα p1 με ΑΛΛΟ καθηγητή
    other = _lesson(env, env.t2, env.c2)
    _slot(env, other, day=0, period=env.p1, room=env.lab)

    slot = _slot(env, _lesson(env, env.t1, env.c1))
    m = build_placement_map(env.s, slot)

    assert _cell(m, 0, env.p1)["ok"] is False          # H7
    assert "κοινός μαθητής" in _cell(m, 0, env.p1)["reason"].lower()
    assert _cell(m, 2, env.p2)["ok"] is False          # student unavailable
    assert "μαθητή" in _cell(m, 2, env.p2)["reason"].lower()


def test_room_exhaustion_blocks_cell(env):
    # Both rooms taken at (0, p1) by unrelated teachers/classes.
    l_a = _lesson(env, env.t2, env.c2)
    _slot(env, l_a, day=0, period=env.p1, room=env.regular)
    extra_teacher = Teacher(name="Τ3", short_name="Τ3", color="#000")
    extra_class = SchoolClass(name="Γ3", short_name="Γ3")
    env.s.add_all([extra_teacher, extra_class])
    env.s.commit()
    env.s.refresh(extra_teacher)
    env.s.refresh(extra_class)
    l_b = _lesson(env, extra_teacher, extra_class)
    _slot(env, l_b, day=0, period=env.p1, room=env.lab)

    slot = _slot(env, _lesson(env, env.t1, env.c1))
    m = build_placement_map(env.s, slot)
    assert _cell(m, 0, env.p1)["ok"] is False
    assert "αίθουσα" in _cell(m, 0, env.p1)["reason"].lower()
    assert _cell(m, 0, env.p2)["ok"] is True


def test_special_room_subject_needs_its_room_type_free(env):
    # Το lab είναι πιασμένο στο (0,p1) — για μάθημα Φυσικής (lab-only) το
    # κελί μπλοκάρει έστω κι αν η regular είναι ελεύθερη.
    occupier = _lesson(env, env.t2, env.c2)
    _slot(env, occupier, day=0, period=env.p1, room=env.lab)

    slot = _slot(env, _lesson(env, env.t1, env.c1, subject=env.lab_subj))
    m = build_placement_map(env.s, slot)
    assert _cell(m, 0, env.p1)["ok"] is False
    assert _cell(m, 0, env.p2)["ok"] is True


def test_placed_slot_does_not_conflict_with_itself(env):
    lesson = _lesson(env, env.t1, env.c1)
    slot = _slot(env, lesson, day=3, period=env.p1, room=env.regular)
    m = build_placement_map(env.s, slot)
    assert _cell(m, 3, env.p1)["ok"] is True


def test_endpoint_returns_map_and_404s(env):
    slot = _slot(env, _lesson(env, env.t1, env.c1))
    res = env.get(
        f"/api/solver/solutions/{env.sol.id}/slots/{slot.id}/placement-map"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["slot_id"] == slot.id
    assert len(body["cells"]) == 10
    assert env.get(
        f"/api/solver/solutions/{env.sol.id}/slots/9999/placement-map"
    ).status_code == 404


def test_agreement_with_drop_enforcer(env):
    """Κάθε μπλοκαρισμένο κελί του map απορρίπτεται από το PUT (400) και
    ένα ok κελί γίνεται δεκτό (200) — ο καθρέφτης δεν έχει ραγίσει."""
    st = Student(first_name="Κ", last_name="Λ")
    env.s.add(st)
    env.s.commit()
    env.s.refresh(st)
    env.s.add_all([
        StudentClassEnrollment(student_id=st.id, class_id=env.c1.id),
        StudentClassEnrollment(student_id=st.id, class_id=env.c2.id),
        TeacherAvailability(teacher_id=env.t1.id, day_of_week=4,
                            period_id=env.p2.id, status="unavailable"),
    ])
    env.s.commit()
    # Γέμισε το πλέγμα με λίγα εμπόδια κάθε είδους
    _slot(env, _lesson(env, env.t1, env.c2), day=0, period=env.p1, room=env.lab)      # teacher
    _slot(env, _lesson(env, env.t2, env.c1), day=1, period=env.p1, room=env.lab)      # class
    _slot(env, _lesson(env, env.t2, env.c2), day=2, period=env.p1, room=env.lab)      # H7

    slot = _slot(env, _lesson(env, env.t1, env.c1))
    m = build_placement_map(env.s, slot)

    blocked = [c for c in m["cells"] if not c["ok"]]
    ok_cells = [c for c in m["cells"] if c["ok"]]
    assert blocked and ok_cells  # το σενάριο έχει και τα δύο είδη

    for c in blocked:
        res = env.put(
            f"/api/solver/solutions/{env.sol.id}/slots/{slot.id}",
            json={"day_of_week": c["day"], "period_id": c["period_id"]},
        )
        assert res.status_code == 400, f"map said blocked but PUT passed: {c}"

    good = ok_cells[0]
    res = env.put(
        f"/api/solver/solutions/{env.sol.id}/slots/{slot.id}",
        json={"day_of_week": good["day"], "period_id": good["period_id"]},
    )
    assert res.status_code == 200, f"map said ok but PUT failed: {good}"
