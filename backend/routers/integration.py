"""Integration endpoints — προς το παρόν: εισαγωγή μαθητών από το Korifi CRM.

Read-only preview + explicit commit, ώστε ο χρήστης να βλέπει τι θα εισαχθεί
πριν πατήσει εισαγωγή. Τερματίζει τη διπλή καταχώρηση μαθητών στα δύο συστήματα.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services import crm_importer

router = APIRouter()


class CrmStudent(BaseModel):
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None


class CrmImportRequest(BaseModel):
    students: list[CrmStudent]


@router.get("/crm/students/preview")
def preview_crm_students(db: Session = Depends(get_db)):
    """Δείξε ποιοι μαθητές του CRM είναι νέοι για το EDS και ποιοι υπάρχουν ήδη.
    Δεν γράφει τίποτα. Αν το CRM είναι απροσπέλαστο, available=false + λόγος."""
    return crm_importer.preview(db).to_dict()


@router.post("/crm/students/import")
def import_crm_students(data: CrmImportRequest, db: Session = Depends(get_db)):
    """Εισαγωγή των επιλεγμένων μαθητών (μόνο νέοι — τα διπλά αγνοούνται)."""
    return crm_importer.commit([s.model_dump() for s in data.students], db)
