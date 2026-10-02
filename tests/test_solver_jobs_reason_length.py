"""Αιτία Παλέτας > 500 χαρακτήρες δεν ρίχνει τη λύση σε «error».

Η στήλη timetable_slots.unplaced_reason είναι VARCHAR(500). Με πολλούς σκληρούς
κανόνες μεγάλων ονομάτων η αιτία ξεπερνούσε τους 500 χαρακτήρες και το Postgres
απέρριπτε όλο το commit της λύσης (το SQLite των tests δεν ελέγχει μήκος).
"""
from __future__ import annotations

from types import SimpleNamespace

from backend.services import solver_jobs


def test_fit_reason_keeps_short_and_caps_long():
    assert solver_jobs._fit_reason(None) is None
    assert solver_jobs._fit_reason("Κώλυμα καθηγητή") == "Κώλυμα καθηγητή"
    exact = "α" * 500
    assert solver_jobs._fit_reason(exact) == exact
    long_ = "β" * 509
    fitted = solver_jobs._fit_reason(long_)
    assert len(fitted) == 500 and fitted.endswith("…") and fitted.startswith("β" * 499)


def test_persisted_unplaced_reason_fits_the_column():
    added = []

    class _DB:
        def add(self, obj):
            added.append(obj)

        def commit(self):
            pass

    result = SimpleNamespace(status="feasible", score=1.0, stats={}, message="", slots=[],
                             unplaced=[{"lesson_id": 7, "hours": 2, "reason": "κανόνας " * 100}])
    sol = SimpleNamespace(id=1, term_id=1, status=None, score=None, metadata_json=None)
    solver_jobs._persist_solver_result(_DB(), sol, result)
    reasons = [s.unplaced_reason for s in added if s.is_unplaced]
    assert len(reasons) == 2
    assert all(len(r) <= 500 for r in reasons)
