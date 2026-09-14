"""Κατάλογος τάξεων/κατευθύνσεων + ο κανόνας «track μόνο όπου έχει νόημα»."""
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
from backend.schemas import StudentCreate
from backend.services import grade_catalog as gc


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    app = FastAPI()
    app.include_router(students_router.router, prefix="/api/students")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session = s
    yield c
    s.close()


# ─── κατάλογος ─────────────────────────────────────────────────────────

def test_grades_are_in_school_order_and_cover_dimotiko_to_epal():
    assert gc.GRADES == [
        "Ε΄ Δημοτικού", "ΣΤ΄ Δημοτικού",
        "Α΄ Γυμνασίου", "Β΄ Γυμνασίου", "Γ΄ Γυμνασίου",
        "Α΄ Λυκείου", "Α΄ ΕΠΑΛ",
        "Β΄ Λυκείου", "Β΄ ΕΠΑΛ",
        "Γ΄ Λυκείου", "Γ΄ ΕΠΑΛ",
    ]


def test_only_b_c_lykeiou_and_epal_have_tracks():
    with_tracks = [g for g in gc.GRADES if gc.has_tracks(g)]
    assert with_tracks == ["Β΄ Λυκείου", "Β΄ ΕΠΑΛ", "Γ΄ Λυκείου", "Γ΄ ΕΠΑΛ"]
    for g in ("Ε΄ Δημοτικού", "Α΄ Γυμνασίου", "Α΄ Λυκείου", "Α΄ ΕΠΑΛ"):
        assert gc.tracks_for(g) == []


def test_track_contents_per_grade():
    assert gc.tracks_for("Β΄ Λυκείου") == [
        "Θετικών Σπουδών (Θετική)", "Ανθρωπιστικών Σπουδών (Θεωρητική)",
    ]
    assert len(gc.tracks_for("Γ΄ Λυκείου")) == 4
    assert any("Υγείας" in t for t in gc.tracks_for("Γ΄ Λυκείου"))
    assert any("Οικονομίας" in t for t in gc.tracks_for("Γ΄ Λυκείου"))
    # ΕΠΑΛ: ίδιοι τομείς σε Β΄ και Γ΄
    assert gc.tracks_for("Β΄ ΕΠΑΛ") == gc.tracks_for("Γ΄ ΕΠΑΛ")
    assert len(gc.tracks_for("Β΄ ΕΠΑΛ")) == 9
    assert "Πληροφορικής" in gc.tracks_for("Β΄ ΕΠΑΛ")
    assert "Διοίκησης και Οικονομίας" in gc.tracks_for("Β΄ ΕΠΑΛ")


def test_track_label_is_katefthinsi_for_gel_and_tomeas_for_epal():
    assert gc.track_label("Γ΄ Λυκείου") == "Κατεύθυνση"
    assert gc.track_label("Γ΄ ΕΠΑΛ") == "Τομέας"
    assert gc.track_label("Α΄ Γυμνασίου") == gc.DEFAULT_TRACK_LABEL


def test_clean_track_drops_values_that_cannot_apply():
    assert gc.clean_track("Β΄ Λυκείου", "Θετικών Σπουδών (Θετική)") == "Θετικών Σπουδών (Θετική)"
    assert gc.clean_track("Α΄ Λυκείου", "Θετικών Σπουδών (Θετική)") is None   # δεν έχει κατεύθυνση
    assert gc.clean_track("Β΄ Λυκείου", "   ") is None
    assert gc.clean_track(None, "οτιδήποτε") is None
    # Ελεύθερο κείμενο (π.χ. ειδικότητα ΕΠΑΛ) επιτρέπεται όπου υπάρχουν τομείς.
    assert gc.clean_track("Γ΄ ΕΠΑΛ", "Τεχνικός Η/Υ") == "Τεχνικός Η/Υ"


# ─── endpoint + persistence ────────────────────────────────────────────

def test_grade_options_endpoint_serves_the_catalog(client):
    res = client.get("/api/students/grade-options")
    assert res.status_code == 200
    body = res.json()
    assert body["grades"] == gc.GRADES
    assert body["tracks"]["Γ΄ ΕΠΑΛ"] == gc.tracks_for("Γ΄ ΕΠΑΛ")
    assert body["track_labels"]["Β΄ ΕΠΑΛ"] == "Τομέας"
    assert body["default_track_label"] == gc.DEFAULT_TRACK_LABEL


def test_students_list_is_alphabetical_by_surname_then_first_name(client):
    for last, first in (("Παπαδόπουλος", "Νίκος"), ("Αλεξίου", "Μαρία"),
                        ("Ζήσης", "Κώστας"), ("Αλεξίου", "Άννα")):
        client.session.add(Student(first_name=first, last_name=last))
    client.session.commit()
    res = client.get("/api/students/")
    assert res.status_code == 200
    assert [(s["last_name"], s["first_name"]) for s in res.json()] == [
        ("Αλεξίου", "Άννα"), ("Αλεξίου", "Μαρία"), ("Ζήσης", "Κώστας"), ("Παπαδόπουλος", "Νίκος"),
    ]


def test_grade_options_is_not_shadowed_by_the_student_id_route(client):
    """Το /grade-options δηλώνεται ΠΡΙΝ το /{student_id} — αλλιώς θα έπεφτε
    στο path parameter και θα γύριζε 422."""
    assert client.get("/api/students/grade-options").status_code == 200


def test_create_and_update_keep_track_only_where_it_applies(client):
    res = client.post("/api/students/", json={
        "first_name": "Νίκος", "last_name": "Π", "grade": "Γ΄ Λυκείου",
        "track": "Σπουδών Υγείας (3ο πεδίο)",
    })
    assert res.status_code == 201
    sid = res.json()["id"]
    assert res.json()["track"] == "Σπουδών Υγείας (3ο πεδίο)"

    # Αλλαγή σε τάξη χωρίς κατευθύνσεις: η παλιά κατεύθυνση ΔΕΝ μένει πίσω.
    res = client.put(f"/api/students/{sid}", json={
        "first_name": "Νίκος", "last_name": "Π", "grade": "Α΄ Λυκείου",
        "track": "Σπουδών Υγείας (3ο πεδίο)",
    })
    assert res.status_code == 200 and res.json()["track"] is None
    assert client.session.query(Student).filter(Student.id == sid).first().track is None


def test_schema_validator_normalises_track_without_a_request():
    assert StudentCreate(first_name="A", last_name="B", grade="Α΄ ΕΠΑΛ",
                         track="Μηχανολογίας").track is None
    assert StudentCreate(first_name="A", last_name="B", grade="Β΄ ΕΠΑΛ",
                         track=" Μηχανολογίας ").track == "Μηχανολογίας"
