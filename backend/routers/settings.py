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
