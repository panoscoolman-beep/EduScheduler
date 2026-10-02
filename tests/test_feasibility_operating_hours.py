"""Έλεγχος Εφικτότητας με ωράριο λειτουργίας (2/10/2026).

Από 18/9 ο solver δεν βάζει μάθημα εκτός ωραρίου (H0), αλλά ο Έλεγχος
Εφικτότητας μετρούσε ακόμα ΟΛΕΣ τις διδακτικές ώρες (π.χ. 08:00–22:00 ενώ το
φροντιστήριο δουλεύει 14:00–22:00): έλεγε «Όλα τα checks πέρασαν» ενώ ο
solver έβγαινε «αδύνατο». Τώρα μετρά μόνο τις ώρες μέσα στο ωράριο και λέει
ότι φταίει το ωράριο. Χωρίς ωράριο όλα μένουν ακριβώς όπως πριν.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import (
    Classroom, Lesson, Period, SchoolClass, SchoolSettings, Student, StudentAvailability,
    StudentClassEnrollment, Subject, Teacher, TeacherAvailability, Term,
)
from backend.services.feasibility import check_feasibility
from backend.solver.engine import TimetableSolver


def _env(n_periods=14, start=8, window=("14:00", "22:00"), days=5, n_rooms=2, **settings):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(Term(id=1, name="Σενάριο", is_active=True))
    if window:
        settings.update(visible_from=window[0], visible_to=window[1])
    s.add(SchoolSettings(school_name="Κ", days_per_week=days, **settings))
    subj = Subject(name="Φυσική", short_name="ΦΥΣ", color="#000000")
    lab = Subject(name="Χημεία", short_name="ΧΗΜ", color="#000000", requires_special_room=True,
                  special_room_type="lab")
    t = Teacher(name="Νικολάου", short_name="ΝΙΚ", color="#000000")
    c1, c2 = SchoolClass(name="Γ1", short_name="Γ1"), SchoolClass(name="Γ2", short_name="Γ2")
    rooms = [Classroom(name=f"Α{i}", short_name=f"Α{i}", room_type="regular") for i in range(n_rooms)]
    periods = [Period(name=f"{i + 1}η", short_name=f"{i + 1}η", start_time=f"{start + i:02d}:00",
                      end_time=f"{start + i:02d}:50", is_break=False, sort_order=i + 1)
               for i in range(n_periods)]
    s.add_all([subj, lab, t, c1, c2, *rooms, *periods])
    s.commit()
    return SimpleNamespace(s=s, subj=subj, lab=lab, t=t, c1=c1, c2=c2, rooms=rooms, periods=periods)


def _lesson(env, ppw, cls=None, subject=None, teacher=None, distribution=None):
    les = Lesson(term_id=1, subject_id=(subject or env.subj).id, teacher_id=(teacher or env.t).id,
                 class_id=(cls or env.c1).id, periods_per_week=ppw, distribution=distribution)
    env.s.add(les)
    env.s.commit()
    return les


def _report(env):
    return check_feasibility(env.s, term_id=1).to_dict()


def _open(env):
    return [p for p in env.periods if int(p.start_time[:2]) >= 14]


def test_part_time_teacher_inside_the_window_is_reported_with_the_cause():
    """Παράδειγμα επαλήθευσης: 26 ώρες, Τρί+Πέμ κώλυμα στις ανοιχτές ώρες → χωράνε 24."""
    env = _env()
    _lesson(env, 13, cls=env.c1)
    _lesson(env, 13, cls=env.c2)
    for d in (1, 3):
        for p in _open(env):
            env.s.add(TeacherAvailability(term_id=1, teacher_id=env.t.id, day_of_week=d,
                                          period_id=p.id, status="unavailable"))
    env.s.commit()
    report = _report(env)
    assert report["feasible"] is False                                 # πριν: True, κανένα σφάλμα
    assert report["errors"] == [
        "Καθηγητής Νικολάου: χρειάζεται 26 ώρες αλλά χωράνε μόνο 24 μέσα στο ωράριο λειτουργίας"]
    assert any("ωράριο λειτουργίας" in s for s in report["suggestions"])
    assert report["stats"]["teacher_load"][0]["capacity"] == 24
    assert TimetableSolver(env.s, max_time_seconds=10, term_id=1).solve().status == "infeasible"


def test_unavailability_on_closed_hours_is_not_counted_twice():
    env = _env()
    _lesson(env, 20, cls=env.c1)
    _lesson(env, 20, cls=env.c2)
    for d in range(5):                                                  # κώλυμα όλα τα πρωινά
        for p in env.periods:
            if int(p.start_time[:2]) < 14:
                env.s.add(TeacherAvailability(term_id=1, teacher_id=env.t.id, day_of_week=d,
                                              period_id=p.id, status="unavailable"))
    env.s.commit()
    report = _report(env)
    assert report["stats"]["teacher_load"][0]["capacity"] == 40        # όχι 40 − 30
    assert not any("Νικολάου: χρειάζεται" in e for e in report["errors"])


def test_class_week_and_global_capacity_count_only_open_hours():
    env = _env(n_rooms=1)
    other = Teacher(name="Άλλος", short_name="ΑΛ", color="#000000")
    env.s.add(other)
    env.s.commit()
    _lesson(env, 20, cls=env.c1)
    _lesson(env, 2, cls=env.c1)
    _lesson(env, 20, cls=env.c1, teacher=other)
    report = _report(env)
    assert "Τάξη Γ1: χρειάζεται 42 ώρες αλλά χωράνε μόνο 40 μέσα στο ωράριο λειτουργίας" in report["errors"]
    assert report["stats"]["total_slots_available"] == 40
    assert report["stats"]["open_periods_per_week"] == 40
    assert any(e.startswith("Δεν επαρκούν τα slots: χρειάζονται 42 αλλά υπάρχουν μόνο 40 "
                            "(40 ώρες/εβδομάδα μέσα στο ωράριο λειτουργίας × 1 αίθουσες)")
               for e in report["errors"])


def test_block_longer_than_the_open_hours_of_a_day():
    env = _env(n_periods=6, start=17)                                  # ανοιχτές 17–21 = 5 ώρες
    _lesson(env, 6, distribution="6")
    report = _report(env)
    assert ("Φυσική (Γ1): ζητάει block 6 ωρών αλλά μέσα στο ωράριο λειτουργίας η μέρα "
            "έχει μόνο 5 συνεχόμενες ώρες") in report["errors"]
    assert any("block" in s for s in report["suggestions"])


def test_special_rooms_and_students_inside_the_window():
    env = _env(n_periods=10, start=10, window=("14:00", "18:00"))    # 4 ανοιχτές/μέρα → 20/εβδ.
    lab_room = Classroom(name="Εργ", short_name="Ε", room_type="lab")
    env.s.add(lab_room)
    st = Student(first_name="Άννα", last_name="Χ")
    env.s.add(st)
    env.s.commit()
    other = Teacher(name="Άλλος", short_name="ΑΛ", color="#000000")
    env.s.add(other)
    env.s.commit()
    _lesson(env, 11, cls=env.c1, subject=env.lab)
    _lesson(env, 11, cls=env.c1, subject=env.lab, teacher=other)
    env.s.add(StudentClassEnrollment(student_id=st.id, class_id=env.c1.id))
    env.s.add(StudentAvailability(term_id=1, student_id=st.id, day_of_week=0,
                                  period_id=env.periods[0].id, status="unavailable"))   # κλειστή ώρα
    env.s.commit()
    errors = _report(env)["errors"]
    assert ("Αίθουσες τύπου 'lab': ζήτηση 22 ώρες αλλά χωρητικότητα μόνο 20 (1 αίθουσες × "
            "20 ώρες/εβδομάδα μέσα στο ωράριο λειτουργίας)") in errors
    assert "Μαθητής Χ Άννα: εγγεγραμμένος σε 22 ώρες αλλά χωράνε μόνο 20 μέσα στο ωράριο λειτουργίας" in errors


def test_saturday_window_adds_its_own_open_hours():
    env = _env(n_periods=14, days=6, window=("14:00", "22:00"),
               saturday_from="08:00", saturday_to="22:00")
    _lesson(env, 2)
    assert _report(env)["stats"]["open_periods_per_week"] == 5 * 8 + 14


def test_without_a_window_messages_and_numbers_are_unchanged():
    env = _env(n_periods=4, window=None, n_rooms=1)
    _lesson(env, 20, cls=env.c1)
    _lesson(env, 1, cls=env.c1)
    _lesson(env, 2, cls=env.c2, distribution="3,3")                    # άκυρη κατανομή → μονόωρα
    _lesson(env, 5, cls=env.c2, subject=env.lab, distribution="5")
    for p in env.periods:
        env.s.add(TeacherAvailability(term_id=1, teacher_id=env.t.id, day_of_week=0,
                                      period_id=p.id, status="unavailable"))
    env.s.commit()
    report = _report(env)
    assert report["errors"] == [
        "Δεν επαρκούν τα slots: χρειάζονται 28 αλλά υπάρχουν μόνο 20 (5 μέρες × 4 ώρες × 1 αίθουσες)",
        "Καθηγητής Νικολάου: χρειάζεται 28 ώρες αλλά η διαθεσιμότητά του επιτρέπει μόνο 16",
        "Τάξη Γ1: χρειάζεται 21 ώρες αλλά η εβδομάδα έχει μόνο 20 (5×4)",
        "Απαιτείται αίθουσα τύπου 'lab' για 5 ώρες αλλά δεν υπάρχει καμία τέτοια αίθουσα",
        "Χημεία (Γ2): ζητάει block 5 ωρών αλλά η μέρα έχει μόνο 4 διαθέσιμες περιόδους",
    ]
    assert report["stats"]["total_slots_available"] == 20
    assert report["stats"]["open_periods_per_week"] == 20
