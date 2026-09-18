"""🕘 Ιστορικό αλλαγών + «αναίρεση μέχρι εδώ» (όλες ή καμία, αναστρέψιμη)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, Subject, Teacher, TimetableSlot, TimetableSolution,
)
from backend.routers import solver as solver_router
from backend.services import slot_history as svc


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    subj = Subject(name="Φυσική", short_name="ΦΥΣ", color="#000000")
    teacher = Teacher(name="Γεωργέλλης", short_name="ΓΕ", color="#000000")
    cls = SchoolClass(name="Β2", short_name="Β2")
    room = Classroom(name="Αίθ 2", short_name="Α2", room_type="regular")
    p1 = Period(name="1η", short_name="1η", start_time="14:00", end_time="15:00", is_break=False, sort_order=1)
    p2 = Period(name="2η", short_name="2η", start_time="15:00", end_time="16:00", is_break=False, sort_order=2)
    s.add_all([subj, teacher, cls, room, p1, p2])
    s.commit()
    sol = TimetableSolution(name="Π", status="optimal")
    lesson = Lesson(subject_id=subj.id, teacher_id=teacher.id, class_id=cls.id, periods_per_week=1)
    s.add_all([sol, lesson])
    s.commit()
    slot = TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=0, period_id=p1.id,
                         classroom_id=room.id, is_unplaced=False)
    s.add(slot)
    s.commit()

    def move(day, period_id):
        prev = svc._slot_state(slot)
        slot.day_of_week, slot.period_id = day, period_id
        entry = svc.record_edit(s, slot, prev, svc._slot_state(slot), "move")
        s.commit()
        return entry.id

    ids = [move(1, p1.id), move(2, p2.id), move(3, p1.id)]      # Δευ1 → Τρι1 → Τετ2 → Πεμ1
    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session, c.sol, c.slot, c.ids, c.p1 = s, sol, slot, ids, p1
    yield c
    s.close()


def test_history_lists_newest_first_with_readable_positions(env):
    body = env.get(f"/api/solver/solutions/{env.sol.id}/history").json()
    items = body["items"]
    assert [i["id"] for i in items] == list(reversed(env.ids))
    assert items[0]["operation_label"] == "Μετακίνηση"
    assert items[0]["lesson"] == "Φυσική · Β2 · Γεωργέλλης"
    assert (items[0]["from"], items[0]["to"]) == ("Τετ 2η · Αίθ 2", "Πεμ 1η · Αίθ 2")
    assert body["summary"]["can_undo"] == 3
    assert env.get("/api/solver/solutions/999/history").status_code == 404


def test_undo_to_reverts_that_change_and_all_newer_ones(env):
    res = env.post(f"/api/solver/solutions/{env.sol.id}/history/undo-to/{env.ids[1]}").json()
    assert res["undone"] == 2 and "Επανάληψη" in res["message"]
    env.session.refresh(env.slot)
    assert (env.slot.day_of_week, env.slot.period_id) == (1, env.p1.id)       # πίσω στην Τρίτη 1η
    assert res["history"]["can_undo"] == 1 and res["history"]["can_redo"] == 2
    # Αναστρέψιμο: δύο «↪ Επανάληψη» ξαναφέρνουν την Πέμπτη.
    env.post(f"/api/solver/solutions/{env.sol.id}/redo")
    env.post(f"/api/solver/solutions/{env.sol.id}/redo")
    env.session.refresh(env.slot)
    assert env.slot.day_of_week == 3


def test_undo_to_rejects_already_undone_or_foreign_entries(env):
    env.post(f"/api/solver/solutions/{env.sol.id}/history/undo-to/{env.ids[2]}")
    again = env.post(f"/api/solver/solutions/{env.sol.id}/history/undo-to/{env.ids[2]}")
    assert again.status_code == 409 and "ήδη αναιρεθεί" in again.json()["detail"]
    missing = env.post(f"/api/solver/solutions/{env.sol.id}/history/undo-to/9999")
    assert missing.status_code == 409
    env.session.refresh(env.slot)
    assert env.slot.day_of_week == 2                                           # μόνο η 1 αναίρεση
