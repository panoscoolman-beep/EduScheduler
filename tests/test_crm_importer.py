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


# ------------------- συνδέσεις του CRM (🔗 με άλλη γραφή) ---------------------

def _eds(db, first, last):
    s = Student(first_name=first, last_name=last)
    db.add(s)
    db.commit()
    return s.id


def test_crm_link_wins_over_a_different_spelling(db):
    """CRM «Γεώργιος» συνδεδεμένος (🔗) με τον «Γιώργο» του EDS → υπάρχει ήδη,
    ΟΧΙ νέος (έως 2/10/2026 η εισαγωγή τον έφτιαχνε δεύτερη φορά)."""
    eds_id = _eds(db, "Γιώργος", "Παπαδόπουλος")
    crm = [{"id": 1, "first_name": "Γεώργιος", "last_name": "Παπαδόπουλος"}]
    (row,) = crm_importer.classify(crm, db.query(Student).all(), {1: eds_id})
    assert (row.status, row.eds_student_id, row.crm_id) == ("exists", eds_id, 1)
    assert row.first_name == "Γεώργιος"                   # τα στοιχεία του CRM, όπως πριν


def test_stale_link_falls_back_to_the_name(db):
    """Σύνδεση προς μαθητή που σβήστηκε από το EDS δεν «κρύβει» τον μαθητή."""
    crm = [{"id": 1, "first_name": "Γεώργιος", "last_name": "Παπαδόπουλος"}]
    (row,) = crm_importer.classify(crm, db.query(Student).all(), {1: 777})
    assert (row.status, row.eds_student_id) == ("new", None)
    same = _eds(db, "ΓΕΩΡΓΙΟΣ", "ΠΑΠΑΔΟΠΟΥΛΟΣ")
    (row,) = crm_importer.classify(crm, db.query(Student).all(), {1: 777})
    assert (row.status, row.eds_student_id) == ("exists", same)


def test_without_links_classification_is_exactly_as_before(db):
    _eds(db, "Νίκη", "Κοντού")
    _eds(db, "Γιώργος", "Παπαδόπουλος")
    crm = [{"id": 3, "first_name": "Μαρία", "last_name": "Λέκκα"},
           {"id": 1, "first_name": "Γεώργιος", "last_name": "Παπαδόπουλος"},
           {"id": 2, "first_name": "ΝΙΚΗ", "last_name": "ΚΟΝΤΟΥ"},
           {"id": 4, "first_name": "Γεώργιος", "last_name": "Παπαδόπουλος"}]
    eds = db.query(Student).all()
    before = [r.to_dict() for r in crm_importer.classify(crm, eds)]
    for links in (None, {}, {99: 1}):
        assert [r.to_dict() for r in crm_importer.classify(crm, eds, links)] == before
    assert [(r.crm_id, r.status) for r in crm_importer.classify(crm, eds)] == \
        [(1, "new"), (3, "new"), (2, "exists")]          # #4 = διπλός του #1 → μία φορά


def test_linked_student_is_kept_over_an_unlinked_namesake_whatever_the_order(db):
    """Διπλοεγγραφή στο CRM (ίδιο όνομα): ο συνδεδεμένος κρατιέται → 'exists',
    ο ασύνδετος συνονόματος δεν προτείνεται ως νέος (κρατιέται το de-dup)."""
    eds_id = _eds(db, "Άγγελος", "Ναλμπάντη")
    crm = [{"id": 1029, "first_name": "ΑΓΓΕΛΟΣ", "last_name": "ΝΑΛΜΠΑΝΤΗΣ"},
           {"id": 1020, "first_name": "ΑΓΓΕΛΟΣ", "last_name": "ΝΑΛΜΠΑΝΤΗΣ"}]
    for order in (crm, crm[::-1]):
        rows = crm_importer.classify(order, db.query(Student).all(), {1020: eds_id})
        assert [(r.crm_id, r.status, r.eds_student_id) for r in rows] == \
            [(1020, "exists", eds_id)]


def test_preview_route_uses_crm_links(client, monkeypatch, db):
    eds_id = _eds(db, "Γιώργος", "Παπαδόπουλος")
    monkeypatch.setattr(crm_importer, "fetch_crm_students", lambda: ([
        {"id": 1, "first_name": "Γεώργιος", "last_name": "Παπαδόπουλος"},
        {"id": 2, "first_name": "Μαρία", "last_name": "Λέκκα"},
    ], None))
    monkeypatch.setattr(crm_importer, "fetch_crm_links", lambda: {1: eds_id})
    body = client.get("/api/integration/crm/students/preview").json()
    assert body["new_count"] == 1 and body["exists_count"] == 1
    assert [r["last_name"] for r in body["rows"] if r["status"] == "new"] == ["Λέκκα"]


# ------------- fetch_crm_links: fail-soft (το EDS μπορεί να βγει πριν το CRM) -------------

@pytest.fixture()
def fake_crm(monkeypatch):
    """Ψεύτικο CRM μέσω httpx.MockTransport — καμία πραγματική σύνδεση."""
    import httpx

    monkeypatch.setenv("KORIFI_API_BASE", "http://crm.test")
    monkeypatch.setenv("KORIFI_API_TOKEN", "tok")
    routes: dict = {}
    seen: list = []

    def handler(request):
        seen.append((request.url.path, request.headers.get("authorization")))
        fn = routes.get(request.url.path)
        return fn(request) if fn else httpx.Response(404, json={"detail": "Not Found"})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client",
                        lambda *a, **kw: real_client(*a, transport=httpx.MockTransport(handler), **kw))
    return routes, seen


def test_fetch_crm_links_parses_the_crm_endpoint(fake_crm):
    import httpx

    routes, seen = fake_crm
    routes["/api/eds-sync/students/links"] = lambda r: httpx.Response(200, json={"1": 5, "12": 7})
    assert crm_importer.fetch_crm_links() == {1: 5, 12: 7}
    assert seen == [("/api/eds-sync/students/links", "Bearer tok")]


@pytest.mark.parametrize("reply", ["404", "500", "list", "garbage", "network"])
def test_fetch_crm_links_never_raises(fake_crm, reply):
    import httpx

    routes, _seen = fake_crm

    def answer(request):
        if reply == "network":
            raise httpx.ConnectError("down", request=request)
        return {"404": httpx.Response(404), "500": httpx.Response(500),
                "list": httpx.Response(200, json=[1, 2]),
                "garbage": httpx.Response(200, json={"x": "y"})}[reply]

    routes["/api/eds-sync/students/links"] = answer
    assert crm_importer.fetch_crm_links() == {}


def test_fetch_crm_links_without_token_does_not_call_the_crm(fake_crm, monkeypatch):
    _routes, seen = fake_crm
    monkeypatch.setenv("KORIFI_API_TOKEN", "")
    assert crm_importer.fetch_crm_links() == {}
    assert seen == []


def test_preview_against_an_older_crm_without_links_behaves_as_before(client, db, fake_crm):
    """Σειρά deploy: EDS πριν από το CRM → /students/links = 404 → καμία
    αποτυχία, αντιστοίχιση μόνο κατά όνομα (όπως πριν)."""
    import httpx

    routes, seen = fake_crm
    _eds(db, "Νίκη", "Κοντού")
    _eds(db, "Γιώργος", "Παπαδόπουλος")
    routes["/api/periods"] = lambda r: httpx.Response(200, json=[{"id": 4, "is_active": True}])
    routes["/api/students"] = lambda r: httpx.Response(200, json=[
        {"id": 1, "first_name": "Γεώργιος", "last_name": "Παπαδόπουλος"},
        {"id": 2, "first_name": "ΝΙΚΗ", "last_name": "ΚΟΝΤΟΥ"},
    ])
    res = client.get("/api/integration/crm/students/preview")
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is True
    assert body["new_count"] == 1 and body["exists_count"] == 1       # όπως πριν
    assert "/api/eds-sync/students/links" in [p for p, _ in seen]


# ─── «nan» από το CRM (pandas NaN) = κενό email/τηλέφωνο (B2) ────────────────

NAN_VARIANTS = ["nan", "NaN", " NAN ", "Nan\t", float("nan")]


@pytest.mark.parametrize("junk", NAN_VARIANTS)
def test_classify_treats_nan_contacts_as_empty(junk):
    rows = crm_importer.classify([{"id": 1, "first_name": "Nan", "last_name": "Nancy",
                                   "email": junk, "phone": junk}], [])
    assert (rows[0].email, rows[0].phone) == (None, None)
    assert (rows[0].first_name, rows[0].last_name) == ("Nan", "Nancy")     # ονόματα ανέγγιχτα


@pytest.mark.parametrize("junk", NAN_VARIANTS)
def test_commit_never_stores_nan_contacts(db, junk):
    res = crm_importer.commit([{"first_name": "nan", "last_name": "Παπά",
                                "email": junk, "phone": junk}], db)
    assert res == {"status": "ok", "created": 1, "skipped": 0}
    st = db.query(Student).one()
    assert (st.email, st.phone) == (None, None)
    assert st.first_name == "nan"                                          # το όνομα μένει


def test_values_that_only_look_like_nan_are_kept(db):
    crm_importer.commit([
        {"first_name": "Α", "last_name": "Β", "email": "nancy@x.gr", "phone": "nan2"},
        {"first_name": "Γ", "last_name": "Δ", "email": "banana@x.gr", "phone": "6971234567"},
    ], db)
    got = {(s.email, s.phone) for s in db.query(Student).all()}
    assert got == {("nancy@x.gr", "nan2"), ("banana@x.gr", "6971234567")}
    rows = crm_importer.classify([{"id": 5, "first_name": "Ε", "last_name": "Ζ",
                                   "email": "Nancy@x.gr", "phone": ""}], [])
    assert (rows[0].email, rows[0].phone) == ("Nancy@x.gr", None)          # '' → None όπως πριν
