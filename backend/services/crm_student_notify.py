"""EduScheduler → CRM: «άλλαξαν τα στοιχεία αυτού του μαθητή».

Μετά από κάθε επεξεργασία μαθητή εδώ, στέλνουμε (στο παρασκήνιο) τα
στοιχεία του στο CRM. Το CRM αποφασίζει: τα εφαρμόζει ΜΟΝΟ αν ο μαθητής
είναι συνδεδεμένος και ο τρόπος συγχρονισμού του είναι «EduScheduler → CRM»
ή «και τα δύο» (ρύθμιση ανά μαθητή στο CRM). Αλλιώς απαντά `skipped`.

Αλλαγές που ΗΡΘΑΝ από το CRM (header `X-Sync-Origin: crm`) δεν
ξαναστέλνονται — αλλιώς ping-pong. Fail-soft: αποτυχία = μόνο log, η
αποθήκευση στο EduScheduler έχει ήδη γίνει.
"""
from __future__ import annotations

import logging

from backend.services.crm_importer import _crm_config

_log = logging.getLogger(__name__)
_TIMEOUT = 10
ORIGIN_HEADER = "x-sync-origin"
_FIELDS = ("first_name", "last_name", "email", "phone", "grade", "track")


def came_from_crm(headers) -> bool:
    return (headers.get(ORIGIN_HEADER) or "").strip().lower() == "crm"


def payload_for(student) -> dict:
    return {"eds_id": int(student.id), **{f: getattr(student, f, None) for f in _FIELDS}}


def notify_student_changed(payload: dict) -> str:
    """Στέλνει στο CRM. Επιστρέφει το action του CRM ή 'error'/'disabled'."""
    import httpx

    base, token = _crm_config()
    if not token:
        return "disabled"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            res = client.post(f"{base}/api/eds-sync/students/from-eds", json=payload,
                              headers={"Authorization": f"Bearer {token}"})
        res.raise_for_status()
        action = (res.json() or {}).get("action", "")
    except Exception as exc:  # noqa: BLE001 — fail-soft
        _log.warning("CRM notify για μαθητή %s απέτυχε: %s", payload.get("eds_id"), exc)
        return "error"
    if action == "updated":
        _log.info("CRM ενημερώθηκε για τον μαθητή %s", payload.get("eds_id"))
    return action
