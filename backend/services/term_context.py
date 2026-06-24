"""Active-term (scenario) resolution.

Every scoped read/write resolves the "current scenario" through here. The
Alembic migration guarantees at least one term exists (a default active one),
so this normally returns that id. Endpoints may also accept an explicit
?term_id= to override the active one.
"""
from sqlalchemy.orm import Session

from backend.models import Term


def get_active_term_id(db: Session) -> int | None:
    """Return the active term id, falling back to the first term."""
    term = (
        db.query(Term)
        .filter(Term.is_active.is_(True))
        .order_by(Term.id)
        .first()
    )
    if term is None:
        term = db.query(Term).order_by(Term.id).first()
    return term.id if term else None


def resolve_term_id(db: Session, term_id: int | None) -> int:
    """Resolve an explicit term_id or fall back to the active one.

    Raises ValueError if no term can be resolved (should not happen after the
    terms migration, which seeds a default active term)."""
    resolved = term_id if term_id is not None else get_active_term_id(db)
    if resolved is None:
        raise ValueError("Δεν υπάρχει ενεργό σενάριο.")
    return resolved
