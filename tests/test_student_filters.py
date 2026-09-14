"""Φίλτρο λίστας μαθητών (backend/services/student_filters.py) — pure.

Οι ίδιοι κανόνες ελέγχονται και στο frontend
(frontend/js/tests/students_helpers.test.js)."""
from __future__ import annotations

from types import SimpleNamespace

from backend.services.student_filters import StudentFilter, normalize

THETIKI = "Θετικών Σπουδών (Θετική)"
OIK = "Σπουδών Οικονομίας & Πληροφορικής (4ο πεδίο)"


def st(last, first, grade=None, track=None, email=None, phone=None):
    return SimpleNamespace(last_name=last, first_name=first, grade=grade, track=track,
                           email=email, phone=phone)


STUDENTS = [
    st("Παπαδόπουλος", "Νίκος", "Γ΄ Λυκείου", OIK, phone="6900000001"),
    st("Αλεξίου", "Μαρία", "Β΄ Λυκείου", THETIKI),
    st("Ζήσης", "Κώστας", "Β΄ Λυκείου", "Ανθρωπιστικών Σπουδών (Θεωρητική)"),
    st("Κοντού", "Άννα", None, None, email="anna@x.gr"),
    st("Βλάχος", "Πέτρος", "  ", None),          # κενή τάξη με κενά = χωρίς τάξη
]


def names(filt: StudentFilter) -> list[str]:
    return [s.last_name for s in filt.apply(STUDENTS)]


def test_normalize_strips_accents_case_and_final_sigma():
    assert normalize("Παπαδόπουλος") == "παπαδοπουλοσ"
    assert normalize("  ΪΌΝ ") == "ιον"
    assert normalize(None) == ""


def test_empty_filter_keeps_everyone_in_input_order():
    filt = StudentFilter.from_query()
    assert not filt.is_active()
    assert names(filt) == [s.last_name for s in STUDENTS]
    assert filt.summary() == "" and filt.query_params() == []


def test_or_within_a_group_and_across_groups():
    assert names(StudentFilter.from_query(["Β΄ Λυκείου"])) == ["Αλεξίου", "Ζήσης"]
    assert names(StudentFilter.from_query(["Β΄ Λυκείου", "Γ΄ Λυκείου"])) == [
        "Παπαδόπουλος", "Αλεξίου", "Ζήσης"]
    assert names(StudentFilter.from_query(["Β΄ Λυκείου"], [THETIKI])) == ["Αλεξίου"]
    assert names(StudentFilter.from_query(["Β΄ Λυκείου"], [OIK])) == []
    assert names(StudentFilter.from_query(tracks=[OIK])) == ["Παπαδόπουλος"]


def test_empty_grade_selects_students_without_grade():
    filt = StudentFilter.from_query([""])
    assert filt.is_active()
    assert names(filt) == ["Κοντού", "Βλάχος"]


def test_blank_tracks_are_ignored_and_duplicates_collapse():
    filt = StudentFilter.from_query([" Β΄ Λυκείου ", "Β΄ Λυκείου"], ["", "  ", THETIKI, THETIKI])
    assert filt.grades == ("Β΄ Λυκείου",)
    assert filt.tracks == (THETIKI,)


def test_search_is_accent_insensitive_and_every_word_must_match():
    assert names(StudentFilter.from_query(search="παπαδοπουλοσ")) == ["Παπαδόπουλος"]
    assert names(StudentFilter.from_query(search="ΑΝΝΑ κοντ")) == ["Κοντού"]
    assert names(StudentFilter.from_query(search="anna@")) == ["Κοντού"]
    assert names(StudentFilter.from_query(search="6900000001")) == ["Παπαδόπουλος"]
    assert names(StudentFilter.from_query(search="   ")) == [s.last_name for s in STUDENTS]


def test_summary_and_query_params_describe_the_filter():
    filt = StudentFilter.from_query(["Γ΄ Λυκείου", ""], [OIK], " παπ ")
    assert filt.summary() == (
        f"Τάξη: Γ΄ Λυκείου, Χωρίς τάξη · Κατεύθυνση / Τομέας: {OIK} · Αναζήτηση: «παπ»")
    assert filt.query_params() == [
        ("grade", "Γ΄ Λυκείου"), ("grade", ""), ("track", OIK), ("q", "παπ")]
