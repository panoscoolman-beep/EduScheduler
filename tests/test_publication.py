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
    assert "  16:00–18:00 ΦΥΣΙΚΗ · Α" in m["message"]        # συνεχόμενες ώρες = ένα μπλοκ
    with_students = svc.build_messages(None, [dict(e, students=["Νίκος Π."]) for e in cur])[0]
    assert "      Νίκος Π." in with_students["message"]       # 👥 ονόματα αντί για τμήμα
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
    client.teacher_id = t.id
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


# --- 📨 Telegram μορφή + email ---------------------------------------------------

def test_telegram_format_is_compact_escaped_and_lists_changes_first():
    prev = [_e(1, 10, 1, "17:00", "18:00", label="Χ<b> (Β2)")]
    cur = [dict(_e(1, 10, 3, "18:00", "19:00", label="Χ<b> (Β2)"), subject="Χ<b>", klass="Β2", room_short="Α3")]
    (m,) = svc.build_messages(prev, cur)
    t = m["telegram"]
    assert t.index("Αλλαγές") < t.index("<b>Πέμπτη</b>")
    assert "Τρι 17:00 → Πεμ 18:00" in t and "<code>18–19</code> Χ&lt;b&gt; · Α3" in t
    assert "<i>Β2</i>" in t and "<b>Χ" not in t


def test_unchanged_teachers_are_listed_but_not_marked_changed():
    prev = [_e(1, 10, 1, "17:00", "18:00"), _e(2, 20, 2, "16:00", "17:00", teacher="Κ")]
    cur = [_e(1, 10, 3, "18:00", "19:00"), _e(2, 20, 2, "16:00", "17:00", teacher="Κ")]
    msgs = svc.build_messages(prev, cur)
    assert [(m["teacher_id"], m["changed"]) for m in msgs] == [(1, True), (2, False)]
    assert "Καμία αλλαγή" in msgs[1]["message"] and "Καμία αλλαγή" in msgs[1]["telegram"]


def _publish_with_email(env, monkeypatch, sender):
    monkeypatch.setattr(pub_router, "_send_emails_job",
                        lambda pid: svc.send_emails(env.s, pid, sender))
    return env.post(f"/api/publications/solutions/{env.sol.id}",
                    json={"email_teacher_ids": [env.teacher_id]})


def test_publish_sends_selected_emails_with_ics_and_records_status(env, monkeypatch):
    sent = []
    res = _publish_with_email(env, monkeypatch, lambda p: (sent.append(p), (True, None))[1])
    assert res.status_code == 200, res.text
    (p,) = sent
    assert p["to"] == "g@example.com" and p["first"] is True and p["test"] is False
    assert p["entries"] == [{"day": 0, "start": "16:00", "end": "17:00", "subject": "ΦΥΣΙΚΗ",
                             "klass": "Β2", "room": "Αίθ. Α", "color": "#000000"}]
    assert "BEGIN:VCALENDAR" in p["ics"]
    detail = env.get(f"/api/publications/{res.json()['id']}").json()
    assert detail["email_state"] == "done" and detail["emails"]["sent"] == 1
    assert detail["messages"][0]["email"]["status"] == "sent"
    assert "change_lines" not in detail["messages"][0]


def test_failed_email_is_recorded_and_telegram_waits_while_sending(env, monkeypatch):
    res = _publish_with_email(env, monkeypatch, lambda p: (False, "SMTP down"))
    d = env.get(f"/api/publications/{res.json()['id']}").json()
    assert d["emails"] == {"requested": 1, "sent": 0, "failed": 1, "pending": 0}
    assert d["messages"][0]["email"]["error"] == "SMTP down"
    assert len(env.get("/api/publications/pending-telegram").json()) == 1   # done → σύνοψη φεύγει
    from backend.models import SolutionPublication
    pub = env.s.get(SolutionPublication, res.json()["id"])
    pub.email_state = "sending"
    env.s.commit()
    assert env.get("/api/publications/pending-telegram").json() == []       # περιμένει τα email


def test_test_email_goes_only_to_given_address_and_publishes_nothing(env, monkeypatch):
    sent = []
    monkeypatch.setattr(pub_router.crm_mail, "send_teacher_schedule",
                        lambda p: (sent.append(p), (True, None))[1])
    res = env.post(f"/api/publications/preview/{env.sol.id}/test-email",
                   json={"teacher_id": env.teacher_id, "to": "me@example.com"})
    assert res.status_code == 200, res.text
    assert sent[0]["to"] == "me@example.com" and sent[0]["test"] is True
    assert env.get("/api/publications").json() == []
    bad = env.post(f"/api/publications/preview/{env.sol.id}/test-email",
                   json={"teacher_id": env.teacher_id, "to": "not-an-email"})
    assert bad.status_code == 422
    monkeypatch.setattr(pub_router.crm_mail, "send_teacher_schedule", lambda p: (False, "SMTP down"))
    fail = env.post(f"/api/publications/preview/{env.sol.id}/test-email",
                    json={"teacher_id": env.teacher_id, "to": "me@example.com"})
    assert fail.status_code == 502 and "SMTP down" in fail.json()["detail"]


def test_emails_for_existing_latest_publication_only(env, monkeypatch):
    sent = []
    monkeypatch.setattr(pub_router, "_send_emails_job",
                        lambda pid: svc.send_emails(env.s, pid, lambda p: (sent.append(p), (True, None))[1]))
    first = env.post(f"/api/publications/solutions/{env.sol.id}", json={}).json()   # χωρίς email
    assert first["emails"]["requested"] == 0 and sent == []
    res = env.post(f"/api/publications/{first['id']}/emails", json={"teacher_ids": [env.teacher_id]})
    assert res.status_code == 200, res.text
    assert [p["to"] for p in sent] == ["g@example.com"] and sent[0]["first"] is True
    assert env.get(f"/api/publications/{first['id']}").json()["emails"]["sent"] == 1
    # νεότερη δημοσίευση → η παλιά δεν στέλνει πια (θα ήταν ξεπερασμένο πρόγραμμα)
    env.slot.period_id = env.p2.id
    env.s.commit()
    env.post(f"/api/publications/solutions/{env.sol.id}", json={})
    old = env.post(f"/api/publications/{first['id']}/emails", json={"teacher_ids": [env.teacher_id]})
    assert old.status_code == 409 and old.json()["detail"]["code"] == "not_latest"
    assert env.post("/api/publications/999/emails", json={"teacher_ids": [1]}).status_code == 404


def test_emails_need_someone_with_an_address(env, monkeypatch):
    monkeypatch.setattr(pub_router, "_send_emails_job", lambda pid: None)
    pub = env.post(f"/api/publications/solutions/{env.sol.id}", json={}).json()
    res = env.post(f"/api/publications/{pub['id']}/emails", json={"teacher_ids": [12345]})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "no_recipients"


# --- G3-08: τμήμα + μαθητές στο «τι άλλαξε» -------------------------------------

def _ec(teacher_id, class_id, day, start, end, klass, students=(), ids=(), room="Α", subject="ΜΑΘ"):
    """Εγγραφή νέου στιγμιοτύπου (με class_id/student_ids)."""
    return dict(_e(teacher_id, 100 + class_id, day, start, end, label=f"{subject} ({klass})", room=room),
                subject=subject, klass=klass, class_id=class_id, students=list(students),
                student_ids=list(ids))


def test_swapping_the_hours_of_two_groups_is_a_change():
    prev = [_ec(1, 1, 0, "16:00", "17:00", "Α1", ["Άννα Χ."], [1]),
            _ec(1, 2, 2, "18:00", "19:00", "Β2", ["Γιώργος Χ."], [3])]
    cur = [_ec(1, 2, 0, "16:00", "17:00", "Β2", ["Γιώργος Χ."], [3]),
           _ec(1, 1, 2, "18:00", "19:00", "Α1", ["Άννα Χ."], [1])]
    (m,) = svc.build_messages(prev, cur)
    assert m["changed"] is True
    assert svc.change_lines(m["changes"]) == [
        "ΜΑΘ (Β2): Τετάρτη 18:00–19:00 → Δευτέρα 16:00–17:00 · Α",
        "ΜΑΘ (Α1): Δευτέρα 16:00–17:00 → Τετάρτη 18:00–19:00 · Α",
    ]
    assert "Τετ 18:00 → Δευ 16:00" in m["telegram"]


def test_two_groups_moving_are_paired_by_group_not_just_subject():
    prev = [_ec(1, 1, 0, "16:00", "17:00", "ΤΜ-Α"), _ec(1, 2, 2, "18:00", "19:00", "ΤΜ-Β")]
    cur = [_ec(1, 2, 3, "19:00", "20:00", "ΤΜ-Β"), _ec(1, 1, 4, "17:00", "18:00", "ΤΜ-Α")]
    assert svc.change_lines(svc.teacher_changes(prev, cur)[1]) == [
        "ΜΑΘ (ΤΜ-Β): Τετάρτη 18:00–19:00 → Πέμπτη 19:00–20:00 · Α",
        "ΜΑΘ (ΤΜ-Α): Δευτέρα 16:00–17:00 → Παρασκευή 17:00–18:00 · Α",
    ]


def test_new_student_in_a_group_is_a_change_with_one_line_for_all_its_hours():
    prev = [_ec(1, 2, 0, "16:00", "17:00", "Β2", ["Γιώργος Χ."], [3]),
            _ec(1, 2, 2, "18:00", "19:00", "Β2", ["Γιώργος Χ."], [3]),
            _ec(1, 1, 4, "16:00", "17:00", "Α1", ["Άννα Χ."], [1])]
    cur = [dict(e, students=["Γιώργος Χ.", "Δήμητρα Χ."], student_ids=[3, 4]) if e["class_id"] == 2 else e
           for e in prev]
    (m,) = svc.build_messages(prev, cur)
    assert m["changed"] is True
    assert svc.change_lines(m["changes"]) == [
        "👥 ΜΑΘ (Β2): Δευτέρα 16:00–17:00, Τετάρτη 18:00–19:00 — μαθητές: + Δήμητρα Χ."]
    assert "• 👥 ΜΑΘ: Δευ 16:00, Τετ 18:00 — μαθητές: + Δήμητρα Χ." in m["telegram"]
    left = [dict(e, students=[], student_ids=[]) if e["class_id"] == 1 else e for e in prev]
    assert svc.change_lines(svc.teacher_changes(prev, left)[1]) == [
        "👥 ΜΑΘ (Α1): Παρασκευή 16:00–17:00 — μαθητές: − Άννα Χ."]


def test_renamed_or_recreated_students_and_groups_are_not_changes():
    prev = [_ec(1, 2, 0, "16:00", "17:00", "Β2", ["Γιώργος Χ."], [3])]
    renamed_student = [_ec(1, 2, 0, "16:00", "17:00", "Β2", ["Γεώργιος Χ."], [3])]
    recreated_student = [_ec(1, 2, 0, "16:00", "17:00", "Β2", ["Γιώργος Χ."], [9])]
    renamed_group = [_ec(1, 2, 0, "16:00", "17:00", "Β2 Θετική", ["Γιώργος Χ."], [3])]
    recreated_group = [_ec(1, 7, 0, "16:00", "17:00", "Β2", ["Γιώργος Χ."], [3])]
    for cur in (renamed_student, recreated_student, renamed_group, recreated_group):
        assert svc.teacher_changes(prev, cur) == {}
    # Ξαναφτιαγμένο τμήμα ΜΕ άλλους μαθητές: μόνο «👥», όχι ψεύτικο «➖/➕».
    other = [_ec(1, 7, 0, "16:00", "17:00", "Β2", ["Νίκος Π."], [5])]
    ch = svc.teacher_changes(prev, other)[1]
    assert ch["added"] == [] and ch["removed"] == [] and ch["moved"] == []
    assert svc.change_lines(ch) == ["👥 ΜΑΘ (Β2): Δευτέρα 16:00–17:00 — μαθητές: + Νίκος Π. · − Γιώργος Χ."]


def test_previous_snapshot_without_class_ids_still_compares_as_before_plus_names():
    old = [dict(_e(1, 10, 0, "16:00", "17:00", label="ΜΑΘ (Παλιό όνομα)"), subject="ΜΑΘ",
                klass="Παλιό όνομα", students=["Γιώργος Χ."])]
    renamed = [_ec(1, 2, 0, "16:00", "17:00", "Β2", ["Γιώργος Χ."], [3])]
    assert svc.teacher_changes(old, renamed) == {}                 # μετονομασία ≠ αλλαγή
    joined = [_ec(1, 2, 0, "16:00", "17:00", "Β2", ["Γιώργος Χ.", "Δήμητρα Χ."], [3, 4])]
    assert svc.change_lines(svc.teacher_changes(old, joined)[1]) == [
        "👥 ΜΑΘ (Β2): Δευτέρα 16:00–17:00 — μαθητές: + Δήμητρα Χ."]
    very_old = [_e(1, 10, 0, "16:00", "17:00", label="ΜΑΘ (Β2)")]  # πριν τα ονόματα μαθητών
    assert svc.teacher_changes(very_old, joined) == {}


def test_new_student_makes_the_programme_publishable_again(env):
    from backend.models import SchoolClass, Student, StudentClassEnrollment

    assert env.post(f"/api/publications/solutions/{env.sol.id}", json={}).status_code == 200
    klass = env.s.query(SchoolClass).first()
    nikos = Student(first_name="Νίκος", last_name="Παππάς")
    env.s.add(nikos)
    env.s.commit()
    env.s.add(StudentClassEnrollment(student_id=nikos.id, class_id=klass.id))
    env.s.commit()
    prev = env.get(f"/api/publications/preview/{env.sol.id}").json()
    assert prev["affected"] == 1
    assert "👥 ΦΥΣΙΚΗ (Β2): Δευτέρα 16:00–17:00 — μαθητές: + Νίκος Π." in prev["teachers"][0]["message"]
    assert env.post(f"/api/publications/solutions/{env.sol.id}", json={}).status_code == 200


def test_resend_emails_the_published_programme_also_in_the_ics(env, monkeypatch):
    import re

    sent = []
    monkeypatch.setattr(pub_router, "_send_emails_job",
                        lambda pid: svc.send_emails(env.s, pid, lambda p: (sent.append(p), (True, None))[1]))
    first = env.post(f"/api/publications/solutions/{env.sol.id}", json={}).json()
    env.slot.period_id = env.p2.id            # το ζωντανό πρόγραμμα αλλάζει μετά τη δημοσίευση
    env.s.commit()
    res = env.post(f"/api/publications/{first['id']}/emails", json={"teacher_ids": [env.teacher_id]})
    assert res.status_code == 200, res.text
    (p,) = sent
    assert [e["start"] for e in p["entries"]] == ["16:00"]
    assert re.findall(r"DTSTART;TZID=Europe/Athens:\d{8}T(\d{4})", p["ics"]) == ["1600"]


# --- G3-11: συνεχόμενες ώρες με άλλους μαθητές -----------------------------------

def test_back_to_back_cards_with_other_students_are_not_merged():
    a = dict(_e(1, 10, 0, "16:00", "17:00"), students=["Άννα Χ.", "Βασίλης Χ."])
    b = dict(_e(1, 11, 0, "17:00", "18:00"), students=["Άννα Χ.", "Γιώργος Χ."])
    (m,) = svc.build_messages(None, [a, b])
    for text in (m["message"], m["telegram"]):
        assert "Βασίλης Χ." in text and "Γιώργος Χ." in text
    assert "16:00–18:00" not in m["message"] and "<code>16–18</code>" not in m["telegram"]
    (same,) = svc.build_messages(None, [a, dict(a, start="17:00", end="18:00", period_id=17)])
    assert "  16:00–18:00 ΦΥΣΙΚΗ · Α" in same["message"]       # δίωρο ίδιων μαθητών: ένα μπλοκ


# --- G3-10: μεγάλα τμήματα χωράνε στα όρια του CRM ----------------------------------

def test_email_payload_fits_the_crm_limits_for_big_groups():
    from pydantic import BaseModel, Field

    class CrmScheduleEntry(BaseModel):   # korifi-crm backend/routers/eds_mail.py (όρια)
        subject: str = Field(..., min_length=1, max_length=200)
        klass: str = Field("", max_length=200)
        room: str = Field("", max_length=100)

    names = [f"{n} Π." for n in ("Παναγιώτης", "Κωνσταντίνος", "Γεώργιος", "Δημήτριος", "Αικατερίνη",
                                  "Ελευθερία", "Μαρία", "Ελένη", "Ιωάννης", "Νικόλαος", "Αναστασία",
                                  "Χριστίνα", "Βασίλειος", "Σοφία", "Ευάγγελος", "Αθανάσιος",
                                  "Δέσποινα", "Θεοδώρα", "Μιχαήλ", "Στυλιανός")]
    big = dict(_e(1, 10, 0, "16:00", "17:00", room="Α" * 150), subject="ΦΥΣΙΚΗ", students=names)
    small = dict(_e(1, 11, 1, "16:00", "17:00"), subject="ΦΥΣΙΚΗ", students=names[:5])
    p = svc.email_payload(to="a@b.gr", teacher="Τ", title="Χ", note=None, changes=["x"] * 150,
                          first=False, entries=[big, small], ics=None)
    for e in p["entries"]:
        CrmScheduleEntry(**e)
    assert p["entries"][0]["klass"] == "Παναγιώτης Π., Κωνσταντίνος Π., Γεώργιος Π. +17"
    assert p["entries"][1]["klass"] == ", ".join(names[:5])          # μικρό τμήμα: όπως πριν
    assert len(p["changes"]) == 100 and p["changes"][-1].startswith("…και άλλες 51 αλλαγές")


# --- G3-09: αποστολή που «πέθανε» δεν μένει «sending» για πάντα ---------------------

def test_startup_recovery_releases_a_publication_stuck_in_sending(env, monkeypatch):
    monkeypatch.setattr(pub_router, "_send_emails_job", lambda pid: None)   # η αποστολή σκοτώθηκε
    pid = env.post(f"/api/publications/solutions/{env.sol.id}",
                   json={"email_teacher_ids": [env.teacher_id]}).json()["id"]
    assert env.get(f"/api/publications/{pid}").json()["email_state"] == "sending"
    assert env.post(f"/api/publications/{pid}/emails",
                    json={"teacher_ids": [env.teacher_id]}).json()["detail"]["code"] == "sending"

    assert svc.recover_interrupted_emails(env.s) == 1
    detail = env.get(f"/api/publications/{pid}").json()
    assert detail["email_state"] == "done"
    assert detail["emails"] == {"requested": 1, "sent": 0, "failed": 1, "pending": 0}
    assert detail["messages"][0]["email"]["error"] == svc.EMAIL_INTERRUPTED
    assert svc.recover_interrupted_emails(env.s) == 0                    # τίποτα δεν ξαναστέλνεται μόνο του

    sent = []
    monkeypatch.setattr(pub_router, "_send_emails_job",
                        lambda p: svc.send_emails(env.s, p, lambda x: (sent.append(x), (True, None))[1]))
    assert env.post(f"/api/publications/{pid}/emails", json={"teacher_ids": [env.teacher_id]}).status_code == 200
    assert len(sent) == 1 and env.get(f"/api/publications/{pid}").json()["emails"]["sent"] == 1


def test_crashing_email_job_marks_the_rest_failed_instead_of_sending_forever(env, monkeypatch):
    monkeypatch.setattr(pub_router, "_send_emails_job", lambda pid: None)
    pid = env.post(f"/api/publications/solutions/{env.sol.id}",
                   json={"email_teacher_ids": [env.teacher_id]}).json()["id"]
    monkeypatch.undo()

    def boom(*_args, **_kwargs):
        raise RuntimeError("η βάση έπεσε")
    monkeypatch.setattr(pub_router, "SessionLocal", lambda: env.s)
    monkeypatch.setattr(pub_router.pub_service, "send_emails", boom)
    pub_router._send_emails_job(pid)
    detail = env.get(f"/api/publications/{pid}").json()
    assert detail["email_state"] == "done" and detail["emails"]["failed"] == 1
    assert detail["messages"][0]["email"]["error"] == svc.EMAIL_ABORTED


def test_payload_error_fails_only_that_email(env, monkeypatch):
    monkeypatch.setattr(pub_router, "_send_emails_job", lambda pid: None)
    pid = env.post(f"/api/publications/solutions/{env.sol.id}",
                   json={"email_teacher_ids": [env.teacher_id]}).json()["id"]

    def broken_payload(**_kwargs):
        raise KeyError("room")
    monkeypatch.setattr(svc, "email_payload", broken_payload)
    svc.send_emails(env.s, pid, lambda p: (True, None))
    detail = env.get(f"/api/publications/{pid}").json()
    assert detail["email_state"] == "done" and detail["emails"]["failed"] == 1


def test_app_startup_runs_the_email_recovery(monkeypatch):
    import json

    from backend import main
    from backend.models import SolutionPublication

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    term = Term(name="Τ", is_active=True)
    s.add(term)
    s.commit()
    s.add(SolutionPublication(term_id=term.id, solution_name="Χ", snapshot_json="[]",
                              messages_json=json.dumps([{"teacher_id": 1, "teacher": "Τ",
                                                         "email": {"to": "t@x.gr", "status": "pending"}}]),
                              email_state="sending"))
    s.commit()
    monkeypatch.setattr(main, "engine", engine)
    with TestClient(main.app):
        pass
    s.expire_all()
    pub = s.query(SolutionPublication).one()
    assert pub.email_state == "done"
    assert json.loads(pub.messages_json)[0]["email"]["status"] == "failed"
    s.close()


# --- G3-12: παράλληλα αιτήματα σειριοποιούνται ανά σενάριο ------------------------

def test_publish_and_email_requests_lock_the_term_before_reading_the_latest(env, monkeypatch):
    calls = []
    real_latest = svc.latest_publication
    monkeypatch.setattr(svc, "_lock_term", lambda db, term_id: calls.append("lock"))
    monkeypatch.setattr(svc, "latest_publication",
                        lambda db, term_id: (calls.append("latest"), real_latest(db, term_id))[1])
    monkeypatch.setattr(pub_router, "_send_emails_job", lambda pid: None)
    pid = env.post(f"/api/publications/solutions/{env.sol.id}", json={}).json()["id"]
    assert calls and calls[0] == "lock"
    calls.clear()
    assert env.post(f"/api/publications/{pid}/emails", json={"teacher_ids": [env.teacher_id]}).status_code == 200
    assert calls and calls[0] == "lock"
