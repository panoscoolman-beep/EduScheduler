"""Unit tests for the extracted solver job helpers
(backend/services/solver_jobs.py).

_iso_utc and _guard_no_active_solve are small and pure-ish, so they get fast
direct tests here. The heavier _persist_solver_result / _run_generation_job are
exercised end-to-end by the solver integration suite (test_solver_constraints,
test_warm_start); the timeout→'error' mapping is pinned at the bottom of this
file against an in-memory SQLite DB that enforces ck_solution_status.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import Term, TimetableSolution
from backend.services import solver_jobs
from backend.services.solver_jobs import (
    _guard_no_active_solve,
    _iso_utc,
    _persist_solver_result,
    _run_generation_job,
)
from backend.solver.engine import SolverResult


# --------------------------------------------------------------------------- #
# _iso_utc — serialize stored naive-UTC datetimes as explicit-UTC ISO
# --------------------------------------------------------------------------- #

def test_iso_utc_none_passes_through():
    assert _iso_utc(None) is None


def test_iso_utc_naive_is_tagged_as_utc():
    # A naive datetime (how they're stored) must come out with +00:00 so the
    # browser's new Date() reads it as UTC, not local.
    assert _iso_utc(datetime(2026, 6, 14, 10, 30, 0)) == "2026-06-14T10:30:00+00:00"


def test_iso_utc_aware_is_preserved():
    aware = datetime(2026, 6, 14, 10, 30, tzinfo=timezone.utc)
    assert _iso_utc(aware) == "2026-06-14T10:30:00+00:00"


# --------------------------------------------------------------------------- #
# _guard_no_active_solve — 409 when a solve is already running
# --------------------------------------------------------------------------- #

class _Query:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDB:
    """Minimal stand-in: db.query(...).filter(...).first() -> `active`."""
    def __init__(self, active):
        self._active = active

    def query(self, *args, **kwargs):
        return _Query(self._active)


def test_guard_passes_when_no_active_solve():
    assert _guard_no_active_solve(_FakeDB(active=None)) is None


def test_guard_raises_409_when_a_solve_is_running():
    with pytest.raises(HTTPException) as exc_info:
        _guard_no_active_solve(_FakeDB(active=object()))
    assert exc_info.value.status_code == 409


# --------------------------------------------------------------------------- #
# Timeout του solver — δεν επιτρέπεται από το ck_solution_status, άρα πρέπει
# να αποθηκεύεται ως 'error' ΜΕ το ελληνικό μήνυμα του engine (συμβουλές),
# όχι να σκάει σε CheckViolation → «Solver crashed: …».
# --------------------------------------------------------------------------- #

TIMEOUT_MSG = (
    "Ο solver έκανε timeout μετά από 30s χωρίς να βρει πλήρη λύση. Δοκίμασε:\n"
    "  • Αύξησε το max_time_seconds (π.χ. 300)\n"
    "  • Χαλάρωσε κάποιους hard constraints\n"
    "  • Δοκίμασε permissive mode (parking lot για ό,τι δεν χωράει)"
)


def _timeout_result() -> SolverResult:
    return SolverResult(
        status="timeout",
        message=TIMEOUT_MSG,
        stats={"wall_time": 30.0, "branches": 0, "conflicts": 0},
    )


@pytest.fixture()
def sqlite_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _generating_solution(s) -> TimetableSolution:
    term = Term(name="Κύριο", is_active=True)
    s.add(term)
    s.commit()
    sol = TimetableSolution(name="Πρόγραμμα", status="generating", term_id=term.id)
    s.add(sol)
    s.commit()
    s.refresh(sol)
    return sol


def test_test_db_enforces_solution_status_check(sqlite_sessionmaker):
    """Sanity: το SQLite των tests ΟΝΤΩΣ επιβάλλει το ck_solution_status —
    αλλιώς τα παρακάτω tests θα περνούσαν ψευδώς."""
    s = sqlite_sessionmaker()
    sol = _generating_solution(s)
    sol.status = "timeout"
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()
    s.close()


def test_persist_timeout_result_stores_error_with_engine_message(sqlite_sessionmaker):
    s = sqlite_sessionmaker()
    sol = _generating_solution(s)

    _persist_solver_result(s, sol, _timeout_result())

    s.expire_all()
    stored = s.get(TimetableSolution, sol.id)
    assert stored.status == "error"
    meta = json.loads(stored.metadata_json)
    assert meta["message"] == TIMEOUT_MSG
    assert meta["solver_status"] == "timeout"
    assert meta["wall_time"] == 30.0
    s.close()


def test_status_endpoint_shows_timeout_advice(sqlite_sessionmaker):
    """Ό,τι διαβάζει το frontend (GET /solver/status) — το μήνυμα του timeout,
    όχι «Κατάσταση: error»."""
    from backend.routers.solver import solver_status

    s = sqlite_sessionmaker()
    sol = _generating_solution(s)
    _persist_solver_result(s, sol, _timeout_result())

    resp = solver_status(sol.id, db=s)
    assert resp.status == "error"
    assert resp.message == TIMEOUT_MSG
    s.close()


def test_persist_keeps_engine_message_for_other_failures(sqlite_sessionmaker):
    """Και τα υπόλοιπα μη-επιτυχή αποτελέσματα κρατούν το μήνυμα του engine
    (π.χ. validation error «δεν υπάρχουν μαθήματα»)."""
    s = sqlite_sessionmaker()
    sol = _generating_solution(s)
    _persist_solver_result(
        s, sol, SolverResult(status="error", message="Δεν υπάρχουν μαθήματα"),
    )
    s.expire_all()
    stored = s.get(TimetableSolution, sol.id)
    assert stored.status == "error"
    meta = json.loads(stored.metadata_json)
    assert meta["message"] == "Δεν υπάρχουν μαθήματα"
    assert "solver_status" not in meta
    s.close()


def test_run_generation_job_timeout_is_not_reported_as_crash(
    sqlite_sessionmaker, monkeypatch,
):
    """Ολόκληρη η ροή του background job: πριν τη διόρθωση το commit έσκαγε
    (CheckViolation) και η λύση έμενε 'error' με «Solver crashed: …»."""
    s = sqlite_sessionmaker()
    sol_id = _generating_solution(s).id
    s.close()

    class _TimeoutSolver:
        def __init__(self, *args, **kwargs):
            pass

        def solve(self):
            return _timeout_result()

    monkeypatch.setattr(solver_jobs, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(solver_jobs, "TimetableSolver", _TimeoutSolver)

    _run_generation_job(sol_id, max_time_seconds=30, mode="strict")

    s = sqlite_sessionmaker()
    stored = s.get(TimetableSolution, sol_id)
    assert stored.status == "error"
    meta = json.loads(stored.metadata_json)
    assert meta["message"] == TIMEOUT_MSG
    assert "Solver crashed" not in meta["message"]
    s.close()


def test_infeasible_keeps_message_and_reasons_take_priority(
    sqlite_sessionmaker, monkeypatch,
):
    """Αδύνατο πρόγραμμα: αποθηκεύεται 'infeasible' (όχι αντιστοίχιση) με το
    μήνυμα του engine· όταν υπάρχουν συγκεκριμένες αιτίες εφικτότητας, το
    /solver/status δείχνει ΑΥΤΕΣ — χωρίς αιτίες, το μήνυμα του engine."""
    from backend.routers.solver import solver_status

    class _Report:
        def __init__(self, errors):
            self._errors = errors

        def to_dict(self):
            return {"errors": self._errors, "warnings": []}

    engine_msg = "Οι περιορισμοί σου είναι αντιφατικοί"
    s = sqlite_sessionmaker()

    monkeypatch.setattr(solver_jobs, "check_feasibility",
                        lambda db, term_id=None: _Report(["Ο Παπαδόπουλος δεν φτάνει"]))
    sol = _generating_solution(s)
    _persist_solver_result(s, sol, SolverResult(status="infeasible", message=engine_msg))
    meta = json.loads(s.get(TimetableSolution, sol.id).metadata_json)
    assert s.get(TimetableSolution, sol.id).status == "infeasible"
    assert meta["message"] == engine_msg
    assert "solver_status" not in meta
    resp = solver_status(sol.id, db=s)
    assert resp.message.startswith("Αδύνατο πρόγραμμα. Αιτίες:")
    assert "Ο Παπαδόπουλος δεν φτάνει" in resp.message

    monkeypatch.setattr(solver_jobs, "check_feasibility",
                        lambda db, term_id=None: _Report([]))
    sol2 = TimetableSolution(name="Β", status="generating", term_id=sol.term_id)
    s.add(sol2)
    s.commit()
    _persist_solver_result(s, sol2, SolverResult(status="infeasible", message=engine_msg))
    assert solver_status(sol2.id, db=s).message == engine_msg
    s.close()
