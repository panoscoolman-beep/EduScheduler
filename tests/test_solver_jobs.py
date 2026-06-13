"""Unit tests for the extracted solver job helpers
(backend/services/solver_jobs.py).

_iso_utc and _guard_no_active_solve are small and pure-ish, so they get fast
direct tests here. The heavier _persist_solver_result / _run_generation_job are
exercised end-to-end by the solver integration suite (test_solver_constraints,
test_warm_start).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from backend.services.solver_jobs import _guard_no_active_solve, _iso_utc


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
