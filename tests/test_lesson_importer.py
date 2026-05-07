"""Unit tests for backend.services.lesson_importer.

Two-phase contract:
  preview(csv_text, db) — read-only validation + lookup resolution
  commit(rows, db)      — single-transaction insert with rollback

Tests use a real in-memory SQLite + minimal fixture data so we exercise
both the lookup logic AND the commit transaction without touching prod.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import Subject, Teacher, SchoolClass, Classroom, Period, Lesson
from backend.services.lesson_importer import preview, commit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Fresh in-memory DB per test, with a minimal seed."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed
    subj = Subject(name="Μαθηματικά", short_name="ΜΑΘ", color="#3B82F6")
    teacher = Teacher(name="Παπαδόπουλος", short_name="ΠΠ", color="#3B82F6")
    cls = SchoolClass(name="Α' Λυκείου", short_name="Α-ΛΥΚ")
    room = Classroom(name="Αίθουσα 1", short_name="ΑΙΘ-1")
    p1 = Period(name="1η", short_name="1", start_time="08:15",
                end_time="09:00", is_break=False, sort_order=1)
    p2 = Period(name="2η", short_name="2", start_time="09:05",
                end_time="09:50", is_break=False, sort_order=2)
    p3 = Period(name="3η", short_name="3", start_time="09:55",
                end_time="10:40", is_break=False, sort_order=3)
    p4 = Period(name="4η", short_name="4", start_time="10:45",
                end_time="11:30", is_break=False, sort_order=4)
    session.add_all([subj, teacher, cls, room, p1, p2, p3, p4])
    session.commit()

    yield session

    session.close()


def _csv(*lines: str) -> str:
    """Helper to build CSV text from header + data lines."""
    header = "subject,teacher,class,classroom,periods_per_week,distribution"
    return "\n".join([header, *lines])


# ---------------------------------------------------------------------------
# preview() — header + structural errors
# ---------------------------------------------------------------------------

def test_preview_empty_csv(db):
    result = preview("", db)
    assert result.fatal_error == "Άδειο CSV"


def test_preview_whitespace_only(db):
    result = preview("   \n\n   ", db)
    assert result.fatal_error == "Άδειο CSV"


def test_preview_missing_required_columns(db):
    result = preview("subject,teacher\nFoo,Bar", db)
    assert result.fatal_error is not None
    assert "Λείπουν υποχρεωτικές στήλες" in result.fatal_error
    assert "class" in result.fatal_error
    assert "periods_per_week" in result.fatal_error


def test_preview_only_header_no_data(db):
    """Just the header row → 0 rows, no fatal error."""
    result = preview(
        "subject,teacher,class,classroom,periods_per_week,distribution",
        db,
    )
    assert result.fatal_error is None
    assert result.rows == []


# ---------------------------------------------------------------------------
# preview() — lookup resolution
# ---------------------------------------------------------------------------

def test_preview_resolves_by_full_name(db):
    csv = _csv("Μαθηματικά,Παπαδόπουλος,Α' Λυκείου,Αίθουσα 1,4,2,2")
    result = preview(csv, db)
    assert result.fatal_error is None
    assert len(result.rows) == 1

    row = result.rows[0]
    assert row.is_valid, row.errors
    assert row.subject_id is not None
    assert row.teacher_id is not None
    assert row.class_id is not None
    assert row.classroom_id is not None
    assert row.periods_per_week == 4
    assert row.distribution == "2,2"


def test_preview_resolves_by_short_name(db):
    """short_name should also match the lookup."""
    csv = _csv("ΜΑΘ,ΠΠ,Α-ΛΥΚ,ΑΙΘ-1,3,")
    result = preview(csv, db)
    row = result.rows[0]
    assert row.is_valid, row.errors


def test_preview_lookup_is_case_insensitive(db):
    """Lookup matching should be lowercased."""
    csv = _csv("μαθηματικα,ΠΠ,α' λυκειου,ΑΙΘ-1,2,")
    result = preview(csv, db)
    row = result.rows[0]
    # 'μαθηματικα' (no accent) ≠ 'μαθηματικά' — DOES depend on accents.
    # We document this: exact lookup, case-insensitive only. Greek accents
    # matter. So this row should fail the subject lookup.
    assert "Subject" in " ".join(row.errors)


def test_preview_unknown_subject_creates_error_row(db):
    csv = _csv("ΞΕΝΟ,ΠΠ,Α-ΛΥΚ,,2,")
    result = preview(csv, db)
    row = result.rows[0]
    assert not row.is_valid
    assert any("Subject" in e for e in row.errors)


def test_preview_unknown_teacher_creates_error_row(db):
    csv = _csv("ΜΑΘ,ΑΓΝΩΣΤΟΣ,Α-ΛΥΚ,,2,")
    result = preview(csv, db)
    row = result.rows[0]
    assert any("Teacher" in e for e in row.errors)


def test_preview_unknown_class_creates_error_row(db):
    csv = _csv("ΜΑΘ,ΠΠ,Z-ΛΥΚ,,2,")
    result = preview(csv, db)
    row = result.rows[0]
    assert any("Class" in e for e in row.errors)


def test_preview_unknown_classroom_creates_error_row(db):
    csv = _csv("ΜΑΘ,ΠΠ,Α-ΛΥΚ,ΞΕΝΗ,2,")
    result = preview(csv, db)
    row = result.rows[0]
    assert any("Classroom" in e for e in row.errors)


def test_preview_blank_classroom_is_optional(db):
    """Empty classroom column → automatic room (no error, classroom_id=None)."""
    csv = _csv("ΜΑΘ,ΠΠ,Α-ΛΥΚ,,2,")
    result = preview(csv, db)
    row = result.rows[0]
    assert row.is_valid, row.errors
    assert row.classroom_id is None


# ---------------------------------------------------------------------------
# preview() — periods_per_week + distribution validation
# ---------------------------------------------------------------------------

def test_preview_invalid_periods_per_week(db):
    csv = _csv("ΜΑΘ,ΠΠ,Α-ΛΥΚ,,abc,")
    row = preview(csv, db).rows[0]
    assert not row.is_valid
    assert any("periods_per_week" in e for e in row.errors)


def test_preview_periods_per_week_zero(db):
    csv = _csv("ΜΑΘ,ΠΠ,Α-ΛΥΚ,,0,")
    row = preview(csv, db).rows[0]
    assert any("εκτός εύρους" in e for e in row.errors)


def test_preview_distribution_does_not_sum(db):
    csv = _csv("ΜΑΘ,ΠΠ,Α-ΛΥΚ,,5,2,2")
    row = preview(csv, db).rows[0]
    assert any("σύνολο" in e for e in row.errors)


def test_preview_distribution_block_too_large(db):
    """Test seeded with 4 teaching periods/day. Block of 5 should fail."""
    csv = _csv("ΜΑΘ,ΠΠ,Α-ΛΥΚ,,5,5")
    row = preview(csv, db).rows[0]
    assert any("ωρών/μέρα" in e for e in row.errors)


def test_preview_distribution_negative_block(db):
    csv = _csv("ΜΑΘ,ΠΠ,Α-ΛΥΚ,,2,-1,3")
    row = preview(csv, db).rows[0]
    # Negative parses as non-digit, falls through to first check
    assert any("distribution" in e for e in row.errors)


def test_preview_no_distribution_is_fine(db):
    csv = _csv("ΜΑΘ,ΠΠ,Α-ΛΥΚ,,2,")
    row = preview(csv, db).rows[0]
    assert row.is_valid, row.errors
    assert row.distribution is None


# ---------------------------------------------------------------------------
# preview() — multi-row scenarios
# ---------------------------------------------------------------------------

def test_preview_mix_of_valid_and_invalid_rows(db):
    csv = _csv(
        "ΜΑΘ,ΠΠ,Α-ΛΥΚ,,2,",
        "ΞΕΝΟ,ΠΠ,Α-ΛΥΚ,,3,",
        "ΜΑΘ,ΠΠ,Α-ΛΥΚ,,4,2,2",
    )
    result = preview(csv, db)
    assert len(result.rows) == 3
    assert result.valid_count == 2
    assert result.error_count == 1
    assert result.rows[1].line_number == 3  # second data row → CSV line 3


def test_preview_trims_whitespace_around_values(db):
    csv = _csv("  ΜΑΘ ,  ΠΠ , Α-ΛΥΚ ,, 2 ,")
    row = preview(csv, db).rows[0]
    assert row.is_valid, row.errors


# ---------------------------------------------------------------------------
# commit() — transaction semantics
# ---------------------------------------------------------------------------

def test_commit_inserts_all_valid_rows(db):
    csv = _csv(
        "ΜΑΘ,ΠΠ,Α-ΛΥΚ,ΑΙΘ-1,2,",
        "ΜΑΘ,ΠΠ,Α-ΛΥΚ,,3,2,1",
    )
    result = preview(csv, db)
    summary = commit(result.rows, db)
    assert summary["status"] == "ok"
    assert summary["created"] == 2

    lessons = db.query(Lesson).all()
    assert len(lessons) == 2


def test_commit_refuses_when_any_row_invalid(db):
    csv = _csv(
        "ΜΑΘ,ΠΠ,Α-ΛΥΚ,,2,",
        "ΞΕΝΟ,ΠΠ,Α-ΛΥΚ,,3,",  # invalid
    )
    result = preview(csv, db)
    summary = commit(result.rows, db)
    assert summary["status"] == "rejected"
    assert summary["created"] == 0
    # Make sure NOTHING was inserted (transactional)
    assert db.query(Lesson).count() == 0


def test_commit_empty_rows_is_noop(db):
    summary = commit([], db)
    assert summary["status"] == "ok"
    assert summary["created"] == 0
