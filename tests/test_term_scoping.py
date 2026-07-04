"""Regression tests: κάθε read-path που κρίνει διαθεσιμότητα/ζήτηση πρέπει
να βλέπει ΜΟΝΟ το δικό του σενάριο (term).

Μετά τα Terms Phase 1+2, τα lessons και οι availability rows είναι
scenario-scoped. Ο solver (engine._load_data) φιλτράρει σωστά με term_id,
αλλά τρία services έμειναν unscoped και άθροιζαν την ένωση ΟΛΩΝ των
σεναρίων — λάθος «δεν επαρκούν τα slots», λάθος 400 στο drag&drop και
λάθος αποκλεισμός αντικαταστατών, μόλις υπάρξει δεύτερο σενάριο (clone):

  * services/feasibility.check_feasibility
  * services/slot_placement.resolve_and_validate_target_room
  * services/substitute_finder.find_substitutes

Τα tests εδώ στήνουν δύο σενάρια όπου το «άλλο» σενάριο είναι σκόπιμα
ασφυκτικό (υπερβολική ζήτηση / ολική μη-διαθεσιμότητα) και βεβαιώνουν ότι
το ενεργό σενάριο ΔΕΝ μολύνεται. Τα term_id columns έχουν server_default=1,
οπότε ό,τι δεν δηλώνει term ανήκει στο σενάριο 1.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom,
    Lesson,
    Period,
    SchoolClass,
    SchoolSettings,
    Subject,
    Teacher,
    TeacherAvailability,
    Term,
    TimetableSlot,
    TimetableSolution,
)
from backend.services.feasibility import check_feasibility
from backend.services.substitute_finder import find_substitutes
from backend.routers import solver as solver_router


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


def _seed_two_scenarios(db, *, n_periods=2, n_rooms=1):
    """Καταλογικά δεδομένα (global) + term 1 ενεργό, term 2 «πείραμα».

    Επιστρέφει dict με τα βασικά objects. Χωρητικότητα σεναρίου:
    5 μέρες × n_periods × n_rooms.
    """
    db.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))
    subj = Subject(name="Math", short_name="Μ", color="#000")
    teacher = Teacher(name="Νικολάου", short_name="Ν", color="#000")
    sub_teacher = Teacher(name="Παπαδόπουλος", short_name="Π", color="#000")
    cls = SchoolClass(name="A1", short_name="A1")
    rooms = [Classroom(name=f"R{i}", short_name=f"R{i}", room_type="regular")
             for i in range(1, n_rooms + 1)]
    periods = [
        Period(name=f"{i}η", short_name=str(i), start_time=f"{7+i:02d}:00",
               end_time=f"{7+i:02d}:50", is_break=False, sort_order=i)
        for i in range(1, n_periods + 1)
    ]
    main = Term(name="Κύριο", is_active=True)
    experiment = Term(name="Πείραμα", is_active=False)
    db.add_all([subj, teacher, sub_teacher, cls, *rooms, *periods, main, experiment])
    db.commit()
    for o in [subj, teacher, sub_teacher, cls, *rooms, *periods, main, experiment]:
        db.refresh(o)
    return {
        "subject": subj, "teacher": teacher, "sub_teacher": sub_teacher,
        "class": cls, "rooms": rooms, "periods": periods,
        "main": main, "experiment": experiment,
    }


def _flood_unavailability(db, seed, teacher_id, term_id):
    """Ο καθηγητής δηλωμένος «Μη Διαθέσιμος» ΠΑΝΤΟΥ — στο δοσμένο term."""
    for day in range(5):
        for p in seed["periods"]:
            db.add(TeacherAvailability(
                teacher_id=teacher_id, day_of_week=day, period_id=p.id,
                status="unavailable", term_id=term_id,
            ))


# --------------------------- feasibility ------------------------------------

def test_feasibility_ignores_other_scenarios_demand_and_availability(db):
    seed = _seed_two_scenarios(db)  # capacity σεναρίου: 5×2×1 = 10

    # Σενάριο 1 (ενεργό): άνετο — 4 ώρες ζήτηση.
    db.add(Lesson(subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
                  class_id=seed["class"].id, periods_per_week=4, duration=1,
                  term_id=seed["main"].id))
    # Σενάριο 2: υπερφορτωμένο (20 > 10) ΚΑΙ καθηγητής παντού μη διαθέσιμος.
    db.add(Lesson(subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
                  class_id=seed["class"].id, periods_per_week=20, duration=1,
                  term_id=seed["experiment"].id))
    _flood_unavailability(db, seed, seed["teacher"].id, seed["experiment"].id)
    db.commit()

    report = check_feasibility(db, term_id=seed["main"].id)
    # Με το union bug: «Δεν επαρκούν τα slots» (24>10) + capacity καθηγητή 0.
    assert report.errors == []
    assert report.feasible is True
    assert report.stats["total_lessons"] == 1
    assert report.stats["total_periods_needed"] == 4


def test_feasibility_defaults_to_active_term(db):
    seed = _seed_two_scenarios(db)
    # Η υπερφόρτωση ζει ΜΟΝΟ στο ανενεργό σενάριο 2.
    db.add(Lesson(subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
                  class_id=seed["class"].id, periods_per_week=20, duration=1,
                  term_id=seed["experiment"].id))
    db.add(Lesson(subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
                  class_id=seed["class"].id, periods_per_week=2, duration=1,
                  term_id=seed["main"].id))
    db.commit()

    report = check_feasibility(db)  # χωρίς term_id → ενεργό σενάριο
    assert report.feasible is True
    assert report.stats["total_lessons"] == 1


def test_feasibility_without_terms_keeps_legacy_behavior(db):
    """Χωρίς κανένα Term row (παλιές βάσεις/tests) η συμπεριφορά μένει ίδια:
    κανένα φίλτρο, ο έλεγχος βλέπει ό,τι υπάρχει."""
    db.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))
    db.commit()
    report = check_feasibility(db)
    assert report.feasible is False  # minimal-data errors, όπως πριν
    assert any("καθηγητές" in e for e in report.errors)


# ------------------------- substitute finder --------------------------------

def test_substitute_not_excluded_by_other_scenario_unavailability(db):
    seed = _seed_two_scenarios(db, n_periods=2)

    lesson = Lesson(subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
                    class_id=seed["class"].id, periods_per_week=1, duration=1,
                    term_id=seed["main"].id)
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    sol = TimetableSolution(name="s1", status="feasible", term_id=seed["main"].id)
    db.add(sol)
    db.commit()
    db.refresh(sol)
    db.add(TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=0,
                         period_id=seed["periods"][0].id,
                         classroom_id=seed["rooms"][0].id))
    # Ο υποψήφιος αντικαταστάτης είναι «Μη Διαθέσιμος» ΜΟΝΟ στο σενάριο 2.
    db.add(TeacherAvailability(teacher_id=seed["sub_teacher"].id, day_of_week=0,
                               period_id=seed["periods"][0].id,
                               status="unavailable",
                               term_id=seed["experiment"].id))
    db.commit()

    result = find_substitutes(db, sol.id, seed["teacher"].id, 0)
    candidates = result["affected_slots"][0]["candidates"]
    assert any(c["teacher_id"] == seed["sub_teacher"].id for c in candidates), (
        "Ο αντικαταστάτης αποκλείστηκε από κώλυμα ΑΛΛΟΥ σεναρίου"
    )


# ---------------------------- slot placement --------------------------------

@pytest.fixture()
def client(db):
    """Slot-move endpoint πάνω στο ίδιο seeded session."""
    app = FastAPI()
    app.include_router(solver_router.router, prefix="/api/solver")

    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.session = db
    return c


def test_slot_move_not_blocked_by_other_scenario_unavailability(client):
    db = client.session
    seed = _seed_two_scenarios(db, n_periods=2)

    lesson = Lesson(subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
                    class_id=seed["class"].id, classroom_id=seed["rooms"][0].id,
                    periods_per_week=1, duration=1, term_id=seed["main"].id)
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    sol = TimetableSolution(name="s1", status="feasible", term_id=seed["main"].id)
    db.add(sol)
    db.commit()
    db.refresh(sol)
    slot = TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=0,
                         period_id=seed["periods"][0].id,
                         classroom_id=seed["rooms"][0].id)
    db.add(slot)
    # Ο καθηγητής έχει κώλυμα στον στόχο (Τρίτη/2η) ΜΟΝΟ στο σενάριο 2 —
    # η μετακίνηση μέσα στη λύση του σεναρίου 1 πρέπει να περάσει.
    db.add(TeacherAvailability(teacher_id=seed["teacher"].id, day_of_week=1,
                               period_id=seed["periods"][1].id,
                               status="unavailable",
                               term_id=seed["experiment"].id))
    db.commit()
    db.refresh(slot)

    res = client.put(
        f"/api/solver/solutions/{sol.id}/slots/{slot.id}",
        json={"day_of_week": 1, "period_id": seed["periods"][1].id},
    )
    assert res.status_code == 200, res.text


def test_slot_move_still_blocked_by_same_scenario_unavailability(client):
    """Ο υπάρχων έλεγχος πρέπει να συνεχίσει να πιάνει το ΙΔΙΟ σενάριο."""
    db = client.session
    seed = _seed_two_scenarios(db, n_periods=2)

    lesson = Lesson(subject_id=seed["subject"].id, teacher_id=seed["teacher"].id,
                    class_id=seed["class"].id, classroom_id=seed["rooms"][0].id,
                    periods_per_week=1, duration=1, term_id=seed["main"].id)
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    sol = TimetableSolution(name="s1", status="feasible", term_id=seed["main"].id)
    db.add(sol)
    db.commit()
    db.refresh(sol)
    slot = TimetableSlot(solution_id=sol.id, lesson_id=lesson.id, day_of_week=0,
                         period_id=seed["periods"][0].id,
                         classroom_id=seed["rooms"][0].id)
    db.add(slot)
    db.add(TeacherAvailability(teacher_id=seed["teacher"].id, day_of_week=1,
                               period_id=seed["periods"][1].id,
                               status="unavailable",
                               term_id=seed["main"].id))
    db.commit()
    db.refresh(slot)

    res = client.put(
        f"/api/solver/solutions/{sol.id}/slots/{slot.id}",
        json={"day_of_week": 1, "period_id": seed["periods"][1].id},
    )
    assert res.status_code == 400
    assert "κώλυμα" in res.json()["detail"]
