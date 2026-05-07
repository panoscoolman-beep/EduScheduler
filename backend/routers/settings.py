"""
Settings API — School / institution configuration.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import SchoolSettings
from backend.schemas import SchoolSettingsBase, SchoolSettingsResponse

router = APIRouter()


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
    for key, value in data.model_dump().items():
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
