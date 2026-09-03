"""Εγγραφές μαθητών σε τμήμα: PUT γράφει μόνο διαφορές, POST/DELETE
μεμονωμένα (idempotent), άγνωστα ids → 400, student_count πάντα από τις
εγγραφές, `student_ids` απόν στο PUT = καμία αλλαγή.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import SchoolClass, Student, StudentClassEnrollment
from backend.routers import classes as classes_router
from backend.routers import students as students_router


@pytest.fixture()
def env():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    students = [
        Student(first_name="Νίκος", last_name="Αλεξίου"),
        Student(first_name="Μαρία", last_name="Βασιλείου"),
        Student(first_name="Κώστας", last_name="Γεωργίου"),
    ]
    s.add_all(students)
    s.commit()
    for st in students:
        s.refresh(st)

    app = FastAPI()
    app.include_router(classes_router.router, prefix="/api/classes")
    app.include_router(students_router.router, prefix="/api/students")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.s = s
    client.students = students
    yield client
    s.close()


def _ids(env):
    return [st.id for st in env.students]


def _create(env, student_ids, short="Α1"):
    res = env.post("/api/classes/", json={
        "name": f"Τμήμα {short}", "short_name": short, "student_ids": student_ids,
    })
    assert res.status_code == 201, res.text
    return res.json()


def _enrollments(env, class_id):
    return {
        e.student_id: e.enrolled_at
        for e in env.s.query(StudentClassEnrollment)
        .filter(StudentClassEnrollment.class_id == class_id).all()
    }


def test_create_enrolls_dedups_and_counts_from_enrollments(env):
    a, b, _ = _ids(env)
    body = _create(env, [a, b, a])
    assert sorted(body["student_ids"]) == sorted([a, b])
    assert body["student_count"] == 2  # όχι 3, όχι ό,τι στείλει ο client


def test_create_with_unknown_student_is_400_not_500(env):
    res = env.post("/api/classes/", json={
        "name": "Χ", "short_name": "Χ", "student_ids": [9999],
    })
    assert res.status_code == 400
    assert "9999" in res.json()["detail"]
    assert env.s.query(SchoolClass).count() == 0  # τίποτα δεν γράφτηκε


def test_put_writes_only_the_diff_and_keeps_enrolled_at(env):
    a, b, c = _ids(env)
    cls = _create(env, [a, b])
    before = _enrollments(env, cls["id"])

    res = env.put(f"/api/classes/{cls['id']}", json={
        "name": cls["name"], "short_name": cls["short_name"], "student_ids": [b, c],
    })
    assert res.status_code == 200
    assert sorted(res.json()["student_ids"]) == sorted([b, c])
    assert res.json()["student_count"] == 2

    after = _enrollments(env, cls["id"])
    assert a not in after and c in after
    assert after[b] == before[b]  # ο b έμεινε — ίδιο enrolled_at


def test_put_without_student_ids_leaves_enrollments_alone(env):
    a, b, _ = _ids(env)
    cls = _create(env, [a, b])
    res = env.put(f"/api/classes/{cls['id']}", json={
        "name": "Νέο όνομα", "short_name": cls["short_name"],
    })
    assert res.status_code == 200
    assert res.json()["name"] == "Νέο όνομα"
    assert sorted(res.json()["student_ids"]) == sorted([a, b])  # δεν άδειασε
    assert res.json()["student_count"] == 2


def test_put_with_empty_list_empties_the_class_explicitly(env):
    a, _, _ = _ids(env)
    cls = _create(env, [a])
    res = env.put(f"/api/classes/{cls['id']}", json={
        "name": cls["name"], "short_name": cls["short_name"], "student_ids": [],
    })
    assert res.status_code == 200
    assert res.json()["student_ids"] == [] and res.json()["student_count"] == 0


def test_put_student_count_in_body_is_ignored(env):
    a, _, _ = _ids(env)
    cls = _create(env, [a])
    res = env.put(f"/api/classes/{cls['id']}", json={
        "name": cls["name"], "short_name": cls["short_name"],
        "student_ids": [a], "student_count": 42,
    })
    assert res.json()["student_count"] == 1


def test_enroll_and_unenroll_single_student_idempotent(env):
    a, b, _ = _ids(env)
    cls = _create(env, [a])

    res = env.post(f"/api/classes/{cls['id']}/students/{b}")
    assert res.status_code == 200
    assert sorted(res.json()["student_ids"]) == sorted([a, b])
    assert res.json()["student_count"] == 2

    # ξανά — καμία αλλαγή, κανένα 500 από το unique constraint
    res = env.post(f"/api/classes/{cls['id']}/students/{b}")
    assert res.status_code == 200
    assert res.json()["student_count"] == 2

    res = env.delete(f"/api/classes/{cls['id']}/students/{a}")
    assert res.status_code == 200
    assert res.json()["student_ids"] == [b]
    assert res.json()["student_count"] == 1

    # αφαίρεση κάποιου που δεν είναι μέσα — 200, τίποτα δεν αλλάζει
    res = env.delete(f"/api/classes/{cls['id']}/students/{a}")
    assert res.status_code == 200
    assert res.json()["student_count"] == 1


def test_enroll_404s_for_unknown_class_or_student(env):
    a, _, _ = _ids(env)
    cls = _create(env, [])
    assert env.post(f"/api/classes/9999/students/{a}").status_code == 404
    assert env.post(f"/api/classes/{cls['id']}/students/9999").status_code == 404
    assert env.delete(f"/api/classes/{cls['id']}/students/9999").status_code == 404


def test_list_class_students_sorted_and_student_class_ids_reflect_membership(env):
    a, b, c = _ids(env)
    cls = _create(env, [c, a])
    res = env.get(f"/api/classes/{cls['id']}/students")
    assert res.status_code == 200
    assert [s["last_name"] for s in res.json()] == ["Αλεξίου", "Γεωργίου"]

    res = env.get(f"/api/students/{b}")
    assert res.json()["class_ids"] == []
    res = env.get(f"/api/students/{a}")
    assert res.json()["class_ids"] == [cls["id"]]


def test_deleting_a_student_cascades_enrollment_and_count_resyncs_on_next_write(env):
    a, b, _ = _ids(env)
    cls = _create(env, [a, b])
    assert env.delete(f"/api/students/{a}").status_code == 204
    # Το cascade έφυγε την εγγραφή· το count ξανασυγχρονίζεται στο επόμενο PUT.
    res = env.put(f"/api/classes/{cls['id']}", json={
        "name": cls["name"], "short_name": cls["short_name"],
    })
    assert res.json()["student_ids"] == [b]
    assert res.json()["student_count"] == 1
