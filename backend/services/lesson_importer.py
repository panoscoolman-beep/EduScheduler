"""Bulk-import service for lesson cards.

Two-phase workflow:
  1. preview(csv_text, db) → returns parsed rows + per-row errors so
     the user sees what would happen before committing
  2. commit(parsed_rows, db) → inserts all rows in a single transaction;
     all-or-nothing rollback if anything fails

CSV format (header row required, comma-separated, trim/case-insensitive
on lookups):

    subject,teacher,class,classroom,periods_per_week,distribution

Where:
  subject     → Subject.name OR Subject.short_name
  teacher     → Teacher.name OR Teacher.short_name
  class       → SchoolClass.name OR SchoolClass.short_name
  classroom   → Classroom.name OR Classroom.short_name (optional, blank = auto)
  periods     → integer 1-20
  distribution→ optional, e.g. "2,2,1" — must sum to periods_per_week
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import (
    Subject, Teacher, SchoolClass, Classroom, Lesson, Period,
)


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = ["subject", "teacher", "class", "periods_per_week"]
OPTIONAL_COLUMNS = ["classroom", "distribution"]
ALL_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


@dataclass
class PreviewRow:
    """One parsed row, with the lookups already resolved (or error)."""
    line_number: int
    raw: dict[str, str]
    subject_id: Optional[int] = None
    teacher_id: Optional[int] = None
    class_id: Optional[int] = None
    classroom_id: Optional[int] = None
    periods_per_week: Optional[int] = None
    distribution: Optional[str] = None
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_lesson_kwargs(self) -> dict:
        return {
            "subject_id": self.subject_id,
            "teacher_id": self.teacher_id,
            "class_id": self.class_id,
            "classroom_id": self.classroom_id,
            "periods_per_week": self.periods_per_week,
            "duration": 1,
            "distribution": self.distribution,
            "is_locked": False,
        }


@dataclass
class PreviewResult:
    rows: list[PreviewRow] = field(default_factory=list)
    fatal_error: Optional[str] = None  # CSV parsing or missing-headers level

    @property
    def valid_count(self) -> int:
        return sum(1 for r in self.rows if r.is_valid)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.rows if not r.is_valid)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preview(csv_text: str, db: Session) -> PreviewResult:
    """Parse CSV text and resolve every lookup. Doesn't touch the DB
    beyond reads. Caller can show the rows to the user before deciding
    whether to commit."""
    if not csv_text or not csv_text.strip():
        return PreviewResult(fatal_error="Άδειο CSV")

    try:
        reader = csv.reader(io.StringIO(csv_text))
        rows_raw = list(reader)
    except csv.Error as e:
        return PreviewResult(fatal_error=f"CSV parsing error: {e}")

    if not rows_raw:
        return PreviewResult(fatal_error="Άδειο CSV")

    headers = [_normalize(h) for h in rows_raw[0]]
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        return PreviewResult(
            fatal_error=f"Λείπουν υποχρεωτικές στήλες: {', '.join(missing)}"
        )

    # Lookup tables — fetch once, lower/strip for case-insensitive matching
    subject_idx = _build_index(db.query(Subject).all())
    teacher_idx = _build_index(db.query(Teacher).all())
    class_idx = _build_index(db.query(SchoolClass).all())
    classroom_idx = _build_index(db.query(Classroom).all())
    teaching_periods = (
        db.query(Period).filter(Period.is_break == False).count()  # noqa: E712
    )

    # Find the index of "distribution" column — anything PAST it gets
    # joined back into distribution, since user-typed distributions
    # ("2,2,1") collide with CSV's own comma separator.
    try:
        dist_idx = headers.index("distribution")
    except ValueError:
        dist_idx = -1

    result = PreviewResult()
    for line_no, raw_row in enumerate(rows_raw[1:], start=2):
        if not any(_strip(c) for c in raw_row):
            continue  # skip blank lines

        # Build the normalized dict, special-casing distribution to
        # absorb any trailing extra fields back into one string.
        norm: dict[str, str] = {}
        for i, header in enumerate(headers):
            if header == "distribution" and dist_idx >= 0:
                tail = raw_row[dist_idx:] if dist_idx < len(raw_row) else []
                norm["distribution"] = ",".join(_strip(p) for p in tail if _strip(p))
            elif i < len(raw_row):
                norm[header] = _strip(raw_row[i])
            else:
                norm[header] = ""

        row = PreviewRow(line_number=line_no, raw=norm)

        # Subject
        subj = subject_idx.get(_norm_lookup(norm.get("subject", "")))
        if not subj:
            row.errors.append(
                f"Subject '{norm.get('subject','')}' δεν βρέθηκε"
            )
        else:
            row.subject_id = subj.id

        # Teacher
        t = teacher_idx.get(_norm_lookup(norm.get("teacher", "")))
        if not t:
            row.errors.append(f"Teacher '{norm.get('teacher','')}' δεν βρέθηκε")
        else:
            row.teacher_id = t.id

        # Class
        c = class_idx.get(_norm_lookup(norm.get("class", "")))
        if not c:
            row.errors.append(f"Class '{norm.get('class','')}' δεν βρέθηκε")
        else:
            row.class_id = c.id

        # Classroom (optional)
        room_raw = norm.get("classroom", "")
        if room_raw:
            r = classroom_idx.get(_norm_lookup(room_raw))
            if not r:
                row.errors.append(f"Classroom '{room_raw}' δεν βρέθηκε")
            else:
                row.classroom_id = r.id

        # periods_per_week
        ppw_raw = norm.get("periods_per_week", "")
        try:
            ppw = int(ppw_raw)
            if ppw < 1 or ppw > 20:
                row.errors.append(f"periods_per_week={ppw} εκτός εύρους 1-20")
            else:
                row.periods_per_week = ppw
        except (ValueError, TypeError):
            row.errors.append(f"periods_per_week='{ppw_raw}' μη έγκυρο")
            ppw = None

        # Distribution (optional, but if present must be valid)
        dist_raw = norm.get("distribution", "")
        if dist_raw:
            ok, blocks_or_msg = _parse_distribution(dist_raw, ppw, teaching_periods)
            if ok:
                row.distribution = dist_raw
            else:
                row.errors.append(blocks_or_msg)

        result.rows.append(row)

    return result


def commit(rows: list[PreviewRow], db: Session) -> dict:
    """Insert every valid row in a single transaction. If any row fails,
    rolls back everything. Returns a summary dict.

    Caller is expected to have run preview() and either filtered to
    valid rows or accepted the warnings."""
    invalid = [r for r in rows if not r.is_valid]
    if invalid:
        return {
            "status": "rejected",
            "message": f"{len(invalid)} γραμμές είναι invalid — διόρθωσε πρώτα",
            "created": 0,
        }

    try:
        for r in rows:
            lesson = Lesson(**r.to_lesson_kwargs())
            db.add(lesson)
        db.commit()
        return {
            "status": "ok",
            "message": f"Δημιουργήθηκαν {len(rows)} lesson cards",
            "created": len(rows),
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "status": "error",
            "message": f"Transaction failed (rollback): {exc}",
            "created": 0,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Header normalization — lowercase, strip surrounding whitespace,
    treat 'periods/week' or 'periods per week' as 'periods_per_week'."""
    if s is None:
        return ""
    out = s.strip().lower()
    out = out.replace(" per ", "_per_")
    out = out.replace(" ", "_")
    out = out.replace("/", "_per_")
    return out


def _strip(v: str) -> str:
    return (v or "").strip()


def _norm_lookup(s: str) -> str:
    """Lookup key — case-insensitive trim. Greek-aware would be nice
    but for a small dataset exact lower() suffices."""
    return s.strip().lower()


def _build_index(rows) -> dict:
    """Index a list of ORM rows by both name and short_name (lower
    + stripped) so the user can use either in the CSV."""
    idx = {}
    for r in rows:
        if getattr(r, "name", None):
            idx[_norm_lookup(r.name)] = r
        if getattr(r, "short_name", None):
            idx[_norm_lookup(r.short_name)] = r
    return idx


def _parse_distribution(s: str, ppw: Optional[int], n_periods_per_day: int):
    """Returns (ok, blocks_list_or_error_message). Block sum must equal
    periods_per_week (if known) and no block can exceed periods/day."""
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not all(p.isdigit() for p in parts):
        return False, f"distribution='{s}': μόνο θετικοί ακέραιοι με κόμμα"
    blocks = [int(p) for p in parts]
    if any(b <= 0 for b in blocks):
        return False, f"distribution='{s}': όλα τα blocks ≥ 1"
    if ppw is not None and sum(blocks) != ppw:
        return False, f"distribution σύνολο={sum(blocks)} ≠ ppw={ppw}"
    if n_periods_per_day > 0 and max(blocks) > n_periods_per_day:
        return False, f"distribution: block {max(blocks)} > {n_periods_per_day} ωρών/μέρα"
    return True, blocks
