"""Tests for backend.services.template_loader.

Covers:
  - listing the bundled templates
  - preview()/apply() behaviour with empty + populated DBs
  - idempotency: re-applying a template is a no-op for everything
    that already exists
  - SchoolSettings is *never* overwritten
  - graceful failure on missing/malformed template
"""
from __future__ import annotations

import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base
from backend.models import Subject, SchoolClass, Classroom, Constraint, SchoolSettings
from backend.services import template_loader as tl


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def test_list_templates_returns_bundled():
    """The 3 templates we ship should be discovered."""
    summaries = tl.list_templates()
    keys = {t.key for t in summaries}
    assert "frontistirio_lykeio" in keys
    assert "gymnasio" in keys
    assert "panellinies" in keys


def test_list_templates_summaries_have_label_and_description():
    summaries = tl.list_templates()
    for s in summaries:
        assert s.label, f"{s.key} missing label"
        assert s.description, f"{s.key} missing description"


def test_unknown_template_returns_friendly_error(db):
    result = tl.preview("does_not_exist", db)
    assert result.fatal_error is not None
    assert "δεν βρέθηκε" in result.fatal_error


# ---------------------------------------------------------------------------
# Preview — fresh DB
# ---------------------------------------------------------------------------

def test_preview_on_empty_db_will_create_everything(db):
    result = tl.preview("frontistirio_lykeio", db)
    assert result.fatal_error is None
    # All items in the JSON should be slated for creation
    assert result.will_create["subjects"] > 0
    assert result.will_create["classes"] > 0
    assert result.will_create["classrooms"] > 0
    assert result.will_create["constraints"] > 0
    # Nothing skipped
    assert sum(result.will_skip.values()) == 0


def test_preview_does_not_mutate_db(db):
    tl.preview("gymnasio", db)
    assert db.query(Subject).count() == 0
    assert db.query(SchoolClass).count() == 0
    assert db.query(Classroom).count() == 0


# ---------------------------------------------------------------------------
# Apply — fresh DB
# ---------------------------------------------------------------------------

def test_apply_on_empty_db_creates_everything(db):
    result = tl.apply("gymnasio", db)
    assert result.fatal_error is None
    assert result.created["subjects"] >= 5  # gymnasio has 7 subjects
    assert result.created["classes"] == 3   # 3 grades
    assert result.created["classrooms"] == 2

    # Verify they actually landed in the DB
    assert db.query(Subject).count() == 7
    assert db.query(SchoolClass).count() == 3
    assert db.query(Classroom).count() == 2


def test_apply_creates_school_settings_if_none(db):
    assert db.query(SchoolSettings).count() == 0
    tl.apply("gymnasio", db)
    assert db.query(SchoolSettings).count() == 1
    s = db.query(SchoolSettings).first()
    assert s.school_name == "Φροντιστήριο Γυμνασίου"


def test_apply_creates_constraints_with_serialized_rule(db):
    tl.apply("frontistirio_lykeio", db)
    constraints = db.query(Constraint).all()
    assert len(constraints) >= 1
    # The rule must be serialized as JSON string (not dict)
    for c in constraints:
        rule = json.loads(c.rule)
        assert "type" in rule


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_apply_twice_is_idempotent(db):
    """Re-applying the same template inserts NOTHING the second time."""
    first = tl.apply("frontistirio_lykeio", db)
    assert first.fatal_error is None
    first_total = first.total_created
    assert first_total > 0

    second = tl.apply("frontistirio_lykeio", db)
    assert second.fatal_error is None
    assert second.total_created == 0
    # Everything should be reported as 'skipped'
    assert sum(second.skipped.values()) >= first_total


def test_apply_does_not_overwrite_existing_school_settings(db):
    """SchoolSettings is sacred — never replaced by a template."""
    db.add(SchoolSettings(
        school_name="Custom School",
        days_per_week=4,
        institution_type="frontistirio",
    ))
    db.commit()

    tl.apply("gymnasio", db)
    s = db.query(SchoolSettings).first()
    assert s.school_name == "Custom School"
    assert s.days_per_week == 4


def test_apply_skips_subjects_with_existing_short_name(db):
    """Idempotency by short_name OR name."""
    db.add(Subject(name="My Math",
                   short_name="ΜΑΘ",  # collides with template's ΜΑΘ
                   color="#000000"))
    db.commit()

    result = tl.apply("frontistirio_lykeio", db)
    # The Math subject from the template should be skipped
    assert result.skipped["subjects"] >= 1
    # We still have only one ΜΑΘ
    math_count = db.query(Subject).filter(Subject.short_name == "ΜΑΘ").count()
    assert math_count == 1
    # And the existing one wasn't overwritten
    existing = db.query(Subject).filter(Subject.short_name == "ΜΑΘ").first()
    assert existing.name == "My Math"


def test_apply_skips_classroom_with_existing_name(db):
    db.add(Classroom(name="Αίθουσα 1", short_name="X1"))
    db.commit()
    result = tl.apply("gymnasio", db)
    # ΑΙΘ-1 from the template should skip due to name match
    assert result.skipped["classrooms"] >= 1


# ---------------------------------------------------------------------------
# Multi-template scenario
# ---------------------------------------------------------------------------

def test_can_apply_two_templates_back_to_back(db):
    """Loading both gymnasio + lykeio adds the union of their items
    (with the overlap, e.g. shared subjects, deduplicated)."""
    r1 = tl.apply("gymnasio", db)
    assert r1.fatal_error is None

    r2 = tl.apply("frontistirio_lykeio", db)
    assert r2.fatal_error is None

    # Total subjects in DB equals union, not sum
    subj_names = {s.short_name for s in db.query(Subject).all()}
    # ΜΑΘ exists in both templates → only one entry
    math_count = db.query(Subject).filter(Subject.short_name == "ΜΑΘ").count()
    assert math_count == 1

    # Lykeio-only subject
    assert "ΛΑΤ" in subj_names
    # Gymnasio also has ΑΓΓ
    assert "ΑΓΓ" in subj_names


# ---------------------------------------------------------------------------
# Error / partial failure
# ---------------------------------------------------------------------------

def test_apply_with_unknown_key_returns_fatal_error(db):
    result = tl.apply("does_not_exist", db)
    assert result.fatal_error is not None
    assert result.total_created == 0


# ---------------------------------------------------------------------------
# Encoding (W01): τα templates είναι ελληνικά — διαβάζονται πάντα ως utf-8,
# ανεξάρτητα από το locale, και ένα χαλασμένο αρχείο παραλείπεται (όχι 500)
# ---------------------------------------------------------------------------

def test_templates_load_under_non_utf8_locale():
    """Με locale ASCII (ή Windows cp1252) το read_text() χωρίς encoding
    σκάει σε UnicodeDecodeError στα ελληνικά. Τρέχει σε subprocess γιατί το
    locale encoding κλειδώνει στην εκκίνηση του interpreter."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0",
        "LC_ALL": "C", "LANG": "C",
        "PYTHONPATH": str(root),
    }
    script = (
        "import json\n"
        "from backend.services import template_loader as tl\n"
        "keys = [t.key for t in tl.list_templates()]\n"
        "labels = {k: tl._load_template(k)['label'] for k in keys}\n"
        "print(json.dumps(labels))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], cwd=root, env=env,
        capture_output=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    labels = json.loads(proc.stdout)
    assert {"frontistirio_lykeio", "gymnasio", "panellinies"} <= set(labels)
    # Τα ελληνικά labels διαβάστηκαν σωστά (όχι mojibake).
    for key, label in labels.items():
        assert label == tl._load_template(key)["label"]


def test_bad_template_files_are_skipped_not_raised(db, tmp_path, monkeypatch):
    """Μη-utf-8 αρχείο ή χαλασμένο JSON: η λίστα το παραλείπει και το
    preview/apply επιστρέφει φιλικό fatal_error — ποτέ 500."""
    good = {"key": "good", "label": "Φροντιστήριο", "description": "Καλό"}
    (tmp_path / "good.json").write_text(json.dumps(good, ensure_ascii=False),
                                        encoding="utf-8")
    (tmp_path / "latin.json").write_bytes(
        '{"key": "latin", "label": "Λύκειο"}'.encode("cp1253"))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(tl, "TEMPLATES_DIR", tmp_path)

    assert [t.key for t in tl.list_templates()] == ["good"]
    assert tl.list_templates()[0].label == "Φροντιστήριο"
    for key in ("latin", "broken"):
        assert tl.preview(key, db).fatal_error is not None
        assert tl.apply(key, db).fatal_error is not None
