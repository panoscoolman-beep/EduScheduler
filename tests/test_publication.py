"""📢 Δημοσίευση προγράμματος: «τι άλλαξε για σένα» + endpoints."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, Subject, Teacher, Term, TimetableSlot, TimetableSolution,
)
from backend.routers import publications as pub_router
from backend.services import publication as svc


def _e(teacher_id, lesson_id, day, start, end, label="ΦΥΣΙΚΗ (Β2)", room="Α", teacher="Τ"):
    return {"teacher_id": teacher_id, "teacher": teacher, "lesson_id": lesson_id, "label": label,
            "day": day, "period_id": int(start[:2]), "start": start, "end": end, "room": room}


# --- pure ---------------------------------------------------------------------

def test_move_add_remove_and_room_change_per_teacher():
    prev = [_e(1, 10, 1, "17:00", "18:00"), _e(1, 11, 4, "16:00", "17:00", label="ΧΗΜΕΙΑ (Γ1)"),
            _e(2, 20, 0, "15:00", "16:00", teacher="Κ")]
    cur = [_e(1, 10, 3, "18:00", "19:00"), _e(1, 12, 0, "19:00", "20:00", label="ΒΙΟΛΟΓΙΑ (Α1)"),
           _e(2, 20, 0, "15:00", "16:00", room="Β", teacher="Κ")]
    ch = svc.teacher_changes(prev, cur)
    assert set(ch) == {1, 2}
    assert [(m["from"]["day"], m["to"]["day"]) for m in ch[1]["moved"]] == [(1, 3)]
    assert [e["label"] for e in ch[1]["added"]] == ["ΒΙΟΛΟΓΙΑ (Α1)"]
    assert [e["label"] for e in ch[1]["removed"]] == ["ΧΗΜΕΙΑ (Γ1)"]
    msg = svc.teacher_message("Κ", cur[2:], ch[2])
    assert "αίθουσα Α → Β" in msg                     # ίδια ώρα, άλλη αίθουσα


def test_unchanged_teacher_is_not_notified_and_reassigned_lesson_hits_both():
    prev = [_e(1, 10, 1, "17:00", "18:00"), _e(3, 30, 2, "16:00", "17:00")]
    cur = [_e(2, 10, 1, "17:00", "18:00", teacher="Νέος"), _e(3, 30, 2, "16:00", "17:00")]
    ch = svc.teacher_changes(prev, cur)
    assert set(ch) == {1, 2}                           # ο 3 δεν ενοχλείται
    assert ch[1]["removed"] and ch[2]["added"]


def test_first_publication_messages_everyone_with_merged_blocks():
    cur = [_e(1, 10, 0, "16:00", "17:00"), _e(1, 10, 0, "17:00", "18:00"),
           _e(1, 11, 2, "15:00", "16:00", label="ΧΗΜΕΙΑ (Γ1)")]
    (m,) = svc.build_messages(None, cur)
    assert m["changes"] is None and m["hours"] == 3
    assert "Τι άλλαξε" not in m["message"]
    assert "  16:00–18:00 ΦΥΣΙΚΗ (Β2) · Α" in m["message"]   # συνεχόμενες ώρες = ένα μπλοκ
    assert m["message"].index("Δευτέρα") < m["message"].index("Τετάρτη")


def test_teacher_left_without_hours_gets_told():
    msgs = svc.build_messages([_e(1, 10, 0, "16:00", "17:00")], [])
    assert "Δεν έχεις πλέον ώρες" in msgs[0]["message"] and "καταργείται" in msgs[0]["message"]


# --- endpoints ----------------------------------------------------------------

@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    term = Term(name="Χειμερινό", is_active=True)
    subj = Subject(name="ΦΥΣΙΚΗ", short_name="Φ", color="#000000")
    t = Teacher(name="Γ. Παπαδόπουλος", short_name="ΓΠ", color="#000000", email="g@example.com")
    c = SchoolClass(name="Β2", short_name="Β2")
    r = Classroom(name="Αίθ. Α", short_name="Α", room_type="regular")
    p1 = Period(name="1η", short_name="1", start_time="16:00", end_time="17:00", is_break=False, sort_order=1)
    p2 = Period(name="2η", short_name="2", start_time="17:00", end_time="18:00", is_break=False, sort_order=2)
    s.add_all([term, subj, t, c, r, p1, p2])
    s.commit()
    sol = TimetableSolution(name="ΧΕΙΜΕΡΙΝΟ", status="optimal", term_id=term.id)
    lesson = Lesson(subject_id=subj.id, teacher_id=t.id, class_id=c.id, periods_per_week=2, term_id=term.id)
    s.add_all([sol, lesson])
    s.commit()
    slot = TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=0, period_id=p1.id,
                         classroom_id=r.id, is_unplaced=False)
    s.add_all([slot, TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, is_unplaced=True)])
    s.commit()
    app = FastAPI()
    app.include_router(pub_router.router, prefix="/api/publications")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.s, client.sol, client.slot, client.p2 = s, sol, slot, p2
    yield client
    s.close()


def test_preview_is_read_only_and_lists_contacts(env):
    res = env.get(f"/api/publications/preview/{env.sol.id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["first"] is True and body["placed"] == 1 and body["unplaced"] == 1
    (t,) = body["teachers"]
    assert t["email"] == "g@example.com" and "Δευτέρα" in t["message"]
    assert "_snapshot" not in body
    assert env.get("/api/publications").json() == []  # τίποτα δεν γράφτηκε


def test_publish_then_change_then_republish_flow(env):
    first = env.post(f"/api/publications/solutions/{env.sol.id}", json={"note": "Έναρξη"})
    assert first.status_code == 200, first.text
    again = env.post(f"/api/publications/solutions/{env.sol.id}", json={})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "no_changes"

    env.slot.period_id = env.p2.id            # μετακίνηση 16:00 → 17:00
    env.s.commit()
    prev = env.get(f"/api/publications/preview/{env.sol.id}").json()
    assert prev["first"] is False and prev["previous"]["note"] == "Έναρξη"
    assert "Δευτέρα 16:00–17:00 → Δευτέρα 17:00–18:00" in prev["teachers"][0]["message"]
    second = env.post(f"/api/publications/solutions/{env.sol.id}", json={"notify_telegram": False})
    assert second.status_code == 200
    listed = env.get("/api/publications").json()
    assert [p["id"] for p in listed] == [second.json()["id"], first.json()["id"]]


def test_telegram_queue_only_pending_and_mark_is_idempotent(env):
    a = env.post(f"/api/publications/solutions/{env.sol.id}", json={}).json()
    (pending,) = env.get("/api/publications/pending-telegram").json()
    assert pending["id"] == a["id"] and pending["messages"][0]["teacher"] == "Γ. Παπαδόπουλος"
    assert env.post(f"/api/publications/{a['id']}/telegram-sent").status_code == 200
    assert env.post(f"/api/publications/{a['id']}/telegram-sent").status_code == 200
    assert env.get("/api/publications/pending-telegram").json() == []
    assert env.post("/api/publications/999/telegram-sent").status_code == 404


def test_archived_or_generating_or_missing_cannot_be_published(env):
    env.sol.archived_at = datetime(2026, 9, 1)
    env.s.commit()
    assert env.post(f"/api/publications/solutions/{env.sol.id}", json={}).json()["detail"]["code"] == "archived"
    env.sol.archived_at, env.sol.status = None, "generating"
    env.s.commit()
    assert env.get(f"/api/publications/preview/{env.sol.id}").json()["detail"]["code"] == "generating"
    assert env.post("/api/publications/solutions/999", json={}).status_code == 404


def test_recreated_card_at_same_hours_is_not_a_change():
    prev = [_e(1, 10, 1, "17:00", "18:00"), _e(1, 10, 3, "18:00", "19:00")]
    cur = [_e(1, 99, 1, "17:00", "18:00"), _e(1, 99, 3, "19:00", "20:00")]   # νέο id κάρτας
    ch = svc.teacher_changes(prev, cur)
    assert ch[1]["added"] == [] and ch[1]["removed"] == []
    assert [(m["from"]["start"], m["to"]["start"]) for m in ch[1]["moved"]] == [("18:00", "19:00")]
    assert svc.teacher_changes(prev, [dict(e, lesson_id=99) for e in prev]) == {}
