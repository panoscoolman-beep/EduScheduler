"""Καθημερινές αλλαγές που έβγαζαν σκέτο «Σφάλμα 500» (G2-13) + τηλέφωνα (G2-10).

Διπλή συντομογραφία στο PUT, άγνωστη αίθουσα βάσης / ώρα διαθεσιμότητας,
υπερβολικά μεγάλα πεδία → τώρα 409 / 400 / 422 με εξήγηση. Τα έγκυρα δεδομένα
συμπεριφέρονται ακριβώς όπως πριν. SQLite με FK ON (όπως το Postgres).
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
    Classroom, Period, SchoolClass, SchoolSettings, Student, Subject, Teacher, Term,
)
from backend.routers import classes as classes_router
from backend.routers import classrooms as classrooms_router
from backend.routers import settings as settings_router
from backend.routers import students as students_router
from backend.routers import subjects as subjects_router
from backend.routers import teachers as teachers_router


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
    s.add_all([Term(name="Σενάριο", is_active=True), SchoolSettings(id=1, school_name="Κ")])
    s.add_all([
        Teacher(name="Α", short_name="ΤΑ", color="#000000"),
        Teacher(name="Β", short_name="ΤΒ", color="#000000"),
        Subject(name="Φυσική", short_name="ΦΥΣ"), Subject(name="Χημεία", short_name="ΧΗΜ"),
        Classroom(name="R1", short_name="R1"), Classroom(name="R2", short_name="R2"),
        SchoolClass(name="Α1", short_name="Α1"), SchoolClass(name="Β2", short_name="Β2"),
        Period(name="1η", short_name="1", start_time="14:00", end_time="15:00", sort_order=1),
        Student(first_name="Άννα", last_name="Χ"),
    ])
    s.commit()
    app = FastAPI()
    for prefix, mod in (("/api/teachers", teachers_router), ("/api/subjects", subjects_router),
                        ("/api/classrooms", classrooms_router), ("/api/classes", classes_router),
                        ("/api/settings", settings_router), ("/api/students", students_router)):
        app.include_router(mod.router, prefix=prefix)

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app, raise_server_exceptions=False)
    c.s = s
    yield c
    s.close()


def _id(env, model, short):
    return env.s.query(model).filter(model.short_name == short).first().id


@pytest.mark.parametrize("path,model,mine,taken,extra", [
    ("teachers", Teacher, "ΤΒ", "ΤΑ", {"name": "Β"}),
    ("subjects", Subject, "ΧΗΜ", "ΦΥΣ", {"name": "Χημεία"}),
    ("classrooms", Classroom, "R2", "R1", {"name": "R2"}),
    ("classes", SchoolClass, "Β2", "Α1", {"name": "Β2"}),
])
def test_put_with_a_short_name_that_already_exists_is_409(env, path, model, mine, taken, extra):
    oid = _id(env, model, mine)
    res = env.put(f"/api/{path}/{oid}", json={**extra, "short_name": taken})
    assert res.status_code == 409 and f"'{taken}'" in res.json()["detail"]
    env.s.expire_all()
    assert env.s.get(model, oid).short_name == mine                     # τίποτα δεν άλλαξε
    # Το ίδιο το δικό του short_name (αποθήκευση χωρίς αλλαγή) περνά όπως πριν.
    assert env.put(f"/api/{path}/{oid}", json={**extra, "short_name": mine}).status_code == 200


def test_unknown_home_room_is_400(env):
    assert env.post("/api/classes/", json={"name": "Γ", "short_name": "Γ3",
                                           "home_room_id": 999999}).status_code == 400
    cid = _id(env, SchoolClass, "Β2")
    res = env.put(f"/api/classes/{cid}", json={"name": "Β2", "short_name": "Β2",
                                               "home_room_id": 999999})
    assert res.status_code == 400 and "αίθουσα" in res.json()["detail"]
    ok = env.put(f"/api/classes/{cid}", json={"name": "Β2", "short_name": "Β2",
                                              "home_room_id": _id(env, Classroom, "R1")})
    assert ok.status_code == 200


@pytest.mark.parametrize("who", ["teachers", "students"])
def test_availability_with_an_unknown_period_is_400(env, who):
    oid = (env.s.query(Teacher).first() if who == "teachers" else env.s.query(Student).first()).id
    res = env.put(f"/api/{who}/{oid}/availability", json={"availabilities": [
        {"day_of_week": 0, "period_id": 999999, "status": "unavailable"}]})
    assert res.status_code == 400 and "999999" in res.json()["detail"]
    pid = env.s.query(Period).first().id
    ok = env.put(f"/api/{who}/{oid}/availability", json={"availabilities": [
        {"day_of_week": 0, "period_id": pid, "status": "unavailable"}]})
    assert ok.status_code == 200


def test_academic_year_longer_than_the_column_is_422(env):
    res = env.put("/api/settings/", json={"academic_year": "Σχολικό έτος 2026-2027"})
    assert res.status_code == 422
    assert env.put("/api/settings/", json={"academic_year": "2026-2027"}).status_code == 200


@pytest.mark.parametrize("path,body", [
    ("subjects", {"name": "Χ", "short_name": "Χ1", "special_room_type": "x" * 51}),
    ("classrooms", {"name": "Χ", "short_name": "Χ1", "building": "x" * 101}),
    ("teachers", {"name": "Χ", "short_name": "Χ1", "email": "x" * 201}),
])
def test_overlong_free_text_is_422(env, path, body):
    assert env.post(f"/api/{path}/", json=body).status_code == 422


# ─── G2-10: τηλέφωνα έως 100 χαρακτήρες, όπως στο CRM ─────────────────────────

LONG_PHONE = "6971234567 / 6987654321 (μητέρα)"     # 32 χαρακτήρες — έσκαγε με 500


def test_phone_columns_hold_100_characters():
    assert Student.__table__.c.phone.type.length == 100
    assert Teacher.__table__.c.phone.type.length == 100


def test_long_phones_are_accepted_and_overlong_ones_are_422(env):
    assert env.post("/api/students/", json={"first_name": "Α", "last_name": "Β",
                                            "phone": LONG_PHONE}).status_code == 201
    assert env.post("/api/teachers/", json={"name": "Τ", "short_name": "Τ9",
                                            "phone": "9" * 100}).status_code == 201
    assert env.post("/api/students/", json={"first_name": "Α", "last_name": "Β",
                                            "phone": "9" * 101}).status_code == 422
