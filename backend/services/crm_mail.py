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
    return False, _detail_text(res) or f"CRM {res.status_code}"


def _detail_text(res) -> str | None:
    """Το `detail` της απάντησης του CRM ως κείμενο για τον ιδιοκτήτη.

    String → ως έχει. Λίστα σφαλμάτων επικύρωσης (422 του FastAPI) → «πεδίο:
    μήνυμα» για τα πρώτα 5, αντί για σκέτο «CRM 422» που δεν έλεγε τι
    απορρίφθηκε. Οτιδήποτε άλλο (όχι JSON, JSON χωρίς dict) → None."""
    try:
        body = res.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if not isinstance(detail, list):
        return None
    parts = []
    for err in detail[:5]:
        if not isinstance(err, dict):
            continue
        loc = ".".join(str(x) for x in (err.get("loc") or []) if x != "body")
        msg = str(err.get("msg") or "").strip()
        if msg:
            parts.append(f"{loc}: {msg}" if loc else msg)
    if not parts:
        return None
    more = f" (+{len(detail) - 5} ακόμα)" if len(detail) > 5 else ""
    return f"Το CRM απέρριψε τα δεδομένα ({res.status_code}): " + "; ".join(parts) + more
