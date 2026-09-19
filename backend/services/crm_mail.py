"""Αποστολή email καθηγητών μέσω του Korifi CRM.

Το SMTP (Gmail του φροντιστηρίου) και η δημιουργία PDF (reportlab + ελληνική
γραμματοσειρά) ζουν στο CRM· εδώ μόνο στέλνουμε τα δεδομένα. Ίδιο KORIFI_API_*
με την εισαγωγή μαθητών (crm_importer). Fail-closed χωρίς token.
"""
from __future__ import annotations

from backend.services.crm_importer import _crm_config

_TIMEOUT = 90   # SMTP + PDF μπορεί να πάρουν μερικά δευτερόλεπτα


def send_teacher_schedule(payload: dict) -> tuple[bool, str | None]:
    import httpx

    base, token = _crm_config()
    if not token:
        return False, "Λείπει το KORIFI_API_TOKEN — δεν μπορεί να σταλεί email."
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            res = client.post(f"{base}/api/eds-mail/teacher-schedule", json=payload,
                              headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        return False, f"Το CRM δεν απαντά: {exc}"
    if res.status_code == 200:
        return True, None
    try:
        detail = res.json().get("detail")
    except ValueError:
        detail = None
    return False, (detail if isinstance(detail, str) else None) or f"CRM {res.status_code}"
