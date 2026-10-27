"""
Settings API — School / institution configuration.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import (
    SchoolSettings, StudentAvailability, TeacherAvailability, Term, TimetableSlot,
    TimetableSolution,
)
from backend.schemas import SchoolSettingsBase, SchoolSettingsResponse
from backend.services.delete_guards import programme_label
from backend.services.placement_conflicts import day_name

router = APIRouter()


def _days_usage(db: Session, first_removed_day: int) -> tuple[list[dict], int]:
    """Τοποθετημένες ώρες σε ημέρες ≥ `first_removed_day` σε ΟΛΑ τα προγράμματα
    (ανά πρόγραμμα: όνομα, σενάριο, αρχειοθετημένο, πλήθος) και πόσα κωλύματα
    (καθηγητών + μαθητών, όλων των σεναρίων) υπάρχουν σε αυτές τις ημέρες."""
    rows = (
        # TimetableSlot.id keeps one row per slot (entities alone are de-duplicated).
        db.query(TimetableSlot.id, TimetableSlot.day_of_week, TimetableSolution, Term)
        .join(TimetableSolution, TimetableSolution.id == TimetableSlot.solution_id)
        .outerjoin(Term, Term.id == TimetableSolution.term_id)
        .filter(TimetableSlot.is_unplaced == False,  # noqa: E712
                TimetableSlot.day_of_week >= first_removed_day)
        .order_by(TimetableSolution.id)
        .all()
    )
    programmes: dict[int, dict] = {}
    for _slot_id, day, sol, term in rows:
        item = programmes.setdefault(sol.id, {
            "solution_id": sol.id, "solution_name": sol.name,
            "term_id": sol.term_id, "term_name": term.name if term else "",
            "archived": sol.archived_at is not None, "slots": 0, "days": [],
        })
        item["slots"] += 1
        if day not in item["days"]:
            item["days"].append(day)
    availability = (
        db.query(TeacherAvailability)
        .filter(TeacherAvailability.day_of_week >= first_removed_day,
                TeacherAvailability.status == "unavailable").count()
        + db.query(StudentAvailability)
        .filter(StudentAvailability.day_of_week >= first_removed_day,
                StudentAvailability.status == "unavailable").count()
    )
    return list(programmes.values()), availability


def _days_phrase(days: list[int]) -> str:
    names = [day_name(d) for d in sorted(days)]
    if len(names) == 1:
        return ("στο " if days[0] == 5 else "στην ") + names[0]
    return "σε " + ", ".join(names)


def _days_message(programmes: list[dict], availability: int) -> str:
    def listing(items):
        return ", ".join(f"{programme_label(dict(p, archived=False))} {p['slots']} ώρες"
                         for p in items)
    active = [p for p in programmes if not p["archived"]]
    archived = [p for p in programmes if p["archived"]]
    days = sorted({d for p in active for d in p["days"]})
    text = (f"Δεν άλλαξαν οι ημέρες: υπάρχουν τοποθετημένες ώρες {_days_phrase(days)}: "
            f"{listing(active)}. Μετακίνησέ τες ή στείλ' τες στην Παλέτα πρώτα.")
    if archived:
        text += (f" Ενημερωτικά: ώρες σε αυτές τις ημέρες έχουν και αρχειοθετημένα προγράμματα "
                 f"(δεν φαίνονται στις λίστες): {listing(archived)}.")
    if availability:
        text += f" Ενημερωτικά: σε αυτές τις ημέρες υπάρχουν και {availability} κωλύματα."
    return text


def _get_or_create_settings(db: Session) -> SchoolSettings:
    """Ensure a settings row exists and return it."""
    settings = db.query(SchoolSettings).filter(SchoolSettings.id == 1).first()
    if not settings:
        settings = SchoolSettings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("/", response_model=SchoolSettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    return _get_or_create_settings(db)


@router.put("/", response_model=SchoolSettingsResponse)
def update_settings(data: SchoolSettingsBase, db: Session = Depends(get_db)):
    settings = _get_or_create_settings(db)
    changes = data.model_dump(exclude_unset=True)
    # Λιγότερες ημέρες με τοποθετημένες ώρες σε ημέρα που αφαιρείται: οι ώρες
    # θα «χάνονταν» από πλέγμα/εκτυπώσεις (μένοντας στο .ics και στις
    # δημοσιεύσεις) και ο solver θα τις προσπερνούσε. 409, χωρίς force — ο
    # χρήστης τις μετακινεί ή τις στέλνει στην Παλέτα πρώτα.
    new_days = changes.get("days_per_week")
    if new_days is not None and new_days < settings.days_per_week:
        programmes, availability = _days_usage(db, new_days)
        if any(not p["archived"] for p in programmes):
            raise HTTPException(status_code=409, detail={
                "code": "days_in_use",
                "message": _days_message(programmes, availability),
                "programmes": programmes,
                "availability": availability,
            })
    # Μόνο ό,τι στάλθηκε: ένας παλιός (cached) client χωρίς τα νέα πεδία δεν
    # πρέπει να σβήσει π.χ. το ωράριο λειτουργίας.
    for key, value in changes.items():
        setattr(settings, key, value)
    db.commit()
    db.refresh(settings)
    return settings


# ---------------------------------------------------------------------------
# Pre-baked starter templates
# ---------------------------------------------------------------------------

@router.get("/templates")
def list_templates():
    """List the bundled starter templates."""
    from backend.services.template_loader import list_templates as svc_list
    return [
        {"key": t.key, "label": t.label, "description": t.description}
        for t in svc_list()
    ]


@router.post("/templates/{key}/preview")
def preview_template(key: str, db: Session = Depends(get_db)):
    """Read-only — show what the template would create vs. skip."""
    from backend.services.template_loader import preview as svc_preview
    result = svc_preview(key, db)
    return {
        "template": {
            "key": result.template.key,
            "label": result.template.label,
            "description": result.template.description,
        },
        "fatal_error": result.fatal_error,
        "will_create": result.will_create,
        "will_skip": result.will_skip,
    }


@router.post("/templates/{key}/apply")
def apply_template(key: str, db: Session = Depends(get_db)):
    """Insert every entry in the named template that doesn't already
    exist (idempotent by short_name OR name)."""
    from backend.services.template_loader import apply as svc_apply
    result = svc_apply(key, db)
    return {
        "template": {
            "key": result.template.key,
            "label": result.template.label,
            "description": result.template.description,
        },
        "fatal_error": result.fatal_error,
        "created": result.created,
        "skipped": result.skipped,
        "total_created": result.total_created,
    }
