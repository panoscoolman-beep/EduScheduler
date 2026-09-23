"""EduScheduler → CRM ειδοποίηση μετά από αλλαγή μαθητή (χωρίς ping-pong)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import Student
from backend.routers import students as students_router
from backend.services import crm_student_notify as notify


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(Student(id=1, first_name="Νίκος", last_name="Π"))
    s.commit()
    app = FastAPI()
    app.include_router(students_router.router, prefix="/api/students")
    app.dependency_overrides[get_db] = lambda: (yield s)
    sent = []
    monkeypatch.setattr(notify, "notify_student_changed", lambda payload: sent.append(payload) or "ok")
    c = TestClient(app)
    c.sent = sent
    yield c
    s.close()


BODY = {"first_name": "Νικόλαος", "last_name": "Π", "email": None, "phone": "69",
        "grade": "Γ΄ Λυκείου", "track": None, "max_days_per_week": None}


def test_edit_in_eds_notifies_crm(client):
    assert client.put("/api/students/1", json=BODY).status_code == 200
    assert client.sent == [{"eds_id": 1, "first_name": "Νικόλαος", "last_name": "Π", "email": None,
                            "phone": "69", "grade": "Γ΄ Λυκείου", "track": None}]


def test_edit_that_came_from_crm_is_not_echoed_back(client):
    r = client.put("/api/students/1", json=BODY, headers={"X-Sync-Origin": "crm"})
    assert r.status_code == 200
    assert client.sent == []


def test_notify_is_disabled_without_token(monkeypatch):
    monkeypatch.setattr(notify, "_crm_config", lambda: ("http://crm", ""))
    assert notify.notify_student_changed({"eds_id": 1}) == "disabled"


def test_notify_is_fail_soft_when_crm_is_down(monkeypatch):
    monkeypatch.setattr(notify, "_crm_config", lambda: ("http://127.0.0.1:9", "tok"))
    assert notify.notify_student_changed({"eds_id": 1}) == "error"
