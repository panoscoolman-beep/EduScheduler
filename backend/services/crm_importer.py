"""Import students from Korifi CRM into EduScheduler (one-way pull).

Το CRM είναι master για τα προσωπικά στοιχεία μαθητών· το EDS τους χρειάζεται
για το scheduling. Αυτό το service τερματίζει τη ΔΙΠΛΗ ΚΑΤΑΧΩΡΗΣΗ: γράφεις
τον μαθητή μία φορά στο CRM και τον «τραβάς» στο EDS με ροή preview → commit
(ίδιο pattern με το lesson_importer).

Η κλήση REST στο CRM (GET /api/students) απομονώνεται στο fetch_crm_students()
ώστε η λογική αντιστοίχισης/ταξινόμησης (classify) να μένει pure και
unit-testable χωρίς ζωντανό CRM. Το EDS backend φτάνει το CRM api μέσω του
κοινού docker network `korifi-integration` (container name).

Συνδέσεις του CRM (GET /api/eds-sync/students/links, fetch_crm_links()): ένας
μαθητής του CRM που έχει «🔗 συνδεθεί» με μαθητή του EDS γραμμένο αλλιώς
(Γεώργιος/Γιώργος) είναι «υπάρχει ήδη» — δεν ξαναφτιάχνεται. Fail-soft: παλιό
CRM χωρίς το endpoint (404) ή οποιοδήποτε σφάλμα → αντιστοίχιση μόνο με όνομα,
δηλαδή ακριβώς η παλιά συμπεριφορά.

Env:
    KORIFI_API_BASE   default http://korifi-crm-v2-api-1:8000
    KORIFI_API_TOKEN  ο ίδιος bearer του CRM (fail-closed: χωρίς αυτό, unavailable)
"""
from __future__ import annotations

import logging
import math
import os
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import Student

DEFAULT_CRM_BASE = "http://korifi-crm-v2-api-1:8000"
_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Name normalization (Greek-aware) — κοινή λογική με το bot side
# ---------------------------------------------------------------------------

def _normalize_gr(s: str) -> str:
    """lower + strip τόνων + ενοποίηση τελικού ς→σ, ώστε «Νίκη»/«ΝΙΚΗ»/«νικη»
    να ταιριάζουν και να μη δημιουργούνται διπλοεγγραφές."""
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                if unicodedata.category(c) != "Mn")
    return s.replace("ς", "σ").strip()


def _name_key(first: str, last: str) -> str:
    return f"{_normalize_gr(first)} {_normalize_gr(last)}".strip()


def _contact(value):
    """email/τηλέφωνο από το CRM. Ένα bug του CRM (pandas NaN → κείμενο «nan»)
    έγραφε «nan» σε κενά πεδία επικοινωνίας: «nan» (οποιαδήποτε κεφαλαία, με ή
    χωρίς κενά γύρω) ή NaN αριθμός = ΚΕΝΟ. Μόνο ακριβές ταίριασμα — «Nancy»,
    «banana», «nan2» μένουν ως έχουν· κάθε άλλη τιμή όπως πριν (`or None`).
    Τα ονόματα δεν περνούν ποτέ από εδώ."""
    if isinstance(value, str) and value.strip().lower() == "nan":
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value or None


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class ImportRow:
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    crm_id: Optional[int] = None
    status: str = "new"          # "new" | "exists"
    eds_student_id: Optional[int] = None  # όταν status == "exists"

    def to_dict(self) -> dict:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "crm_id": self.crm_id,
            "status": self.status,
            "eds_student_id": self.eds_student_id,
        }


@dataclass
class PreviewResult:
    available: bool = True
    rows: list[ImportRow] = field(default_factory=list)
    fatal_error: Optional[str] = None

    @property
    def new_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "new")

    @property
    def exists_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "exists")

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "fatal_error": self.fatal_error,
            "new_count": self.new_count,
            "exists_count": self.exists_count,
            "rows": [r.to_dict() for r in self.rows],
        }


# ---------------------------------------------------------------------------
# Pure classification (no DB, no HTTP) — the testable core
# ---------------------------------------------------------------------------

def classify(crm_students: list[dict], eds_students: list,
             links: Optional[dict] = None) -> list[ImportRow]:
    """Ταξινόμησε κάθε CRM μαθητή σε 'new' ή 'exists' (κατά κανονικοποιημένο
    ονοματεπώνυμο). Pure: δέχεται λίστες, δεν αγγίζει DB/δίκτυο.

    De-dup: αν το CRM στέλνει τον ίδιο μαθητή δύο φορές (π.χ. πολλαπλές
    εγγραφές τμημάτων), κρατιέται μία φορά.

    `links` = {crm_id: eds_id} (συνδέσεις του CRM): μαθητής συνδεδεμένος με
    μαθητή που ΥΠΑΡΧΕΙ εδώ είναι 'exists' με εκείνο το id, όποια κι αν είναι η
    γραφή του ονόματος. Μπαίνουν πρώτοι, ώστε το de-dup κατά όνομα να κρατά
    αυτούς και όχι έναν ασύνδετο συνονόματο. Σύνδεση προς μαθητή που δεν
    υπάρχει πια εδώ αγνοείται (ισχύει το όνομα). Χωρίς links = η παλιά λογική.
    """
    existing = {}
    for s in eds_students:
        existing[_name_key(s.first_name, s.last_name)] = s.id
    eds_ids = {s.id for s in eds_students}

    def linked_id(cs: dict) -> Optional[int]:
        try:
            eds_id = (links or {}).get(int(cs.get("id")))
        except (TypeError, ValueError):
            return None
        return eds_id if eds_id in eds_ids else None

    rows: list[ImportRow] = []
    seen: set[str] = set()
    # sorted() είναι σταθερό: χωρίς συνδέσεις η σειρά (και το de-dup) μένει ίδια.
    for cs in sorted(crm_students, key=lambda cs: linked_id(cs) is None):
        first = (cs.get("first_name") or "").strip()
        last = (cs.get("last_name") or "").strip()
        if not first or not last:
            continue
        key = _name_key(first, last)
        if key in seen:
            continue
        seen.add(key)
        eds_id = linked_id(cs)
        if eds_id is None:
            eds_id = existing.get(key)
        rows.append(ImportRow(
            first_name=first, last_name=last,
            email=_contact(cs.get("email")),
            phone=_contact(cs.get("phone")),
            crm_id=cs.get("id"),
            status="exists" if eds_id else "new",
            eds_student_id=eds_id,
        ))
    rows.sort(key=lambda r: _name_key(r.first_name, r.last_name))
    return rows


# ---------------------------------------------------------------------------
# CRM REST fetch (isolated I/O)
# ---------------------------------------------------------------------------

def _crm_config() -> tuple[str, str]:
    base = os.environ.get("KORIFI_API_BASE", DEFAULT_CRM_BASE).rstrip("/")
    token = os.environ.get("KORIFI_API_TOKEN", "")
    return base, token


def fetch_crm_students() -> tuple[list[dict], Optional[str]]:
    """(students, None) ή ([], error_message). Βρίσκει την ΕΝΕΡΓΗ περίοδο του
    CRM και επιστρέφει τους ενεργούς μαθητές της. Fail-closed χωρίς token."""
    import httpx

    base, token = _crm_config()
    if not token:
        return [], "Λείπει το KORIFI_API_TOKEN — η εισαγωγή από CRM είναι απενεργοποιημένη."
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=20) as client:
            periods = client.get(f"{base}/api/periods", headers=headers)
            periods.raise_for_status()
            active = next((p for p in periods.json() if p.get("is_active")), None)
            if not active:
                plist = periods.json()
                active = plist[0] if plist else None
            if not active:
                return [], "Το CRM δεν έχει ακαδημαϊκή περίοδο."
            resp = client.get(f"{base}/api/students",
                              params={"period_id": active["id"]}, headers=headers)
            resp.raise_for_status()
            return resp.json(), None
    except httpx.HTTPStatusError as e:
        return [], f"Το CRM απάντησε {e.response.status_code}."
    except httpx.HTTPError as e:
        return [], f"Αδύνατη σύνδεση με το CRM: {e}"


def fetch_crm_links() -> dict[int, int]:
    """{crm_id: eds_id} — οι συνδέσεις μαθητών του CRM με μαθητές του EDS
    (GET /api/eds-sync/students/links). ΠΟΤΕ δεν σηκώνει: παλιό CRM χωρίς το
    endpoint (404), δίκτυο, απρόσμενη μορφή → {} = αντιστοίχιση μόνο με
    όνομα, δηλαδή ακριβώς η συμπεριφορά πριν υπάρξει το endpoint."""
    base, token = _crm_config()
    if not token:
        return {}
    try:
        import httpx

        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{base}/api/eds-sync/students/links",
                              headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            body = resp.json()
        return {int(k): int(v) for k, v in body.items() if v is not None}
    except Exception as exc:  # noqa: BLE001 — fail-soft
        _log.warning("Συνδέσεις μαθητών από το CRM μη διαθέσιμες (μόνο κατά όνομα): %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Two-phase public API
# ---------------------------------------------------------------------------

def preview(db: Session) -> PreviewResult:
    """Read-only: τι θα εισαχθεί από το CRM (νέοι) vs τι υπάρχει ήδη."""
    crm_students, err = fetch_crm_students()
    if err:
        return PreviewResult(available=False, fatal_error=err)
    eds_students = db.query(Student).all()
    return PreviewResult(rows=classify(crm_students, eds_students, fetch_crm_links()))


def commit(students: list[dict], db: Session) -> dict:
    """Εισαγωγή των επιλεγμένων νέων μαθητών σε μία συναλλαγή (rollback σε
    σφάλμα). Ξαναελέγχει το duplicate ΤΩΡΑ (ο κατάλογος μπορεί να άλλαξε
    από το preview) — ποτέ δεν δημιουργεί διπλοεγγραφή. Επιστρέφει counts."""
    existing = {_name_key(s.first_name, s.last_name) for s in db.query(Student).all()}
    created, skipped = 0, 0
    try:
        for s in students:
            first = (s.get("first_name") or "").strip()
            last = (s.get("last_name") or "").strip()
            if not first or not last:
                skipped += 1
                continue
            key = _name_key(first, last)
            if key in existing:
                skipped += 1
                continue
            existing.add(key)
            db.add(Student(first_name=first, last_name=last,
                           email=_contact(s.get("email")),
                           phone=_contact(s.get("phone"))))
            created += 1
        db.commit()
        return {"status": "ok", "created": created, "skipped": skipped}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {"status": "error", "message": f"Transaction failed (rollback): {exc}",
                "created": 0, "skipped": 0}
