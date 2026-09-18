"""Ωράριο λειτουργίας: κρύβει ώρες εκτός ωραρίου από πλέγμα/εκτυπώσεις, ΠΟΤΕ
όμως ώρα που έχει τοποθετημένο μάθημα. Και οι ρυθμίσεις δεν «σβήνονται» από
παλιούς clients που δεν στέλνουν τα νέα πεδία."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, SchoolSettings, Subject, Teacher,
    TimetableSlot, TimetableSolution,
)
from backend.routers import exports as exports_router
from backend.routers import settings as settings_router
from backend.services.operating_hours import in_window, visible_periods


def test_in_window_rules():
    assert in_window("14:00", "14:00", "22:00") is True
    assert in_window("21:30", "14:00", "22:00") is True
    assert in_window("22:00", "14:00", "22:00") is False       # [from, to)
    assert in_window("08:00", "14:00", "22:00") is False
    assert in_window("08:00", None, None) is True               # χωρίς ωράριο → όλες
    assert in_window("", "14:00", "22:00") is True              # άγνωστη ώρα → φαίνεται


def test_visible_periods_never_hides_a_period_with_a_lesson():
    p = [NS(id=1, start_time="08:00"), NS(id=2, start_time="09:00"), NS(id=3, start_time="14:00")]
    assert [x.id for x in visible_periods(p, "14:00", "22:00")] == [3]
    assert [x.id for x in visible_periods(p, "14:00", "22:00", {2})] == [2, 3]
    assert [x.id for x in visible_periods(p, None, None)] == [1, 2, 3]


@pytest.fixture()
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    subj = Subject(name="Άλγεβρα", short_name="ΑΛΓ", color="#000")
    teacher = Teacher(name="Καθ", short_name="Κ", color="#000")
    cls = SchoolClass(name="Β2", short_name="Β2")
    room = Classroom(name="Α1", short_name="Α1", room_type="regular")
    periods = [Period(name=n, short_name=n, start_time=a, end_time=b, is_break=False, sort_order=i)
               for i, (n, a, b) in enumerate([("1η", "08:00", "09:00"), ("2η", "09:00", "10:00"),
                                              ("7η", "14:00", "15:00")])]
    s.add_all([subj, teacher, cls, room, *periods])
    s.commit()
    sol = TimetableSolution(name="Π", status="optimal")
    lesson = Lesson(subject_id=subj.id, teacher_id=teacher.id, class_id=cls.id, periods_per_week=1)
    s.add_all([sol, lesson])
    s.commit()
    # Μάθημα Σαββάτου στις 09:00 — εκτός ωραρίου, πρέπει να ΦΑΙΝΕΤΑΙ.
    s.add(TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=0,
                        period_id=periods[1].id, classroom_id=room.id, is_unplaced=False))
    s.add(SchoolSettings(id=1, school_name="Κορυφή", days_per_week=6))
    s.commit()

    app = FastAPI()
    app.include_router(settings_router.router, prefix="/api/settings")
    app.include_router(exports_router.router, prefix="/api/exports")

    def override_db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session, c.sol, c.teacher = s, sol, teacher
    yield c
    s.close()


def _put(c, **fields):
    body = {"school_name": "Κορυφή", "days_per_week": 6, "institution_type": "frontistirio", **fields}
    return c.put("/api/settings/", json=body)


def test_settings_store_and_validate_the_window(client):
    res = _put(client, visible_from="14:00", visible_to="22:00")
    assert res.status_code == 200
    assert (res.json()["visible_from"], res.json()["visible_to"]) == ("14:00", "22:00")
    assert _put(client, visible_from="25:00").status_code == 422
    assert _put(client, visible_from="22:00", visible_to="14:00").status_code == 422


def test_old_clients_without_the_new_fields_do_not_wipe_the_window(client):
    _put(client, visible_from="14:00", visible_to="22:00")
    res = _put(client, school_name="Κορυφή 2")                  # χωρίς visible_*
    assert res.json()["school_name"] == "Κορυφή 2"
    assert (res.json()["visible_from"], res.json()["visible_to"]) == ("14:00", "22:00")
    cleared = _put(client, visible_from=None, visible_to=None)  # ρητό κενό → όλες
    assert cleared.json()["visible_from"] is None


def test_print_hides_empty_morning_hours_but_keeps_ones_with_lessons(client):
    url = f"/api/exports/print?solution_id={client.sol.id}&teacher_id={client.teacher.id}"
    before = client.get(url).text
    assert "08:00–09:00" in before and "09:00–10:00" in before and "14:00–15:00" in before

    _put(client, visible_from="14:00", visible_to="22:00")
    after = client.get(url).text
    assert "08:00–09:00" not in after                           # άδεια πρωινή ώρα → κρυφή
    assert "09:00–10:00" in after                               # έχει μάθημα → φαίνεται
    assert "14:00–15:00" in after
