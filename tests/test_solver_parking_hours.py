"""Παλέτα μετά από permissive / «🧩 Γέμισε τα κενά»: ΜΙΑ κάρτα ανά ΩΡΑ (2/10/2026).

Πριν: ένα δίωρο που δεν χώρεσε γινόταν ΜΙΑ κάρτα στην Παλέτα (η 2η ώρα δεν
υπήρχε πουθενά) και ένα μάθημα 3 ωρών χωρίς εργαστήριο γινόταν επίσης μία·
το μήνυμα μετρούσε blocks αντί για ώρες. Τώρα γράφεται μία γραμμή ανά ώρα —
όπως τη μετράνε Παλέτα, parking_lot_sync και drag & drop.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, SchoolSettings, Subject, Teacher, TeacherAvailability,
    Term, TimetableSlot, TimetableSolution,
)
from backend.services.parking_lot_sync import sync_lesson_slot_count
from backend.services.solver_jobs import _persist_solver_result
from backend.solver.engine import SolverResult, TimetableSolver


def _env(n_periods=2, days=2, n_rooms=2):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(Term(id=1, name="Σενάριο", is_active=True))
    s.add(SchoolSettings(school_name="Κ", days_per_week=days))
    subj = Subject(name="Φυσική", short_name="ΦΥΣ", color="#000000")
    lab = Subject(name="Χημεία", short_name="ΧΗΜ", color="#000000", requires_special_room=True,
                  special_room_type="lab")
    t = Teacher(name="Τ", short_name="Τ", color="#000000")
    c = SchoolClass(name="Γ1", short_name="Γ1")
    rooms = [Classroom(name=f"Α{i}", short_name=f"Α{i}") for i in range(n_rooms)]
    periods = [Period(name=f"{i + 1}η", short_name=f"{i + 1}η", start_time=f"{14 + i:02d}:00",
                      end_time=f"{14 + i:02d}:50", is_break=False, sort_order=i + 1)
               for i in range(n_periods)]
    s.add_all([subj, lab, t, c, *rooms, *periods])
    s.commit()
    sol = TimetableSolution(name="Π", status="generating", term_id=1)
    s.add(sol)
    s.commit()
    return SimpleNamespace(s=s, subj=subj, lab=lab, t=t, c=c, periods=periods, sol=sol)


def _lesson(env, ppw, distribution=None, subject=None):
    les = Lesson(term_id=1, subject_id=(subject or env.subj).id, teacher_id=env.t.id,
                 class_id=env.c.id, periods_per_week=ppw, distribution=distribution)
    env.s.add(les)
    env.s.commit()
    return les


def _rows(env):
    env.s.expire_all()
    per: dict[int, list[int]] = {}
    for r in env.s.query(TimetableSlot).filter(TimetableSlot.solution_id == env.sol.id):
        per.setdefault(r.lesson_id, [0, 0])[1 if r.is_unplaced else 0] += 1
    return per


def test_unplaced_double_and_missing_lab_become_one_palette_card_per_hour():
    from backend.routers.solver import solver_status

    env = _env()
    for p in env.periods:   # ο καθηγητής μόνο την 1η μέρα → χωράει ΕΝΑ από τα δύο δίωρα
        env.s.add(TeacherAvailability(term_id=1, teacher_id=env.t.id, day_of_week=1,
                                      period_id=p.id, status="unavailable"))
    l1, l2 = _lesson(env, 2, "2"), _lesson(env, 2, "2")
    l3 = _lesson(env, 3, subject=env.lab)                        # δεν υπάρχει εργαστήριο
    res = TimetableSolver(env.s, max_time_seconds=10, mode="permissive", term_id=1).solve()
    assert res.message.endswith("τοποθετήθηκαν 2 ώρες, 5 ώρες έμειναν στο parking lot.")
    assert res.stats["total_hours_unplaced"] == 5
    _persist_solver_result(env.s, env.sol, res)
    rows = _rows(env)
    assert sorted(rows[l1.id] + rows[l2.id]) == [0, 0, 2, 2]     # ένα δίωρο μπήκε, το άλλο 2 κάρτες
    assert rows[l3.id] == [0, 3]                                 # πριν: [0, 1]
    assert solver_status(env.sol.id, db=env.s).unplaced_count == 5
    # Η Παλέτα δεν «λείπει» πια τίποτα — ο συγχρονισμός δεν έχει τι να προσθέσει.
    env.sol.status = "optimal"
    env.s.commit()
    for les in (l1, l2, l3):
        assert sync_lesson_slot_count(env.s, les.id)["synced"] == []


def test_block_longer_than_the_day_parks_exactly_the_missing_hours():
    env = _env(n_periods=6, days=5, n_rooms=1)
    les = _lesson(env, 9, "8,1")                                 # το «8» δεν χωράει ποτέ
    res = TimetableSolver(env.s, max_time_seconds=10, mode="permissive", term_id=1).solve()
    assert len(res.slots) == 1
    _persist_solver_result(env.s, env.sol, res)
    assert _rows(env)[les.id] == [1, 8]                          # 1 + 8 = 9 ώρες/εβδ.


def test_single_hour_blocks_are_counted_as_before():
    env = _env(n_periods=2, days=1, n_rooms=2)                   # ο καθηγητής χωράει 2 από τις 3
    les = _lesson(env, 3)
    res = TimetableSolver(env.s, max_time_seconds=10, mode="permissive", term_id=1).solve()
    assert res.message == "Βρέθηκε λύση — τοποθετήθηκαν 2 ώρες, 1 ώρες έμειναν στο parking lot."
    _persist_solver_result(env.s, env.sol, res)
    assert _rows(env)[les.id] == [2, 1]


def test_entries_without_hours_still_write_one_row():
    """Αποτέλεσμα χωρίς `hours` (π.χ. παλιός κώδικας) → μία γραμμή, όπως πριν."""
    env = _env()
    les = _lesson(env, 2)
    _persist_solver_result(env.s, env.sol, SolverResult(
        status="feasible", message="", unplaced=[{"lesson_id": les.id, "reason": "x"}]))
    assert _rows(env)[les.id] == [0, 1]
