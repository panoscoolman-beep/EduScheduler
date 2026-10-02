"""Ώρα με τοποθετημένα μαθήματα → «Διάλειμμα»: ποτέ σιωπηλή εξαφάνιση, ποτέ απώλεια.

Πριν (G3-05): PUT /periods/{id} με is_break=true έκρυβε τα μαθήματα από πλέγμα
και εκτυπώσεις, ενώ έμεναν «τοποθετημένα» στο .ics και στις δημοσιεύσεις.

Τώρα: 409 + πλήθη ανά πρόγραμμα (με σενάριο και «αρχειοθετημένο»). Με force:
  • ενεργά προγράμματα (όλων των σεναρίων) → Παλέτα, με εγγραφή 'unplace' στο
    🕘 ιστορικό (παλιά μέρα/ώρα/αίθουσα/🔒) → αν η ώρα ξαναγίνει διδακτική, το
    «↩️ Αναίρεση» τα επαναφέρει·
  • αρχειοθετημένα → ΑΝΕΓΓΙΧΤΑ (κρυφά όσο είναι διάλειμμα, πίσω μόλις ξαναγίνει
    διδακτική — όπως πάντα).
"""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, Subject, Teacher, Term, TimetableSlot,
    TimetableSlotHistory, TimetableSolution,
)
from backend.routers import periods as periods_router
from backend.routers import solver as solver_router


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
    winter = Term(name="Χειμερινό", is_active=True)
    summer = Term(name="Καλοκαιρινό", is_active=False)
    subj = Subject(name="ΜΑΘ", short_name="ΜΑΘ", color="#000000")
    teacher = Teacher(name="Τ1", short_name="Τ1", color="#000000")
    cls = SchoolClass(name="Α1", short_name="Α1")
    r1 = Classroom(name="R1", short_name="R1", room_type="regular")
    r2 = Classroom(name="R2", short_name="R2", room_type="regular")
    p3 = Period(name="3η Ώρα", short_name="3η", start_time="16:00", end_time="17:00",
                is_break=False, sort_order=3)
    p4 = Period(name="4η Ώρα", short_name="4η", start_time="17:00", end_time="18:00",
                is_break=False, sort_order=4)
    s.add_all([winter, summer, subj, teacher, cls, r1, r2, p3, p4])
    s.commit()
    live = TimetableSolution(name="Τρέχον", status="optimal", term_id=winter.id)
    old = TimetableSolution(name="Παλιό", status="optimal", term_id=winter.id,
                            archived_at=dt.datetime(2026, 9, 20))
    other = TimetableSolution(name="Θερινό", status="optimal", term_id=summer.id)
    s.add_all([live, old, other])
    s.commit()
    lessons = {}
    for term in (winter, summer):
        lessons[term.id] = Lesson(subject_id=subj.id, teacher_id=teacher.id, class_id=cls.id,
                                  periods_per_week=2, term_id=term.id)
        s.add(lessons[term.id])
    s.commit()

    app = FastAPI()
    app.include_router(periods_router.router, prefix="/api/periods")
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app, raise_server_exceptions=False)
    c.s, c.p3, c.p4, c.r1, c.r2 = s, p3, p4, r1, r2
    c.live, c.old, c.other, c.lessons, c.winter, c.summer = live, old, other, lessons, winter, summer
    yield c
    s.close()


def _slot(env, sol, day, period, room, locked=False):
    slot = TimetableSlot(solution_id=sol.id, lesson_id=env.lessons[sol.term_id].id,
                         day_of_week=day, period_id=period.id, classroom_id=room.id,
                         is_unplaced=False, is_locked=locked)
    env.s.add(slot)
    env.s.commit()
    return slot


def _body(period: Period, **changes) -> dict:
    body = {"name": period.name, "short_name": period.short_name, "start_time": period.start_time,
            "end_time": period.end_time, "is_break": bool(period.is_break),
            "sort_order": period.sort_order}
    body.update(changes)
    return body


def _state(env, slot):
    env.s.expire_all()
    s = env.s.get(TimetableSlot, slot.id)
    return (s.day_of_week, s.period_id, s.classroom_id, bool(s.is_locked), bool(s.is_unplaced))


def _to_break(env, force=False, period=None):
    period = period or env.p3
    return env.put(f"/api/periods/{period.id}{'?force=true' if force else ''}",
                   json=_body(period, is_break=True))


def _history(env, sol):
    env.s.expire_all()
    return env.s.query(TimetableSlotHistory).filter(
        TimetableSlotHistory.solution_id == sol.id).order_by(TimetableSlotHistory.id).all()


# ─── χωρίς force: 409, τίποτα δεν αλλάζει ─────────────────────────────────────

def test_without_force_a_used_period_is_409_and_nothing_changes(env):
    a = _slot(env, env.live, 0, env.p3, env.r1, locked=True)
    b = _slot(env, env.old, 1, env.p3, env.r2)
    res = _to_break(env)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "period_in_use" and detail["requires_force"] is True
    assert (detail["slots"], detail["solutions"]) == (2, 2)
    env.s.expire_all()
    assert env.s.get(Period, env.p3.id).is_break is False
    assert _state(env, a) == (0, env.p3.id, env.r1.id, True, False)
    assert _state(env, b) == (1, env.p3.id, env.r2.id, False, False)
    assert _history(env, env.live) == []


def test_409_lists_each_programme_with_scenario_and_archived_marker(env):
    _slot(env, env.live, 0, env.p3, env.r1)
    _slot(env, env.live, 1, env.p3, env.r1)
    _slot(env, env.old, 2, env.p3, env.r2)
    _slot(env, env.other, 3, env.p3, env.r2)
    detail = _to_break(env).json()["detail"]
    assert detail["programmes"] == [
        {"solution_id": env.live.id, "solution_name": "Τρέχον", "term_id": env.winter.id,
         "term_name": "Χειμερινό", "archived": False, "slots": 2},
        {"solution_id": env.old.id, "solution_name": "Παλιό", "term_id": env.winter.id,
         "term_name": "Χειμερινό", "archived": True, "slots": 1},
        {"solution_id": env.other.id, "solution_name": "Θερινό", "term_id": env.summer.id,
         "term_name": "Καλοκαιρινό", "archived": False, "slots": 1},
    ]
    msg = detail["message"]
    assert "«Παλιό» (σενάριο «Χειμερινό», αρχειοθετημένο): 1" in msg
    assert "«Θερινό» (σενάριο «Καλοκαιρινό»): 1" in msg
    assert "Παλέτα" in msg and "🕘 Ιστορικό" in msg and "ΔΕΝ αλλάζουν" in msg
    assert "«Επαναλήψεις»" in msg                       # το redo των ενεργών χάνεται


def test_unused_period_and_other_edits_need_no_force(env):
    _slot(env, env.live, 0, env.p3, env.r1)
    assert env.put(f"/api/periods/{env.p3.id}",
                   json=_body(env.p3, name="3η", start_time="16:05")).status_code == 200
    assert _to_break(env, period=env.p4).status_code == 200
    assert env.put(f"/api/periods/{env.p4.id}",
                   json=_body(env.p4, is_break=False)).status_code == 200


# ─── με force ────────────────────────────────────────────────────────────────

def test_archived_only_usage_with_force_leaves_the_slots_untouched(env):
    a = _slot(env, env.old, 0, env.p3, env.r1, locked=True)
    info = _to_break(env)
    assert info.status_code == 409                                 # ενημέρωση πρώτα
    msg = info.json()["detail"]["message"]
    assert "ΔΕΝ αλλάζουν" in msg and "δεν φαίνονται" in msg
    assert "Παλέτα" not in msg and "συγκρού" not in msg and "Επαναλήψεις" not in msg
    res = _to_break(env, force=True)
    assert res.status_code == 200 and res.json()["is_break"] is True
    assert _state(env, a) == (0, env.p3.id, env.r1.id, True, False)   # ακριβώς ίδιο
    assert _history(env, env.old) == []
    # Ξανά διδακτική → φαίνεται ξανά, όπως πάντα.
    assert env.put(f"/api/periods/{env.p3.id}", json=_body(env.p3, is_break=False)).status_code == 200
    assert _state(env, a) == (0, env.p3.id, env.r1.id, True, False)


def test_force_moves_only_active_programmes_each_with_a_history_row(env):
    a = _slot(env, env.live, 0, env.p3, env.r1, locked=True)
    b = _slot(env, env.other, 2, env.p3, env.r2)
    c = _slot(env, env.old, 1, env.p3, env.r2, locked=True)
    keep = _slot(env, env.live, 4, env.p4, env.r1)               # άλλη ώρα: ανέγγιχτη
    assert _to_break(env, force=True).status_code == 200

    for slot in (a, b):
        st = _state(env, slot)
        assert st == (None, None, None, False, True)
        assert "διάλειμμα" in env.s.get(TimetableSlot, slot.id).unplaced_reason
    # Η παλιά θέση μένει ΚΑΙ στην κάρτα (το ιστορικό μπορεί να χαθεί αργότερα).
    assert env.s.get(TimetableSlot, a.id).unplaced_reason == (
        "Η «3η Ώρα» έγινε διάλειμμα — ήταν Δευτέρα 3η Ώρα, R1, 🔒")
    assert env.s.get(TimetableSlot, b.id).unplaced_reason == (
        "Η «3η Ώρα» έγινε διάλειμμα — ήταν Τετάρτη 3η Ώρα, R2")
    assert _state(env, c) == (1, env.p3.id, env.r2.id, True, False)   # αρχειοθετημένο
    assert _state(env, keep) == (4, env.p4.id, env.r1.id, False, False)

    (ha,) = _history(env, env.live)
    assert (ha.slot_id, ha.operation) == (a.id, "unplace")
    assert (ha.prev_day_of_week, ha.prev_period_id, ha.prev_classroom_id,
            ha.prev_is_locked, ha.prev_is_unplaced) == (0, env.p3.id, env.r1.id, True, False)
    (hb,) = _history(env, env.other)
    assert (hb.slot_id, hb.prev_day_of_week, hb.prev_period_id) == (b.id, 2, env.p3.id)
    assert _history(env, env.old) == []


def test_undo_waits_while_it_is_a_break_and_restores_place_and_lock_after(env):
    a = _slot(env, env.live, 0, env.p3, env.r1, locked=True)
    b = _slot(env, env.live, 3, env.p3, env.r2)
    assert _to_break(env, force=True).status_code == 200
    summary = env.get(f"/api/solver/solutions/{env.live.id}/history-summary").json()

    # Όσο είναι διάλειμμα: άρνηση με εξήγηση, τίποτα δεν αλλάζει (ούτε το ιστορικό).
    res = env.post(f"/api/solver/solutions/{env.live.id}/undo")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "break_hour" and "διάλειμμα" in res.json()["detail"]["message"]
    assert _state(env, b)[4] is True
    assert env.get(f"/api/solver/solutions/{env.live.id}/history-summary").json() == summary

    # Ξανά διδακτική → «↩️ μέχρι εδώ» στο πρώτο βήμα επαναφέρει ΟΛΕΣ, με το 🔒 τους.
    assert env.put(f"/api/periods/{env.p3.id}", json=_body(env.p3, is_break=False)).status_code == 200
    first = _history(env, env.live)[0]
    res = env.post(f"/api/solver/solutions/{env.live.id}/history/undo-to/{first.id}")
    assert res.status_code == 200 and res.json()["undone"] == 2
    assert _state(env, a) == (0, env.p3.id, env.r1.id, True, False)
    assert _state(env, b) == (3, env.p3.id, env.r2.id, False, False)


def test_single_ctrl_z_restores_one_hour_after_toggling_back(env):
    a = _slot(env, env.live, 0, env.p3, env.r1, locked=True)
    _to_break(env, force=True)
    env.put(f"/api/periods/{env.p3.id}", json=_body(env.p3, is_break=False))
    res = env.post(f"/api/solver/solutions/{env.live.id}/undo")
    assert res.status_code == 200, res.text
    assert _state(env, a) == (0, env.p3.id, env.r1.id, True, False)


# ─── R1: η ώρα ΜΕΝΕΙ διάλειμμα — ρητή παράλειψη αντί για αδιέξοδο ─────────────

def _move(env, slot, day, period, room):
    res = env.put(f"/api/solver/solutions/{slot.solution_id}/slots/{slot.id}",
                  json={"day_of_week": day, "period_id": period.id, "classroom_id": room.id})
    assert res.status_code == 200, res.text


def _undo(env, skip=False, sol=None):
    return env.post(f"/api/solver/solutions/{(sol or env.live).id}/undo"
                    + ("?skip_break=true" if skip else ""))


def _redo(env, skip=False, sol=None):
    return env.post(f"/api/solver/solutions/{(sol or env.live).id}/redo"
                    + ("?skip_break=true" if skip else ""))


def _summary(env, sol=None):
    return env.get(f"/api/solver/solutions/{(sol or env.live).id}/history-summary").json()


def _flags(env, sol=None):
    return [bool(h.undone) for h in _history(env, sol or env.live)]


def test_force_path_is_no_dead_end_with_an_explicit_skip(env):
    k = _slot(env, env.live, 1, env.p4, env.r1)
    _move(env, k, 2, env.p4, env.r2)                     # παλαιότερη, εφαρμόσιμη αλλαγή
    a = _slot(env, env.live, 0, env.p3, env.r1, locked=True)
    b = _slot(env, env.live, 3, env.p3, env.r2)
    assert _to_break(env, force=True).status_code == 200   # 2 'unplace' πάνω από αυτήν
    newest = _history(env, env.live)[-1]
    before = (_summary(env), _flags(env))

    for _ in range(2):                                   # χωρίς επιβεβαίωση: πάντα 409, τίποτα δεν αλλάζει
        res = _undo(env)
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert detail["code"] == "break_hour" and detail["requires_force"] is True
        assert detail["entry_id"] == newest.id and detail["period"] == "3η Ώρα"
        assert "παραλείψεις" in detail["message"]
        assert (_summary(env), _flags(env)) == before

    res = _undo(env, skip=True)                          # παράλειψη + η παλαιότερη, σε ΕΝΑ αίτημα
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["skipped_break"] == 2 and body["slot_id"] == k.id
    assert _state(env, k) == (1, env.p4.id, env.r1.id, False, False)
    assert _state(env, a)[4] is True and _state(env, b)[4] is True   # οι κάρτες ανέγγιχτες
    assert _flags(env) == [True, True, True]
    assert body["history"] == _summary(env) == {"can_undo": 0, "can_redo": 3, "total": 3}

    # Το redo μένει συνεπές: ξαναγίνεται η μετακίνηση και μετά οι (ήδη) «στην Παλέτα».
    for _ in range(3):
        assert _redo(env).status_code == 200
    assert _state(env, k)[:2] == (2, env.p4.id)
    assert _summary(env) == {"can_undo": 3, "can_redo": 0, "total": 3}


def test_manual_moves_out_of_the_hour_then_break_is_no_dead_end(env):
    k = _slot(env, env.live, 1, env.p4, env.r1)
    _move(env, k, 2, env.p4, env.r2)                     # παλαιότερη
    a = _slot(env, env.live, 0, env.p3, env.r1)
    _move(env, a, 4, env.p4, env.r1)                     # βγήκε με το χέρι από την 3η
    assert _to_break(env).status_code == 200             # άδεια ώρα → διάλειμμα χωρίς 409
    res = _undo(env)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "break_hour"
    res = _undo(env, skip=True)
    assert res.status_code == 200 and res.json()["skipped_break"] == 1
    assert _state(env, a)[:2] == (4, env.p4.id)          # δεν μπήκε σε διάλειμμα
    assert _state(env, k)[:2] == (1, env.p4.id)          # αναιρέθηκε η παλαιότερη
    assert _summary(env) == {"can_undo": 0, "can_redo": 2, "total": 2}


def test_only_break_entries_left_returns_nothing_to_undo_with_the_count(env):
    _slot(env, env.live, 0, env.p3, env.r1)
    _slot(env, env.live, 3, env.p3, env.r2)
    _to_break(env, force=True)
    res = _undo(env, skip=True)
    assert res.status_code == 400
    assert res.json() == {"detail": "Δεν υπάρχει αλλαγή προς αναίρεση", "skipped_break": 2}
    assert _summary(env) == {"can_undo": 0, "can_redo": 2, "total": 2}
    assert _undo(env).status_code == 400                  # όπως σήμερα: τίποτα για αναίρεση


def test_undo_to_across_break_entries_reaches_the_target_only_with_the_flag(env):
    k = _slot(env, env.live, 1, env.p4, env.r1)
    _move(env, k, 2, env.p4, env.r2)
    target = _history(env, env.live)[0]
    _slot(env, env.live, 0, env.p3, env.r1, locked=True)
    _to_break(env, force=True)
    before = (_summary(env), _flags(env))
    url = f"/api/solver/solutions/{env.live.id}/history/undo-to/{target.id}"
    res = env.post(url)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "break_hour"
    assert (_summary(env), _flags(env)) == before        # όλα ή τίποτα
    res = env.post(url + "?skip_break=true")
    assert res.status_code == 200, res.text
    assert (res.json()["undone"], res.json()["skipped_break"]) == (1, 1)
    assert _state(env, k)[:2] == (1, env.p4.id)
    assert _summary(env) == {"can_undo": 0, "can_redo": 2, "total": 2}


def test_redo_onto_a_break_hour_skips_with_the_flag_and_redoes_the_next(env):
    a = _slot(env, env.live, 0, env.p4, env.r1)
    _move(env, a, 0, env.p3, env.r1)                     # E: 4η → 3η
    k = _slot(env, env.live, 1, env.p4, env.r2)
    _move(env, k, 2, env.p4, env.r2)                     # F
    assert _undo(env).status_code == 200 and _undo(env).status_code == 200
    assert _to_break(env).status_code == 200             # η 3η άδεια → διάλειμμα
    res = _redo(env)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "break_hour"
    assert "επόμενες" in res.json()["detail"]["message"]
    res = _redo(env, skip=True)
    assert res.status_code == 200 and res.json()["skipped_break"] == 1
    assert _state(env, a)[:2] == (0, env.p4.id)          # δεν μπήκε σε διάλειμμα
    assert _state(env, k)[:2] == (2, env.p4.id)          # ξαναέγινε η επόμενη
    assert _summary(env) == {"can_undo": 2, "can_redo": 0, "total": 2}


def test_a_clash_after_skipping_keeps_the_whole_request_unapplied(env):
    k = _slot(env, env.live, 1, env.p4, env.r1)
    _move(env, k, 2, env.p4, env.r2)
    _slot(env, env.live, 0, env.p3, env.r1)
    _to_break(env, force=True)
    _slot(env, env.live, 1, env.p4, env.r2)              # πιάνει την παλιά θέση του k (ίδιος καθηγητής)
    before = (_summary(env), _flags(env))
    res = _undo(env, skip=True)
    assert res.status_code == 409 and "Δεν άλλαξε τίποτα" in res.json()["detail"]
    assert (_summary(env), _flags(env)) == before        # ούτε η παράλειψη κρατήθηκε


def test_skipping_breaks_then_hitting_a_deleted_room_keeps_both_skips_and_explains(env):
    k = _slot(env, env.live, 1, env.p4, env.r2)
    _move(env, k, 2, env.p4, env.r1)                     # D: η παλιά θέση στην R2
    env.s.delete(env.s.get(Classroom, env.r2.id))        # η R2 σβήνεται (το ιστορικό δεν έχει FK)
    env.s.commit()
    _slot(env, env.live, 0, env.p3, env.r1)
    _to_break(env, force=True)                           # U: πάνω από τη D
    res = _undo(env, skip=True)
    assert res.status_code == 409
    msg = res.json()["detail"]
    assert "αίθουσά της δεν υπάρχει πια" in msg and "1 αλλαγές σε ώρες-διαλείμματα" in msg
    assert _flags(env) == [True, True]                   # και οι δύο παραλείψεις κρατήθηκαν
    assert _state(env, k)[:2] == (2, env.p4.id)
    assert _summary(env) == {"can_undo": 0, "can_redo": 2, "total": 2}
