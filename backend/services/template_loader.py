"""Pre-baked starter templates for new EduScheduler installations.

Each template is a JSON file under backend/templates/ describing
subjects + classes + classrooms + constraints + school_settings for a
specific school type (Φροντιστήριο Γυμνασίου, Φροντιστήριο Λυκείου,
Πανελλήνιες). The loader inserts only entries that don't already exist
(matched by short_name OR name), so applying the same template twice
is a no-op for the second run.

Two-phase API:
  list_templates() → discovery: which templates ship with the app
  preview(key, db) → counts of items that WOULD be inserted (idempotent)
  apply(key, db)  → actually insert the new rows
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import (
    Subject, Teacher, SchoolClass, Classroom, Constraint, SchoolSettings,
)


TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------

@dataclass
class TemplateSummary:
    key: str
    label: str
    description: str


@dataclass
class ApplyPreview:
    """What WOULD happen if we applied the template now."""
    template: TemplateSummary
    will_create: dict[str, int] = field(default_factory=dict)
    will_skip: dict[str, int] = field(default_factory=dict)
    fatal_error: Optional[str] = None


@dataclass
class ApplyResult:
    template: TemplateSummary
    created: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    fatal_error: Optional[str] = None

    @property
    def total_created(self) -> int:
        return sum(self.created.values())


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def list_templates() -> list[TemplateSummary]:
    """Scan the templates directory and return summaries.

    Skips files that don't parse — surfaces them as silently ignored;
    a malformed template should not break the listing endpoint.
    """
    out: list[TemplateSummary] = []
    if not TEMPLATES_DIR.exists():
        return out
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out.append(TemplateSummary(
            key=data.get("key", path.stem),
            label=data.get("label", path.stem),
            description=data.get("description", ""),
        ))
    return out


def _load_template(key: str) -> Optional[dict]:
    """Read the named template's raw JSON, or None if not found."""
    path = TEMPLATES_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Preview / Apply
# ---------------------------------------------------------------------------

def preview(key: str, db: Session) -> ApplyPreview:
    """Read-only — counts of what the apply would insert vs. skip.

    Idempotency rule: an item is 'skipped' when an existing row already
    has the same short_name OR the same name (case-insensitive). The
    user can re-apply a template without fear of duplicates.
    """
    data = _load_template(key)
    if data is None:
        # Build a stub summary so the caller can still surface an error
        return ApplyPreview(
            template=TemplateSummary(key=key, label=key, description=""),
            fatal_error=f"Template '{key}' δεν βρέθηκε",
        )

    summary = TemplateSummary(
        key=data.get("key", key),
        label=data.get("label", key),
        description=data.get("description", ""),
    )

    will_create: dict[str, int] = {}
    will_skip: dict[str, int] = {}

    for kind, model, items in (
        ("subjects",   Subject,     data.get("subjects",   [])),
        ("classes",    SchoolClass, data.get("classes",    [])),
        ("classrooms", Classroom,   data.get("classrooms", [])),
    ):
        existing = _name_index(db.query(model).all())
        creates = sum(1 for item in items if not _is_duplicate(item, existing))
        skips = len(items) - creates
        will_create[kind] = creates
        will_skip[kind] = skips

    constraints = data.get("constraints", [])
    existing_constraint_names = {
        (c.name or "").strip().lower()
        for c in db.query(Constraint).all()
    }
    new_c = sum(
        1 for c in constraints
        if (c.get("name", "").strip().lower()) not in existing_constraint_names
    )
    will_create["constraints"] = new_c
    will_skip["constraints"] = len(constraints) - new_c

    return ApplyPreview(
        template=summary,
        will_create=will_create,
        will_skip=will_skip,
    )


def apply(key: str, db: Session) -> ApplyResult:
    """Apply the template: insert every entry that doesn't already exist.

    Single transaction — rollback on any SQLAlchemy error. Existing
    rows are NEVER updated; templates are additive only.
    """
    data = _load_template(key)
    if data is None:
        return ApplyResult(
            template=TemplateSummary(key=key, label=key, description=""),
            fatal_error=f"Template '{key}' δεν βρέθηκε",
        )

    summary = TemplateSummary(
        key=data.get("key", key),
        label=data.get("label", key),
        description=data.get("description", ""),
    )

    created: dict[str, int] = {"subjects": 0, "classes": 0, "classrooms": 0,
                               "constraints": 0}
    skipped: dict[str, int] = {"subjects": 0, "classes": 0, "classrooms": 0,
                               "constraints": 0}

    try:
        # Subjects / classes / classrooms — name+short_name idempotency
        for kind, model, items in (
            ("subjects",   Subject,     data.get("subjects",   [])),
            ("classes",    SchoolClass, data.get("classes",    [])),
            ("classrooms", Classroom,   data.get("classrooms", [])),
        ):
            existing = _name_index(db.query(model).all())
            for item in items:
                if _is_duplicate(item, existing):
                    skipped[kind] += 1
                    continue
                db.add(model(**_filter_fields(model, item)))
                created[kind] += 1
                # Update the index so we don't insert two items in
                # the same template that collide with each other.
                existing |= _keys_for(item)

        # Constraints — match by name only (no short_name on Constraint)
        existing_names = {
            (c.name or "").strip().lower()
            for c in db.query(Constraint).all()
        }
        for c in data.get("constraints", []):
            cname = (c.get("name", "") or "").strip().lower()
            if cname in existing_names:
                skipped["constraints"] += 1
                continue
            rule_dict = c.get("rule", {})
            db.add(Constraint(
                name=c.get("name", "Imported Constraint"),
                constraint_type=c.get("constraint_type", "soft"),
                category=c.get("category", "general"),
                weight=int(c.get("weight", 50)),
                rule=json.dumps(rule_dict, ensure_ascii=False),
                is_active=c.get("is_active", True),
                entity_id=c.get("entity_id"),
                entity_type=c.get("entity_type"),
            ))
            created["constraints"] += 1

        # School settings — only created if no row exists at all (we
        # never overwrite a configured school).
        ss_payload = data.get("school_settings")
        if ss_payload and not db.query(SchoolSettings).first():
            db.add(SchoolSettings(**_filter_fields(SchoolSettings, ss_payload)))
            created["settings"] = 1
        elif ss_payload:
            skipped["settings"] = 1

        db.commit()
        return ApplyResult(
            template=summary, created=created, skipped=skipped,
        )

    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return ApplyResult(
            template=summary, fatal_error=f"Apply failed (rollback): {exc}",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _name_index(rows) -> set[str]:
    """Idempotency keys — both name and short_name, lowercased."""
    out: set[str] = set()
    for r in rows:
        for attr in ("name", "short_name"):
            v = getattr(r, attr, None)
            if v:
                out.add(v.strip().lower())
    return out


def _keys_for(item: dict) -> set[str]:
    """All idempotency keys for an incoming item — both its name and
    its short_name, lowercased. An item is treated as a duplicate of
    an existing row if ANY of its keys overlaps with the existing
    name-index."""
    out: set[str] = set()
    for attr in ("name", "short_name"):
        v = item.get(attr)
        if v:
            out.add(v.strip().lower())
    return out


def _is_duplicate(item: dict, existing: set[str]) -> bool:
    return bool(_keys_for(item) & existing)


def _filter_fields(model, payload: dict) -> dict:
    """Drop keys that aren't real columns on the model — keeps us
    forward-compatible if the JSON gains documentation-only fields."""
    cols = {c.name for c in model.__table__.columns}
    return {k: v for k, v in payload.items() if k in cols}
