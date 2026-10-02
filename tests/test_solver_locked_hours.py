"""Κλειδωμένες / ήδη τοποθετημένες ώρες σε Lock & Regenerate και «🧩 Γέμισε τα κενά».

* Κλειδωμένες ώρες που ΗΔΗ συμπίπτουν (π.χ. ο μαθητής γράφτηκε αργότερα και σε
  δεύτερο τμήμα της ίδιας ώρας) κρατιούνται όπως ήταν· πριν, όλο το
  «Γέμισε τα κενά» έβγαινε «αδύνατο» χωρίς λόγο και δεν τοποθετούσε τίποτα.
* «Γέμισε τα κενά»: κάθε παλιά ώρα κρατά τη ΔΙΚΗ της σήμανση 🔒 στο νέο
  πρόγραμμα· πριν, έβγαιναν ΟΛΕΣ κλειδωμένες.
* Μερικώς κλειδωμένη κάρτα «2,2»: το δίωρο που λείπει μπαίνει ως δίωρο· πριν,
  έσπαγε σε δύο μονόωρα (συχνά σε διαφορετικές μέρες).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Constraint, Lesson, Period, SchoolClass, SchoolSettings, Student,
    StudentClassEnrollment, Subject, Teacher, TeacherAvailability, Term, TimetableSlot,
    TimetableSolution,
)
from backend.solver.engine import TimetableSolver


def _env(n_periods=6, days=5, n_rooms=3):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine)
    s = maker()
    s.add(Term(id=1, name="Σενάριο", is_active=True))
    s.add(SchoolSettings(school_name="Κ", days_per_week=days))
    subj = Subject(name="Φυσική", short_name="ΦΥΣ", color="#000000")
    rooms = [Classroom(name=f"Α{i}", short_name=f"Α{i}") for i in range(n_rooms)]
    periods = [Period(name=f"{i + 1}η", short_name=f"{i + 1}η", start_time=f"{14 + i:02d}:00",
                      end_time=f"{14 + i:02d}:50", is_break=False, sort_order=i + 1)
               for i in range(n_periods)]
    s.add_all([subj, *rooms, *periods])
    s.commit()
    return SimpleNamespace(s=s, maker=maker, subj=subj, rooms=rooms, periods=periods)


def _card(env, name, ppw=1, distribution=None):
    t = Teacher(name=f"Κ{name}", short_name=f"Κ{name}", color="#000000")
    c = SchoolClass(name=name, short_name=name)
    env.s.add_all([t, c])
    env.s.commit()
    les = Lesson(term_id=1, subject_id=env.subj.id, teacher_id=t.id, class_id=c.id,
                 periods_per_week=ppw, distribution=distribution)
    env.s.add(les)
    env.s.commit()
    return les


def _enroll(env, student, *lessons):
    for les in lessons:
        env.s.add(StudentClassEnrollment(student_id=student.id, class_id=les.class_id))
    env.s.commit()


def _at(les, day, period, room):
    return {"lesson_id": les.id, "day_of_week": day, "period_id": period.id, "classroom_id": room.id}


def _keys(res):
    return {(x["lesson_id"], x["day_of_week"], x["period_id"], x["classroom_id"]) for x in res.slots}


def _key(entry):
    return (entry["lesson_id"], entry["day_of_week"], entry["period_id"], entry["classroom_id"])


# ───────────────────── κλειδωμένες ώρες που ήδη συμπίπτουν ─────────────────────

def _shared_student_overlap(env):
    a, b, cx = _card(env, "A"), _card(env, "B"), _card(env, "Cx")
    nikos = Student(first_name="Νίκος", last_name="Π")
    env.s.add(nikos)
    env.s.commit()
    _enroll(env, nikos, a, b)
    p0, (r0, r1, _) = env.periods[0], env.rooms
    return [_at(a, 0, p0, r0), _at(b, 0, p0, r1)], cx


@pytest.mark.parametrize("mode", ["permissive", "strict"])
def test_kept_hours_sharing_a_student_are_kept_and_the_rest_is_placed(mode):
    env = _env()
    locked, cx = _shared_student_overlap(env)
    res = TimetableSolver(env.s, max_time_seconds=10, mode=mode, locked_assignments=locked,
                          term_id=1).solve()
    assert res.status in ("optimal", "feasible"), res.message       # πριν: infeasible, 0 ώρες
    assert all(_key(e) in _keys(res) for e in locked)                # μένουν όπως ήταν
    assert any(x["lesson_id"] == cx.id for x in res.slots)           # το άσχετο μάθημα μπαίνει
    warning = " | ".join(res.stats["warnings"])
    assert "Π Νίκος" in warning and "Φυσική (A) + Φυσική (B)" in warning and "Δευτέρα" in warning


def test_nothing_else_enters_a_cell_where_kept_hours_already_overlap():
    """Η εξαίρεση αφορά ΜΟΝΟ τις κλειδωμένες: τρίτο μάθημα του ίδιου μαθητή δεν
    «χώνεται» στο ίδιο κελί — εδώ δεν έχει άλλη θέση, άρα μένει στην Παλέτα."""
    env = _env(n_periods=2, days=1)
    a, b, c = _card(env, "A"), _card(env, "B"), _card(env, "C")
    nikos = Student(first_name="Νίκος", last_name="Π")
    env.s.add(nikos)
    env.s.commit()
    _enroll(env, nikos, a, b, c)
    env.s.add(TeacherAvailability(term_id=1, teacher_id=c.teacher_id, day_of_week=0,
                                  period_id=env.periods[1].id, status="unavailable"))
    env.s.commit()
    locked = [_at(a, 0, env.periods[0], env.rooms[0]), _at(b, 0, env.periods[0], env.rooms[1])]
    res = TimetableSolver(env.s, max_time_seconds=10, mode="permissive", locked_assignments=locked,
                          term_id=1).solve()
    assert res.status in ("optimal", "feasible")
    assert not any(x["lesson_id"] == c.id for x in res.slots)
    assert [e["lesson_id"] for e in res.unplaced] == [c.id]


def test_teacher_double_booked_in_kept_hours_is_kept():
    env = _env()
    a, b = _card(env, "A"), _card(env, "B", ppw=2)
    b.teacher_id = a.teacher_id                                      # ίδιος καθηγητής
    env.s.commit()
    locked = [_at(a, 1, env.periods[2], env.rooms[0]), _at(b, 1, env.periods[2], env.rooms[1])]
    res = TimetableSolver(env.s, max_time_seconds=10, mode="strict", locked_assignments=locked,
                          term_id=1).solve()
    assert res.status in ("optimal", "feasible"), res.message
    assert all(_key(e) in _keys(res) for e in locked)
    b_hours = [x for x in res.slots if x["lesson_id"] == b.id]
    assert len(b_hours) == 2
    assert any("ίδιος καθηγητής" in w for w in res.stats["warnings"])


def test_without_overlap_the_model_is_exactly_as_before(monkeypatch):
    """Με ≤1 κλειδωμένη ανά κελί, το «το πολύ ένα» χτίζεται όπως πάντα."""
    def proto(old_style: bool):
        env = _env()
        a, b = _card(env, "A", ppw=2), _card(env, "B", ppw=2)
        nikos = Student(first_name="Νίκος", last_name="Π")
        env.s.add(nikos)
        env.s.commit()
        _enroll(env, nikos, a, b)
        locked = [_at(a, 0, env.periods[0], env.rooms[0]), _at(b, 0, env.periods[1], env.rooms[1])]
        if old_style:
            monkeypatch.setattr(
                TimetableSolver, "_at_most_one",
                lambda self, keys, *_: self.model.Add(sum(self.x[k] for k in keys) <= 1))
        solver = TimetableSolver(env.s, max_time_seconds=10, mode="permissive",
                                 locked_assignments=locked, term_id=1)
        assert solver.solve().status in ("optimal", "feasible")
        monkeypatch.undo()
        return solver.model.Proto().SerializeToString()

    assert proto(False) == proto(True)


# ───────────────────── «🧩 Γέμισε τα κενά»: σήμανση 🔒 ανά ώρα ─────────────────────

@pytest.fixture()
def api(monkeypatch):
    from backend.routers import solver as solver_router
    from backend.services import solver_jobs

    env = _env(n_periods=2, n_rooms=1)
    les = _card(env, "Β2", ppw=3)
    src = TimetableSolution(name="ΧΕΙΜΕΡΙΝΟ", status="optimal", term_id=1)
    env.s.add(src)
    env.s.commit()
    p0, room = env.periods[0], env.rooms[0]
    env.s.add_all([
        TimetableSlot(solution_id=src.id, lesson_id=les.id, day_of_week=0, period_id=p0.id,
                      classroom_id=room.id, is_unplaced=False, is_locked=True),
        TimetableSlot(solution_id=src.id, lesson_id=les.id, day_of_week=1, period_id=p0.id,
                      classroom_id=room.id, is_unplaced=False, is_locked=False),
        TimetableSlot(solution_id=src.id, lesson_id=les.id, is_unplaced=True),
    ])
    env.s.commit()
    monkeypatch.setattr(solver_jobs, "SessionLocal", env.maker)      # ο solver τρέχει «στ' αλήθεια»
    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        yield env.s

    app.dependency_overrides[get_db] = override_db
    env.client, env.src, env.lesson = TestClient(app), src, les
    yield env
    env.s.close()


def _new_slots(env, solution_id):
    env.s.expire_all()
    return sorted((s.day_of_week if s.day_of_week is not None else -1, s.is_locked, s.is_unplaced)
                  for s in env.s.query(TimetableSlot).filter(TimetableSlot.solution_id == solution_id))


def test_fill_gaps_keeps_each_hours_own_lock_flag(api):
    res = api.client.post(f"/api/solver/regenerate/{api.src.id}",
                          json={"name": "Συμπλήρωση", "lock_all_placed": True, "max_time_seconds": 10})
    assert res.status_code == 200, res.text
    new_id = res.json()["solution_id"]
    assert api.s.get(TimetableSolution, new_id).status in ("optimal", "feasible")
    slots = _new_slots(api, new_id)
    # Δευ: 🔒 (ήταν 🔒) · Τρί: ελεύθερη (ήταν ελεύθερη — πριν έβγαινε 🔒) · νέα ώρα: ελεύθερη
    assert (0, True, False) in slots and (1, False, False) in slots
    assert sum(1 for _, locked, unplaced in slots if not unplaced) == 3
    assert sum(1 for _, locked, _ in slots if locked) == 1
    assert _new_slots(api, api.src.id) == [(-1, False, True), (0, True, False), (1, False, False)]


def test_plain_lock_and_regenerate_still_locks_the_kept_hours(api):
    res = api.client.post(f"/api/solver/regenerate/{api.src.id}",
                          json={"name": "v2", "mode": "permissive", "max_time_seconds": 10})
    assert res.status_code == 200, res.text
    slots = _new_slots(api, res.json()["solution_id"])
    assert (0, True, False) in slots                                  # το 🔒 μένει 🔒
    assert sum(1 for _, locked, _ in slots if locked) == 1


def test_persist_without_a_lock_flag_keeps_the_old_meaning():
    """Εγγραφές χωρίς `is_locked` (π.χ. από παλιό κώδικα) = κλειδωμένες, όπως πριν."""
    from backend.services.solver_jobs import _persist_solver_result
    from backend.solver.engine import SolverResult

    env = _env(n_periods=1, n_rooms=1)
    les = _card(env, "Α")
    sol = TimetableSolution(name="Ν", status="generating", term_id=1)
    env.s.add(sol)
    env.s.commit()
    cell = _at(les, 0, env.periods[0], env.rooms[0])
    _persist_solver_result(env.s, sol, SolverResult(status="optimal", message="", slots=[cell]), [cell])
    assert env.s.query(TimetableSlot).filter(TimetableSlot.solution_id == sol.id).one().is_locked


# ───────────────────── μερικώς κλειδωμένη κάρτα με δίωρα ─────────────────────

def _soft(env, rtype, weight):
    env.s.add(Constraint(name=rtype, constraint_type="soft", category="general", weight=weight,
                         is_active=True, rule=json.dumps({"type": rtype})))
    env.s.commit()


def test_partially_locked_2_2_keeps_the_missing_double_together():
    env = _env(n_rooms=1)
    les = _card(env, "Γ1", ppw=4, distribution="2,2")
    for rtype, w in (("min_teacher_gaps", 70), ("min_class_gaps", 80),
                     ("subject_distribution", 60), ("class_compactness", 50)):
        _soft(env, rtype, w)
    locked = [_at(les, 0, env.periods[i], env.rooms[0]) for i in (0, 1)]
    res = TimetableSolver(env.s, max_time_seconds=10, mode="permissive", locked_assignments=locked,
                          term_id=1).solve()
    assert res.status in ("optimal", "feasible")
    idx = {p.id: i for i, p in enumerate(env.periods)}
    rest = sorted((x["day_of_week"], idx[x["period_id"]]) for x in res.slots
                  if _key(x) not in {_key(e) for e in locked})
    assert len(rest) == 2
    (d1, i1), (d2, i2) = rest
    assert d1 == d2 != 0 and i2 == i1 + 1                             # δίωρο, άλλη μέρα


def test_partially_locked_2_2_without_room_for_a_double():
    """Δεύτερο δίωρο δεν χωράει πουθενά: strict → αδύνατο (πριν: «βέλτιστη» με
    δύο σκόρπια μονόωρα)· permissive → οι 2 ώρες στην Παλέτα."""
    env = _env(n_periods=5, n_rooms=1)
    les = _card(env, "Γ1", ppw=4, distribution="2,2")
    free = {(0, 0), (0, 1), (4, 0), (4, 2)}                           # Δευ 1η-2η, Παρ 1η & 3η
    for d in range(5):
        for i, p in enumerate(env.periods):
            if (d, i) not in free:
                env.s.add(TeacherAvailability(term_id=1, teacher_id=les.teacher_id, day_of_week=d,
                                              period_id=p.id, status="unavailable"))
    env.s.commit()
    locked = [_at(les, 0, env.periods[i], env.rooms[0]) for i in (0, 1)]
    strict = TimetableSolver(env.s, max_time_seconds=10, mode="strict", locked_assignments=locked,
                             term_id=1).solve()
    assert strict.status == "infeasible"
    assert "Φυσική (Γ1) → «2»" in strict.message and "permissive" in strict.message
    loose = TimetableSolver(env.s, max_time_seconds=10, mode="permissive", locked_assignments=locked,
                            term_id=1).solve()
    assert loose.status in ("optimal", "feasible")
    assert _keys(loose) == {_key(e) for e in locked}
    assert sum(e["hours"] for e in loose.unplaced) == 2


def test_locks_that_do_not_match_the_blocks_keep_the_old_behaviour(monkeypatch):
    """Μία μόνο κλειδωμένη ώρα ενός «2,2» (δεν αντιστοιχεί σε block): όπως πριν,
    όλα μονόωρα — ίδιο μοντέλο με/χωρίς την αντιστοίχιση."""
    def proto(disable_matching: bool):
        env = _env(n_rooms=1)
        les = _card(env, "Γ1", ppw=4, distribution="2,2")
        _soft(env, "min_teacher_gaps", 70)
        if disable_matching:
            monkeypatch.setattr(TimetableSolver, "_match_locked_to_blocks", lambda self, _m: None)
        solver = TimetableSolver(env.s, max_time_seconds=10, mode="permissive",
                                 locked_assignments=[_at(les, 2, env.periods[3], env.rooms[0])],
                                 term_id=1)
        res = solver.solve()
        monkeypatch.undo()
        assert res.status in ("optimal", "feasible") and len(res.slots) == 4
        return solver.model.Proto().SerializeToString()

    assert proto(False) == proto(True)
