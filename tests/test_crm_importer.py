"""Tests για την εισαγωγή μαθητών από το Korifi CRM.

Η καρδιά (classify/commit) είναι pure/DB — δεν χρειάζεται ζωντανό CRM. Η
κλήση REST (fetch_crm_students) απομονώνεται και δεν τεστάρεται εδώ (I/O).
Στόχος: ποτέ διπλοεγγραφή, σωστή ελληνική αντιστοίχιση (τόνοι/κεφαλαία/ς).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import Student
from backend.services import crm_importer
from backend.routers import integration as integration_router


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


# ------------------------------ classify (pure) ------------------------------

def test_classify_new_vs_existing_greek_insensitive(db):
    db.add(Student(first_name="Νίκη", last_name="Κοντού"))
    db.commit()
    crm = [
        {"id": 1, "first_name": "ΝΙΚΗ", "last_name": "ΚΟΝΤΟΥ"},   # ίδιος (τόνοι/κεφαλαία)
        {"id": 2, "first_name": "Γιώργος", "last_name": "Παπαδόπουλος"},  # νέος
    ]
    rows = crm_importer.classify(crm, db.query(Student).all())
    by_name = {r.last_name: r for r in rows}
    assert by_name["ΚΟΝΤΟΥ"].status == "exists"
    assert by_name["ΚΟΝΤΟΥ"].eds_student_id is not None
    assert by_name["Παπαδόπουλος"].status == "new"


def test_classify_dedupes_crm_duplicates():
    # Το CRM στέλνει τον ίδιο μαθητή δύο φορές (2 εγγραφές τμημάτων).
    crm = [
        {"id": 1, "first_name": "Νίκη", "last_name": "Κοντού"},
        {"id": 1, "first_name": "Νίκη", "last_name": "Κοντού"},
    ]
    rows = crm_importer.classify(crm, [])
    assert len(rows) == 1 and rows[0].status == "new"


def test_classify_skips_incomplete_names():
    crm = [{"id": 1, "first_name": "", "last_name": "Κοντού"},
           {"id": 2, "first_name": "Γιώργος", "last_name": ""}]
    assert crm_importer.classify(crm, []) == []


# ------------------------------ commit (DB) ----------------------------------

def test_commit_inserts_new_only(db):
    db.add(Student(first_name="Νίκη", last_name="Κοντού"))
    db.commit()
    result = crm_importer.commit([
        {"first_name": "ΝΙΚΗ", "last_name": "ΚΟΝΤΟΥ", "email": "x@y.gr"},  # υπάρχει → skip
        {"first_name": "Γιώργος", "last_name": "Παπαδόπουλος", "phone": "690"},  # νέος
    ], db)
    assert result["status"] == "ok"
    assert result["created"] == 1 and result["skipped"] == 1
    names = {s.last_name for s in db.query(Student).all()}
    assert names == {"Κοντού", "Παπαδόπουλος"}


def test_commit_is_idempotent_on_rerun(db):
    payload = [{"first_name": "Άννα", "last_name": "Λέκκα"}]
    first = crm_importer.commit(payload, db)
    second = crm_importer.commit(payload, db)
    assert first["created"] == 1
    assert second["created"] == 0 and second["skipped"] == 1
    assert db.query(Student).count() == 1


def test_commit_dedupes_within_same_batch(db):
    result = crm_importer.commit([
        {"first_name": "Άννα", "last_name": "Λέκκα"},
        {"first_name": "άννα", "last_name": "λεκκα"},  # ίδιος στο batch
    ], db)
    assert result["created"] == 1 and result["skipped"] == 1
    assert db.query(Student).count() == 1


# ------------------------------ HTTP route -----------------------------------

@pytest.fixture()
def client(db, monkeypatch):
    app = FastAPI()
    app.include_router(integration_router.router, prefix="/api/integration")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_preview_route_reports_unavailable_without_crm(client, monkeypatch):
    # Χωρίς token/CRM: available=false με λόγο, όχι crash.
    monkeypatch.setattr(crm_importer, "fetch_crm_students",
                        lambda: ([], "Λείπει το KORIFI_API_TOKEN"))
    res = client.get("/api/integration/crm/students/preview")
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False
    assert "KORIFI_API_TOKEN" in body["fatal_error"]


def test_preview_route_classifies_when_crm_available(client, monkeypatch, db):
    db.add(Student(first_name="Νίκη", last_name="Κοντού"))
    db.commit()
    monkeypatch.setattr(crm_importer, "fetch_crm_students", lambda: ([
        {"id": 1, "first_name": "Νίκη", "last_name": "Κοντού"},
        {"id": 2, "first_name": "Μαρία", "last_name": "Λέκκα"},
    ], None))
    res = client.get("/api/integration/crm/students/preview")
    body = res.json()
    assert body["available"] is True
    assert body["new_count"] == 1 and body["exists_count"] == 1


def test_import_route_creates_students(client, db):
    res = client.post("/api/integration/crm/students/import", json={
        "students": [{"first_name": "Μαρία", "last_name": "Λέκκα", "email": "m@l.gr"}],
    })
    assert res.status_code == 200
    assert res.json()["created"] == 1
    assert db.query(Student).filter(Student.last_name == "Λέκκα").count() == 1
