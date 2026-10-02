"""Επεξεργασία μαθήματος-κάρτας από τη φόρμα: τίποτα δεν χάνεται σιωπηλά.

G3-00 / G2-08: το API δεν επέστρεφε ποτέ το `distribution`, οπότε η φόρμα
άνοιγε με κενή «Κατανομή» και ΚΑΘΕ αποθήκευση (π.χ. αλλαγή καθηγητή) έσβηνε
τα δίωρα («2,2» → μονόωρα στον solver).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import Classroom, Lesson, SchoolClass, Subject, Teacher, Term
from backend.routers import lessons as lessons_router


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(Term(name="Σενάριο", is_active=True))
    subj = Subject(name="ΦΥΣΙΚΗ", short_name="ΦΥΣ", color="#000000")
    t1 = Teacher(name="Τ1", short_name="Τ1", color="#000000")
    t2 = Teacher(name="Τ2", short_name="Τ2", color="#000000")
    cls = SchoolClass(name="Β2", short_name="Β2")
    room = Classroom(name="R1", short_name="R1", room_type="regular")
    s.add_all([subj, t1, t2, cls, room])
    s.commit()
    app = FastAPI()
    app.include_router(lessons_router.router, prefix="/api/lessons")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app, raise_server_exceptions=False)
    c.s, c.subj, c.t1, c.t2, c.cls, c.room = s, subj, t1, t2, cls, room
    yield c
    s.close()


def _form_payload(row: dict, **changes) -> dict:
    """Ό,τι στέλνει το LessonsView._parseForm όταν η φόρμα γεμίζει από τη γραμμή
    της λίστας (f-dist = item.distribution || '' → '' γίνεται null)."""
    payload = {
        "subject_id": row["subject_id"], "teacher_id": row["teacher_id"],
        "class_id": row["class_id"], "classroom_id": row["classroom_id"],
        "periods_per_week": row["periods_per_week"], "duration": 1,
        "distribution": (row.get("distribution") or "").strip() or None,
        "is_locked": row["is_locked"],
    }
    payload.update(changes)
    return payload


def test_editing_a_lesson_keeps_its_block_distribution(env):
    created = env.post("/api/lessons/", json={
        "subject_id": env.subj.id, "teacher_id": env.t1.id, "class_id": env.cls.id,
        "periods_per_week": 4, "distribution": "2,2"})
    assert created.status_code == 201, created.text
    assert created.json()["distribution"] == "2,2"
    lid = created.json()["id"]
    assert env.get(f"/api/lessons/{lid}").json()["distribution"] == "2,2"
    row = next(r for r in env.get("/api/lessons/").json() if r["id"] == lid)
    assert row["distribution"] == "2,2"

    res = env.put(f"/api/lessons/{lid}", json=_form_payload(row, teacher_id=env.t2.id))
    assert res.status_code == 200, res.text
    assert res.json()["distribution"] == "2,2"
    env.s.expire_all()
    stored = env.s.get(Lesson, lid)
    assert (stored.distribution, stored.teacher_id) == ("2,2", env.t2.id)


def test_clearing_the_distribution_on_purpose_still_works(env):
    lid = env.post("/api/lessons/", json={
        "subject_id": env.subj.id, "teacher_id": env.t1.id, "class_id": env.cls.id,
        "periods_per_week": 2, "distribution": "2"}).json()["id"]
    row = next(r for r in env.get("/api/lessons/").json() if r["id"] == lid)
    assert env.put(f"/api/lessons/{lid}", json=_form_payload(row, distribution=None)).status_code == 200
    env.s.expire_all()
    assert env.s.get(Lesson, lid).distribution is None


@pytest.mark.parametrize("field,detail", [
    ("teacher_id", "Ο καθηγητής δεν βρέθηκε"),
    ("subject_id", "Το μάθημα δεν βρέθηκε"),
    ("class_id", "Η τάξη δεν βρέθηκε"),
    ("classroom_id", "Η αίθουσα δεν βρέθηκε"),
])
def test_editing_with_an_unknown_reference_is_404_not_500(env, field, detail):
    lid = env.post("/api/lessons/", json={
        "subject_id": env.subj.id, "teacher_id": env.t1.id, "class_id": env.cls.id}).json()["id"]
    row = next(r for r in env.get("/api/lessons/").json() if r["id"] == lid)
    res = env.put(f"/api/lessons/{lid}", json=_form_payload(row, **{field: 999999}))
    assert res.status_code == 404 and res.json()["detail"] == detail
    env.s.expire_all()
    assert env.s.get(Lesson, lid).teacher_id == env.t1.id


def test_overlong_distribution_is_422_not_500(env):
    res = env.post("/api/lessons/", json={
        "subject_id": env.subj.id, "teacher_id": env.t1.id, "class_id": env.cls.id,
        "distribution": "1," * 30})
    assert res.status_code == 422
