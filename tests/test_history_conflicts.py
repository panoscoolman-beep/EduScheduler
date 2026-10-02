"""↩️/↪ Αναίρεση & επανάληψη που ΔΕΝ δημιουργούν διπλοκρατήσεις ούτε 500.

Πριν (έως 1/10/2026) το undo/redo έγραφε τυφλά την παλιά θέση:
  • swap + ένα Ctrl+Z → δύο κάρτες στο ίδιο κελί (G3-01)·
  • αλλαγή καθηγητή με force + Ctrl+Z → ο καθηγητής σε δύο τάξεις (G3-02)·
  • μετατόπιση ωρών + Ctrl+Z → η κάρτα στην ώρα ΠΡΙΝ τη μετατόπιση / σύγκρουση (G3-06)·
  • διαγραμμένη αίθουσα/ώρα στο ιστορικό → 500 σε κάθε Ctrl+Z (G3-07 / G2-12).
SQLite με PRAGMA foreign_keys=ON, ώστε τα FK να συμπεριφέρονται όπως στο Postgres.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, SchoolSettings, Student, StudentClassEnrollment,
    Subject, Teacher, Term, TimetableSlot, TimetableSlotHistory, TimetableSolution,
)
from backend.routers import classrooms as classrooms_router
from backend.routers import lessons as lessons_router
from backend.routers import periods as periods_router
from backend.routers import solver as solver_router
from backend.routers import terms as terms_router
from backend.services import slot_history


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    term = Term(name="Σενάριο", is_active=True)
    s.add_all([term, SchoolSettings(school_name="Κ", days_per_week=5,
                                    institution_type="frontistirio")])
    s.commit()
    subj_m = Subject(name="ΜΑΘΗΜΑΤΙΚΑ", short_name="ΜΑΘ", color="#112233")
    subj_f = Subject(name="ΦΥΣΙΚΗ", short_name="ΦΥΣ", color="#445566")
    t1 = Teacher(name="Τ1", short_name="Τ1", color="#000000")
    t2 = Teacher(name="Τ2", short_name="Τ2", color="#000000")
    c1 = SchoolClass(name="Α1", short_name="Α1")
    c2 = SchoolClass(name="Β2", short_name="Β2")
    rooms = [Classroom(name=f"R{i}", short_name=f"R{i}", room_type="regular") for i in (1, 2, 3)]
    periods = [Period(name=f"{i}η Ώρα", short_name=f"{i}η", start_time=f"{13 + i:02d}:00",
                      end_time=f"{14 + i:02d}:00", is_break=False, sort_order=i) for i in range(1, 6)]
    s.add_all([subj_m, subj_f, t1, t2, c1, c2, *rooms, *periods])
    s.commit()
    sol = TimetableSolution(name="Πρόγραμμα", status="optimal", term_id=term.id)
    s.add(sol)
    s.commit()

    app = FastAPI()
    for prefix, mod in (("/api/solver", solver_router), ("/api/lessons", lessons_router),
                        ("/api/terms", terms_router), ("/api/periods", periods_router),
                        ("/api/classrooms", classrooms_router)):
        app.include_router(mod.router, prefix=prefix)

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app, raise_server_exceptions=False)
    c.s, c.sol, c.term = s, sol, term
    c.subj_m, c.subj_f, c.t1, c.t2, c.c1, c.c2 = subj_m, subj_f, t1, t2, c1, c2
    c.r1, c.r2, c.r3 = rooms
    c.p = periods
    yield c
    s.close()


def _lesson(env, teacher, cls, subj):
    obj = Lesson(subject_id=subj.id, teacher_id=teacher.id, class_id=cls.id, periods_per_week=1,
                 duration=1, term_id=env.term.id)
    env.s.add(obj)
    env.s.commit()
    return obj


def _slot(env, lesson, day, period, room, locked=False):
    obj = TimetableSlot(solution_id=env.sol.id, lesson_id=lesson.id, day_of_week=day,
                        period_id=period.id, classroom_id=room.id, is_unplaced=False,
                        is_locked=locked)
    env.s.add(obj)
    env.s.commit()
    return obj


def _clashes(env):
    """Σκληρές συγκρούσεις (καθηγητής / τμήμα / αίθουσα) μεταξύ τοποθετημένων ωρών."""
    env.s.expire_all()
    rows = (env.s.query(TimetableSlot, Lesson).join(Lesson, Lesson.id == TimetableSlot.lesson_id)
            .filter(TimetableSlot.solution_id == env.sol.id,
                    TimetableSlot.is_unplaced == False).all())  # noqa: E712
    seen, out = {}, []
    for slot, lesson in rows:
        for kind, key in (("teacher", lesson.teacher_id), ("class", lesson.class_id),
                          ("room", slot.classroom_id)):
            k = (kind, key, slot.day_of_week, slot.period_id)
            if k in seen:
                out.append(k)
            seen[k] = slot.id
    return out


def _pos(env, slot):
    env.s.expire_all()
    s = env.s.get(TimetableSlot, slot.id)
    return (s.day_of_week, s.period_id, s.classroom_id, s.is_unplaced)


def _summary(env):
    return env.get(f"/api/solver/solutions/{env.sol.id}/history-summary").json()


def _undo(env):
    return env.post(f"/api/solver/solutions/{env.sol.id}/undo")


def _redo(env):
    return env.post(f"/api/solver/solutions/{env.sol.id}/redo")


def _move(env, slot, day, period, room=None):
    body = {"day_of_week": day, "period_id": period.id}
    if room is not None:
        body["classroom_id"] = room.id
    res = env.put(f"/api/solver/solutions/{env.sol.id}/slots/{slot.id}", json=body)
    assert res.status_code == 200, res.text
    return res


# ─── G3-01: swap = μία αναίρεση όταν το μισό θα έφερνε δύο κάρτες στο ίδιο κελί ──

def test_one_undo_reverts_a_same_class_swap_without_double_booking(env):
    a = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[0], env.r1)
    b = _slot(env, _lesson(env, env.t2, env.c1, env.subj_f), 0, env.p[1], env.r1)
    assert env.post(f"/api/solver/solutions/{env.sol.id}/slots/swap",
                    json={"slot_a_id": a.id, "slot_b_id": b.id}).status_code == 200

    res = _undo(env)
    assert res.status_code == 200, res.text
    assert _clashes(env) == []
    assert _pos(env, a) == (0, env.p[0].id, env.r1.id, False)
    assert _pos(env, b) == (0, env.p[1].id, env.r1.id, False)
    assert _summary(env)["can_undo"] == 0 and _summary(env)["can_redo"] == 2

    # ↪ ξανακάνει ολόκληρο το swap — πάλι χωρίς ενδιάμεση διπλοκράτηση.
    assert _redo(env).status_code == 200
    assert _clashes(env) == []
    assert _pos(env, a)[:2] == (0, env.p[1].id) and _pos(env, b)[:2] == (0, env.p[0].id)
    assert _summary(env)["can_undo"] == 2


def test_one_undo_reverts_a_same_teacher_swap(env):
    a = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 1, env.p[0], env.r1)
    b = _slot(env, _lesson(env, env.t1, env.c2, env.subj_f), 2, env.p[2], env.r2)
    assert env.post(f"/api/solver/solutions/{env.sol.id}/slots/swap",
                    json={"slot_a_id": a.id, "slot_b_id": b.id}).status_code == 200
    assert _undo(env).status_code == 200
    assert _clashes(env) == []
    assert _pos(env, a)[:2] == (1, env.p[0].id) and _pos(env, b)[:2] == (2, env.p[2].id)


def test_undo_to_on_one_half_of_a_swap_reverts_the_whole_swap(env):
    a = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[0], env.r1)
    b = _slot(env, _lesson(env, env.t2, env.c1, env.subj_f), 0, env.p[1], env.r1)
    env.post(f"/api/solver/solutions/{env.sol.id}/slots/swap",
             json={"slot_a_id": a.id, "slot_b_id": b.id})
    newest = env.s.query(TimetableSlotHistory).order_by(TimetableSlotHistory.id.desc()).first()
    res = env.post(f"/api/solver/solutions/{env.sol.id}/history/undo-to/{newest.id}")
    assert res.status_code == 200 and res.json()["undone"] == 2
    assert _clashes(env) == []


# ─── G3-02: η αναίρεση αρνείται να ξαναφτιάξει σύγκρουση (τίποτα δεν αλλάζει) ──

def test_undo_after_guarded_teacher_change_is_refused_and_changes_nothing(env):
    l1 = _lesson(env, env.t1, env.c1, env.subj_m)
    l2 = _lesson(env, env.t2, env.c2, env.subj_f)
    s1 = _slot(env, l1, 0, env.p[0], env.r1, locked=True)
    _slot(env, l2, 0, env.p[0], env.r2)
    body = {"subject_id": env.subj_m.id, "teacher_id": env.t2.id, "class_id": env.c1.id,
            "periods_per_week": 1}
    conflict = env.put(f"/api/lessons/{l1.id}", json=body)
    assert conflict.status_code == 409
    assert "Ιστορικό" not in conflict.json()["detail"]["message"]       # δεν υπόσχεται αναίρεση
    assert env.put(f"/api/lessons/{l1.id}?force=true", json=body).status_code == 200
    assert _pos(env, s1)[3] is True                                      # στην Παλέτα
    before = _summary(env)

    res = _undo(env)
    assert res.status_code == 409
    assert "Τ2" in res.json()["detail"] and "Δεν άλλαξε τίποτα" in res.json()["detail"]
    assert _pos(env, s1) == (None, None, None, True)                     # έμεινε στην Παλέτα
    assert _clashes(env) == []
    assert _summary(env) == before                                       # ιστορικό ανέγγιχτο

    # undo-to: ίδια άρνηση, all-or-nothing
    entry = env.s.query(TimetableSlotHistory).first()
    res = env.post(f"/api/solver/solutions/{env.sol.id}/history/undo-to/{entry.id}")
    assert res.status_code == 409 and "Τ2" in res.json()["detail"]
    assert _pos(env, s1) == (None, None, None, True) and _summary(env) == before


def test_undo_refuses_shared_student_double_booking(env):
    st = Student(first_name="Άννα", last_name="Χ")
    env.s.add(st)
    env.s.commit()
    env.s.add_all([StudentClassEnrollment(student_id=st.id, class_id=env.c1.id),
                   StudentClassEnrollment(student_id=st.id, class_id=env.c2.id)])
    env.s.commit()
    a = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[0], env.r1)
    _move(env, a, 0, env.p[1])                                   # ιστορικό: Δευ 1η → 2η
    # Άλλη κάρτα (κοινή μαθήτρια) μπαίνει στη Δευ 1η χωρίς ιστορικό.
    _slot(env, _lesson(env, env.t2, env.c2, env.subj_f), 0, env.p[0], env.r2)
    res = _undo(env)
    assert res.status_code == 409 and "Χ Άννα" in res.json()["detail"]
    assert _pos(env, a)[:2] == (0, env.p[1].id)


def test_redo_refuses_double_booking_and_keeps_the_redo(env):
    a = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[0], env.r1)
    _move(env, a, 0, env.p[1])
    assert _undo(env).status_code == 200                          # πίσω στην 1η
    _slot(env, _lesson(env, env.t2, env.c1, env.subj_f), 0, env.p[1], env.r2)   # ίδιο τμήμα στη 2η
    res = _redo(env)
    assert res.status_code == 409 and "Α1" in res.json()["detail"]
    assert _pos(env, a)[:2] == (0, env.p[0].id)
    assert _summary(env)["can_redo"] == 1
    assert _clashes(env) == []


def test_plain_undo_redo_unchanged_when_there_is_no_conflict(env):
    a = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[0], env.r1)
    _move(env, a, 2, env.p[3], env.r2)
    assert _undo(env).json()["message"] == "Η αλλαγή αναιρέθηκε"
    assert _pos(env, a) == (0, env.p[0].id, env.r1.id, False)
    assert _redo(env).json()["message"] == "Η αλλαγή επαναλήφθηκε"
    assert _pos(env, a) == (2, env.p[3].id, env.r2.id, False)


# ─── G3-06: μετατόπιση ωρών + Ctrl+Z ─────────────────────────────────────────
# Το ιστορικό μετατοπίζεται ΜΑΖΙ με τα slots (ίδιος χάρτης): το Ctrl+Z γυρίζει
# την κάρτα στο μετατοπισμένο ισοδύναμο της παλιάς ώρας, ποτέ στην προ-μετατόπισης.

def _shift(env, offset, shift_solutions=True):
    res = env.post(f"/api/terms/{env.term.id}/shift-times",
                   json={"offset": offset, "shift_solutions": shift_solutions})
    assert res.status_code == 200, res.text
    return res.json()


def _history_rows(env):
    env.s.expire_all()
    cols = [c.name for c in TimetableSlotHistory.__table__.columns]
    return [tuple(getattr(r, c) for c in cols)
            for r in env.s.query(TimetableSlotHistory).order_by(TimetableSlotHistory.id)]


def test_undo_after_time_shift_returns_to_the_shifted_old_hour(env):
    la = _lesson(env, env.t1, env.c1, env.subj_m)
    lb = _lesson(env, env.t2, env.c1, env.subj_f)
    sa = _slot(env, la, 0, env.p[1], env.r1)
    _slot(env, lb, 0, env.p[0], env.r2)
    _move(env, sa, 0, env.p[2])                                  # ΜΑΘ: 2η → 3η
    body = _shift(env, 1)                                        # ΦΥΣ 1η→2η, ΜΑΘ 3η→4η
    assert _pos(env, sa)[:2] == (0, env.p[3].id)
    res = _undo(env)
    assert res.status_code == 200, res.text
    assert _pos(env, sa) == (0, env.p[2].id, env.r1.id, False)   # η 2η μετατοπισμένη = 3η
    assert _clashes(env) == []
    assert body["history_remapped"] == 1
    assert _redo(env).status_code == 200
    assert _pos(env, sa)[:2] == (0, env.p[3].id)
    items = env.get(f"/api/solver/solutions/{env.sol.id}/history").json()["items"]
    assert (items[0]["from"], items[0]["to"]) == ("Δευ 3η · R1", "Δευ 4η · R1")


def test_out_of_range_history_goes_to_the_palette_like_the_slot(env):
    sa = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[4], env.r1)
    _move(env, sa, 0, env.p[1])                                  # από την 5η (τελευταία) → 2η
    sb = _slot(env, _lesson(env, env.t2, env.c2, env.subj_f), 1, env.p[1], env.r2)
    _move(env, sb, 1, env.p[4])                                  # 2η → 5η
    body = _shift(env, 1)
    assert body["slots_unplaced"] == 1
    assert _pos(env, sb) == (None, None, None, True)             # το slot στην 5η → Παλέτα

    # Νεότερη πρώτη: η sb ήταν στη 2η (→ 3η μετατοπισμένη) πριν πάει στην 5η (→ Παλέτα).
    assert _undo(env).status_code == 200
    assert _pos(env, sb) == (1, env.p[2].id, env.r2.id, False)
    assert _redo(env).status_code == 200                         # ξανά «στην 5η» = Παλέτα
    assert _pos(env, sb) == (None, None, None, True)
    assert _undo(env).status_code == 200
    # Η sa ήρθε από την 5η: το μετατοπισμένο ισοδύναμο δεν υπάρχει → Παλέτα, όπως ένα slot.
    assert _undo(env).status_code == 200
    assert _pos(env, sa) == (None, None, None, True)
    assert _clashes(env) == []
    assert env.s.query(TimetableSlotHistory).count() == 2        # καμία εγγραφή δεν σβήστηκε
    assert body["history_remapped"] == 2


def test_shift_without_programmes_leaves_history_untouched(env):
    sa = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[1], env.r1)
    _move(env, sa, 0, env.p[2])
    before = _history_rows(env)
    assert _shift(env, 1, shift_solutions=False).get("history_remapped", 0) == 0
    assert _history_rows(env) == before
    assert _pos(env, sa)[:2] == (0, env.p[2].id)                 # ούτε το slot μετακινήθηκε
    assert _undo(env).status_code == 200
    assert _pos(env, sa)[:2] == (0, env.p[1].id)


def test_consecutive_shifts_compose(env):
    sa = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 2, env.p[0], env.r1)
    _move(env, sa, 2, env.p[1])                                  # 1η → 2η
    _shift(env, 1)
    _shift(env, 1)                                               # σύνολο +2: 2η → 4η
    assert _pos(env, sa)[:2] == (2, env.p[3].id)
    _shift(env, -1)                                              # σύνολο +1
    assert _pos(env, sa)[:2] == (2, env.p[2].id)
    assert _undo(env).status_code == 200
    assert _pos(env, sa)[:2] == (2, env.p[1].id)                 # 1η + 1 = 2η


def test_deleted_period_in_history_stays_unusable_after_a_shift(env):
    sa = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[4], env.r1)
    _move(env, sa, 0, env.p[0])
    assert env.delete(f"/api/periods/{env.p[4].id}").status_code == 204
    _shift(env, 1)
    res = _undo(env)                                             # δεν «μαντεύει» θέση
    assert res.status_code == 409 and "δεν υπάρχει πια" in res.json()["detail"]
    assert _pos(env, sa)[:2] == (0, env.p[1].id)


# ─── G3-07 / G2-12: αίθουσα ή ώρα του ιστορικού διαγράφηκε → 409, όχι 500 ─────

def test_deleted_room_in_history_is_skipped_and_older_history_still_works(env):
    s2 = _slot(env, _lesson(env, env.t2, env.c2, env.subj_f), 3, env.p[0], env.r1)
    _move(env, s2, 3, env.p[1])                                    # παλαιότερη, υγιής αλλαγή
    s1 = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[0], env.r3)
    _move(env, s1, 0, env.p[1])                                    # ιστορικό με την R3
    assert env.delete(f"/api/classrooms/{env.r3.id}?force=true").status_code == 204
    assert _pos(env, s1) == (None, None, None, True)               # Παλέτα

    res = _undo(env)
    assert res.status_code == 409
    assert "αίθουσά της δεν υπάρχει" in res.json()["detail"] and "παραλείφθηκε" in res.json()["detail"]
    assert _pos(env, s1) == (None, None, None, True)               # ανέγγιχτη
    res = _undo(env)                                               # συνεχίζει με την παλαιότερη
    assert res.status_code == 200
    assert _pos(env, s2)[:2] == (3, env.p[0].id)
    assert _summary(env)["can_undo"] == 0

    assert _redo(env).status_code == 200                           # η υγιής ξαναγίνεται
    res = _redo(env)                                               # η «νεκρή» παραλείπεται
    assert res.status_code == 409 and _pos(env, s1) == (None, None, None, True)
    assert env.s.query(TimetableSlotHistory).count() == 2          # τίποτα δεν σβήστηκε


def test_deleted_period_in_history_gives_409_not_500(env):
    s1 = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[4], env.r1)
    _move(env, s1, 0, env.p[1])
    assert env.delete(f"/api/periods/{env.p[4].id}").status_code == 204
    res = _undo(env)
    assert res.status_code == 409 and "ώρα" in res.json()["detail"]
    assert _pos(env, s1)[:2] == (0, env.p[1].id)


def test_undo_to_skips_dead_entries_and_restores_the_rest(env):
    s2 = _slot(env, _lesson(env, env.t2, env.c2, env.subj_f), 3, env.p[0], env.r1)
    first = _move(env, s2, 3, env.p[1])
    s1 = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[0], env.r3)
    _move(env, s1, 0, env.p[1])
    env.delete(f"/api/classrooms/{env.r3.id}?force=true")
    entry = env.s.query(TimetableSlotHistory).order_by(TimetableSlotHistory.id).first()
    res = env.post(f"/api/solver/solutions/{env.sol.id}/history/undo-to/{entry.id}")
    assert res.status_code == 200, res.text
    assert res.json()["undone"] == 1
    assert _pos(env, s2)[:2] == (3, env.p[0].id)
    assert _pos(env, s1) == (None, None, None, True)
    assert first.status_code == 200


def _set_break(env, period, is_break):
    return env.put(f"/api/periods/{period.id}", json={
        "name": period.name, "short_name": period.short_name, "start_time": period.start_time,
        "end_time": period.end_time, "is_break": is_break, "sort_order": period.sort_order})


def test_undo_into_a_break_hour_waits_until_it_is_a_teaching_hour_again(env):
    s1 = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[2], env.r1)
    _move(env, s1, 0, env.p[3])
    assert _set_break(env, env.p[2], True).status_code == 200      # καμία ώρα εκεί πια
    before = _summary(env)
    res = _undo(env)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "break_hour"
    assert "διάλειμμα" in res.json()["detail"]["message"]
    assert _pos(env, s1)[:2] == (0, env.p[3].id)                     # δεν κρύφτηκε σε διάλειμμα
    assert _summary(env) == before                                   # άρνηση: ιστορικό ανέγγιχτο
    assert _set_break(env, env.p[2], False).status_code == 200
    assert _undo(env).status_code == 200                             # τώρα γίνεται κανονικά
    assert _pos(env, s1)[:2] == (0, env.p[2].id)


def test_time_shift_keeps_history_positions_on_break_hours(env):
    s1 = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[2], env.r1)
    _move(env, s1, 0, env.p[3])
    assert _set_break(env, env.p[2], True).status_code == 200
    _shift(env, 1)                                                   # 4η → 5η
    entry = env.s.query(TimetableSlotHistory).one()
    env.s.refresh(entry)
    # Η ώρα-διάλειμμα δεν έχει μετατοπισμένο ισοδύναμο: η παλιά θέση ΔΕΝ χάνεται.
    assert (entry.prev_day_of_week, entry.prev_period_id, entry.prev_classroom_id,
            entry.prev_is_unplaced) == (0, env.p[2].id, env.r1.id, False)
    assert (entry.new_period_id, entry.new_is_unplaced) == (env.p[4].id, False)


def test_database_error_during_undo_is_409_and_rolls_back(env, monkeypatch):
    s1 = _slot(env, _lesson(env, env.t1, env.c1, env.subj_m), 0, env.p[0], env.r3)
    _move(env, s1, 0, env.p[1])
    env.delete(f"/api/classrooms/{env.r3.id}?force=true")
    # Παράκαμψη του ελέγχου → το flush σκάει στο FK (όπως θα έσκαγε στο Postgres).
    monkeypatch.setattr(slot_history, "_unusable", lambda db, state: None)
    res = _undo(env)
    assert res.status_code == 409 and "Δεν άλλαξε τίποτα" in res.json()["detail"]
    assert _pos(env, s1) == (None, None, None, True)
    assert _summary(env)["can_undo"] == 1
