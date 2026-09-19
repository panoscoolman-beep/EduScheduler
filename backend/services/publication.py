"""📢 Δημοσίευση προγράμματος — «τι άλλαξε για σένα» ανά καθηγητή.

Η δημοσίευση κρατά αυτοτελές στιγμιότυπο (snapshot) των τοποθετημένων ωρών.
Η επόμενη δημοσίευση του ίδιου σεναρίου συγκρίνεται με την προηγούμενη και
βγάζει για κάθε καθηγητή τις αλλαγές του και το πλήρες νέο πρόγραμμά του,
σε απλό κείμενο έτοιμο για προώθηση (Telegram/email/αντιγραφή).

Τίποτα εδώ δεν στέλνει μηνύματα: το bot του CRM παραλαμβάνει τα μηνύματα
και τα στέλνει ΜΟΝΟ στον ιδιοκτήτη, που τα προωθεί.
"""
from __future__ import annotations

import html
import json
from collections import defaultdict

from datetime import timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from backend.models import (
    Classroom, Lesson, Period, SolutionPublication, Teacher, TimetableSlot, TimetableSolution, utcnow_naive,
)
from backend.services.solution_diff import pair_changes

_DAYS = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
_TELEGRAM_BATCH = 5


class PublishError(ValueError):
    """Η δημοσίευση δεν επιτρέπεται· `code` για το 409 του router."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def snapshot_entries(db: Session, solution_id: int) -> list[dict]:
    """Τοποθετημένες ώρες ως αυτοτελείς εγγραφές, ταξινομημένες χρονικά."""
    slots = (
        db.query(TimetableSlot)
        .options(joinedload(TimetableSlot.lesson).joinedload(Lesson.subject),
                 joinedload(TimetableSlot.lesson).joinedload(Lesson.school_class))
        .filter(TimetableSlot.solution_id == solution_id,
                TimetableSlot.is_unplaced == False)  # noqa: E712
        .all()
    )
    periods = {p.id: p for p in db.query(Period).all()}
    rooms = {r.id: r.name for r in db.query(Classroom).all()}
    room_shorts = {r.id: (r.short_name or r.name) for r in db.query(Classroom).all()}
    teachers = {t.id: t.name for t in db.query(Teacher).all()}
    out = []
    for s in slots:
        lesson, period = s.lesson, periods.get(s.period_id)
        if lesson is None or period is None or s.day_of_week is None:
            continue
        subject = lesson.subject.name if lesson.subject else "Μάθημα"
        klass = lesson.school_class.name if lesson.school_class else ""
        out.append({
            "teacher_id": lesson.teacher_id,
            "teacher": teachers.get(lesson.teacher_id, "—"),
            "lesson_id": lesson.id,
            "label": f"{subject} ({klass})" if klass else subject,
            "day": s.day_of_week,
            "period_id": s.period_id,
            "start": period.start_time,
            "end": period.end_time,
            "room": rooms.get(s.classroom_id, "") if s.classroom_id else "",
            "subject": subject,
            "klass": klass,
            "room_short": room_shorts.get(s.classroom_id, "") if s.classroom_id else "",
        })
    return sorted(out, key=_entry_order)


def _entry_order(e: dict):
    return (e["day"], e["start"].zfill(5), e["label"])


def _position(e: dict):
    """Θέση σύγκρισης· η αλλαγή αίθουσας μετρά ως μετακίνηση."""
    return (e["day"], e["start"].zfill(5), e["period_id"], e["room"])


# ---------------------------------------------------------------------------
# «Τι άλλαξε για σένα» — pure
# ---------------------------------------------------------------------------

def teacher_changes(previous: list[dict], current: list[dict]) -> dict[int, dict]:
    """Αλλαγές ανά καθηγητή (μόνο όσοι άλλαξαν).

    Κλειδί (καθηγητής, «μάθημα (τμήμα)») — ό,τι βλέπει ο καθηγητής, όχι το
    εσωτερικό id της κάρτας: κάρτα που σβήστηκε και ξαναφτιάχτηκε στις ίδιες
    ώρες ΔΕΝ βγάζει ψεύτικο «➖ καταργείται / ➕ νέα ώρα». Μάθημα που άλλαξε
    καθηγητή βγαίνει ➖ στον παλιό και ➕ στον νέο."""
    def by_key(entries):
        grouped: dict[tuple, list[dict]] = defaultdict(list)
        for e in entries:
            grouped[(e["teacher_id"], e["label"])].append(e)
        return grouped

    prev, cur = by_key(previous), by_key(current)
    out: dict[int, dict] = {}
    for key in sorted(set(prev) | set(cur)):
        before = {_position(e): e for e in prev.get(key, [])}
        after = {_position(e): e for e in cur.get(key, [])}
        moved, removed, added, _same = pair_changes(before, after)
        if not (moved or removed or added):
            continue
        bucket = out.setdefault(key[0], {"moved": [], "added": [], "removed": []})
        bucket["moved"] += [{"from": before[f], "to": after[t]} for f, t in moved]
        bucket["removed"] += [before[p] for p in removed]
        bucket["added"] += [after[p] for p in added]
    return out


def _when(e: dict) -> str:
    return f"{_DAYS[e['day']] if 0 <= e['day'] < 7 else e['day']} {e['start']}–{e['end']}"


def _room(e: dict) -> str:
    return f" · {e['room']}" if e["room"] else ""


def _change_lines(changes: dict) -> list[str]:
    lines = []
    for m in changes["moved"]:
        f, t = m["from"], m["to"]
        if (f["day"], f["period_id"]) == (t["day"], t["period_id"]):
            lines.append(f"• {t['label']}: {_when(t)} — αίθουσα {f['room'] or '—'} → {t['room'] or '—'}")
        else:
            lines.append(f"• {t['label']}: {_when(f)} → {_when(t)}{_room(t)}")
    lines += [f"• ➕ {e['label']}: {_when(e)}{_room(e)} (νέα ώρα)" for e in changes["added"]]
    lines += [f"• ➖ {e['label']}: {_when(e)} (καταργείται)" for e in changes["removed"]]
    return lines


def _merged_blocks(entries: list[dict]) -> list[dict]:
    """Συνεχόμενες ώρες ίδιου μαθήματος/αίθουσας → ένα μπλοκ (16:00–18:00)."""
    blocks: list[dict] = []
    for e in sorted(entries, key=_entry_order):
        last = blocks[-1] if blocks else None
        if (last and last["day"] == e["day"] and last["label"] == e["label"]
                and last["room"] == e["room"] and last["end"] == e["start"]):
            last["end"] = e["end"]
        else:
            blocks.append(dict(e))
    return blocks


def schedule_lines(entries: list[dict]) -> list[str]:
    lines, day = [], None
    for b in _merged_blocks(entries):
        if b["day"] != day:
            day = b["day"]
            lines.append(_DAYS[day] if 0 <= day < 7 else str(day))
        lines.append(f"  {b['start']}–{b['end']} {b['label']}{_room(b)}")
    return lines


def teacher_message(teacher: str, entries: list[dict], changes: dict | None) -> str:
    """Το μήνυμα προς τον καθηγητή. changes=None → πρώτη δημοσίευση."""
    parts = ["📢 Ενημέρωση προγράμματος", f"👤 {teacher}", ""]
    if changes is not None and any(changes.values()):
        parts += ["🔄 Τι άλλαξε για σένα:", *_change_lines(changes), ""]
    elif changes is not None:
        parts += ["✅ Καμία αλλαγή για σένα.", ""]
    if entries:
        parts += [f"🗓 Το πρόγραμμά σου ({len(entries)} ώρες/εβδομάδα):", *schedule_lines(entries)]
    else:
        parts.append("🗓 Δεν έχεις πλέον ώρες σε αυτό το πρόγραμμα.")
    return "\n".join(parts).strip()


_DAYS_SHORT = ["Δευ", "Τρι", "Τετ", "Πεμ", "Παρ", "Σαβ", "Κυρ"]


def _hm(value: str) -> str:
    """«14:00» → «14», «14:30» → «14:30» (συμπαγές για κινητό)."""
    return value[:-3] if value.endswith(":00") else value


def _short_when(e: dict) -> str:
    return f"{_DAYS_SHORT[e['day']] if 0 <= e['day'] < 7 else e['day']} {e['start']}"


def _subject_of(e: dict) -> str:
    return e.get("subject") or e["label"]


def _klass_of(e: dict) -> str:
    return e.get("klass", "")


def telegram_message(teacher: str, entries: list[dict], changes: dict | None, hours: int) -> str:
    """Μορφή Telegram (parse_mode=HTML): αλλαγές πρώτα, μέρες με έντονα,
    συμπαγείς ώρες, το τμήμα σε πλάγια κάτω από το μάθημα."""
    esc = html.escape
    parts = [f"<b>{esc(teacher)}</b> · {hours} ώρες/εβδ."]
    if changes is not None and any(changes.values()):
        parts += ["", "🔄 <b>Αλλαγές</b>"]
        for m in changes["moved"]:
            f, t = m["from"], m["to"]
            if (f["day"], f["period_id"]) == (t["day"], t["period_id"]):
                parts.append(f"• {esc(_subject_of(t))}: {_short_when(t)} — αίθουσα "
                             f"{esc(f['room'] or '—')} → {esc(t['room'] or '—')}")
            else:
                parts.append(f"• {esc(_subject_of(t))}: {_short_when(f)} → {_short_when(t)}")
        parts += [f"• ➕ {esc(_subject_of(e))}: {_short_when(e)}" for e in changes["added"]]
        parts += [f"• ➖ {esc(_subject_of(e))}: {_short_when(e)} (καταργείται)" for e in changes["removed"]]
    elif changes is not None:
        parts += ["", "✅ Καμία αλλαγή για σένα"]
    day = None
    for b in _merged_blocks(entries):
        if b["day"] != day:
            day = b["day"]
            parts += ["", f"<b>{_DAYS[day] if 0 <= day < 7 else day}</b>"]
        room = f" · {esc(b.get('room_short') or b['room'])}" if b["room"] else ""
        klass = f"\n      <i>{esc(_klass_of(b))}</i>" if _klass_of(b) else ""
        parts.append(f"<code>{_hm(b['start'])}–{_hm(b['end'])}</code> {esc(_subject_of(b))}{room}{klass}")
    if not entries:
        parts += ["", "Δεν έχεις πλέον ώρες σε αυτό το πρόγραμμα."]
    return "\n".join(parts)


def change_lines(changes: dict | None) -> list[str]:
    """Οι αλλαγές σε απλές γραμμές (για το email)."""
    return [line.lstrip("• ") for line in _change_lines(changes)] if changes else []


def build_messages(previous: list[dict] | None, current: list[dict]) -> list[dict]:
    """Ένα μήνυμα για ΚΑΘΕ καθηγητή του προγράμματος (και όσους έφυγαν), με
    `changed`: ποιοι επηρεάζονται (όλοι, αν είναι η πρώτη δημοσίευση)."""
    by_teacher: dict[int, list[dict]] = defaultdict(list)
    names: dict[int, str] = {}
    for e in (previous or []) + current:
        names.setdefault(e["teacher_id"], e["teacher"])
    for e in current:
        by_teacher[e["teacher_id"]].append(e)
        names[e["teacher_id"]] = e["teacher"]

    affected = None if previous is None else teacher_changes(previous, current)
    empty = {"moved": [], "added": [], "removed": []}
    out = []
    for tid in set(by_teacher) | set(affected or {}):
        entries = by_teacher.get(tid, [])
        changes = None if affected is None else affected.get(tid, empty)
        name = names.get(tid, "—")
        out.append({
            "teacher_id": tid,
            "teacher": name,
            "hours": len(entries),
            "changed": affected is None or tid in affected,
            "changes": changes,
            "message": teacher_message(name, entries, changes),
            "telegram": telegram_message(name, entries, changes, len(entries)),
            "entries": entries,
        })
    return sorted(out, key=lambda m: (not m["changed"], m["teacher"]))


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

def latest_publication(db: Session, term_id: int) -> SolutionPublication | None:
    return (db.query(SolutionPublication)
            .filter(SolutionPublication.term_id == term_id)
            .order_by(SolutionPublication.published_at.desc(), SolutionPublication.id.desc())
            .first())


EMAIL_STALE_MINUTES = 20
_PUBLIC_MESSAGE_KEYS = ("teacher_id", "teacher", "changed", "hours", "message", "telegram", "email")


def _messages(pub: SolutionPublication) -> list[dict]:
    return json.loads(pub.messages_json or "[]")


def _email_counts(messages: list[dict]) -> dict:
    states = [m["email"]["status"] for m in messages if m.get("email")]
    return {"requested": len(states), "sent": states.count("sent"), "failed": states.count("failed"),
            "pending": states.count("pending")}


def publication_summary(pub: SolutionPublication | None) -> dict | None:
    if pub is None:
        return None
    messages = _messages(pub)
    affected = sum(1 for m in messages if m.get("changed", True))
    return {
        "id": pub.id,
        "solution_id": pub.solution_id,
        "solution_name": pub.solution_name,
        "published_at": pub.published_at.isoformat() if pub.published_at else None,
        "note": pub.note,
        "teachers": len(messages),
        "affected": affected,
        "teachers_notified": affected,
        "notify_telegram": pub.notify_telegram,
        "telegram_sent_at": pub.telegram_sent_at.isoformat() if pub.telegram_sent_at else None,
        "email_state": pub.email_state,
        "emails": _email_counts(messages),
    }


def publication_detail(db: Session, publication_id: int) -> dict | None:
    pub = db.query(SolutionPublication).filter(SolutionPublication.id == publication_id).first()
    if pub is None:
        return None
    return {**publication_summary(pub),
            "messages": [{k: m.get(k) for k in _PUBLIC_MESSAGE_KEYS} for m in _messages(pub)]}


def _check_publishable(db: Session, solution_id: int) -> TimetableSolution:
    sol = db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    if sol is None:
        raise LookupError("Το πρόγραμμα δεν βρέθηκε.")
    if sol.status == "generating":
        raise PublishError("generating", "Το πρόγραμμα υπολογίζεται ακόμα.")
    if sol.archived_at is not None:
        raise PublishError("archived", "Το πρόγραμμα είναι αρχειοθετημένο — επανέφερέ το πρώτα.")
    return sol


def preview(db: Session, solution_id: int) -> dict:
    """Τι θα γίνει αν δημοσιευτεί τώρα. Pure read."""
    sol = _check_publishable(db, solution_id)
    current = snapshot_entries(db, solution_id)
    prev_pub = latest_publication(db, sol.term_id)
    previous = json.loads(prev_pub.snapshot_json) if prev_pub else None
    messages = build_messages(previous, current)
    contacts = {t.id: t for t in db.query(Teacher).all()}
    entries = {}
    for m in messages:
        t = contacts.get(m["teacher_id"])
        m["email"] = (t.email or "").strip() if t else ""
        m["phone"] = (t.phone or "") if t else ""
        entries[m["teacher_id"]] = m.pop("entries")
    unplaced = (db.query(TimetableSlot)
                .filter(TimetableSlot.solution_id == solution_id,
                        TimetableSlot.is_unplaced == True)  # noqa: E712
                .count())
    return {
        "solution": {"id": sol.id, "name": sol.name},
        "previous": publication_summary(prev_pub),
        "first": prev_pub is None,
        "placed": len(current),
        "unplaced": unplaced,
        "affected": sum(1 for m in messages if m["changed"]),
        "teachers": messages,
        "_snapshot": current,
        "_entries": entries,
    }


def publish(db: Session, solution_id: int, note: str | None, notify_telegram: bool,
            email_teacher_ids: list[int] | None = None) -> SolutionPublication:
    """Καταγράφει τη δημοσίευση (χωρίς commit — το κάνει ο router). Τα email
    ΔΕΝ στέλνονται εδώ: σημειώνονται «pending» και τα στέλνει το send_emails."""
    data = preview(db, solution_id)
    if not data["placed"]:
        raise PublishError("empty", "Το πρόγραμμα δεν έχει καμία τοποθετημένη ώρα.")
    if not data["first"] and not data["affected"]:
        raise PublishError("no_changes", "Δεν άλλαξε τίποτα από την τελευταία δημοσίευση.")
    wanted = set(email_teacher_ids or [])
    stored = []
    for m in data["teachers"]:
        email = None
        if m["teacher_id"] in wanted:
            email = ({"to": m["email"], "status": "pending"} if m["email"]
                     else {"to": "", "status": "no_email"})
        stored.append({
            "teacher_id": m["teacher_id"], "teacher": m["teacher"], "changed": m["changed"],
            "hours": m["hours"], "message": m["message"], "telegram": m["telegram"],
            "change_lines": change_lines(m["changes"]), "email": email,
        })
    sol = db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    pub = SolutionPublication(
        term_id=sol.term_id,
        solution_id=sol.id,
        solution_name=sol.name,
        note=(note or "").strip() or None,
        snapshot_json=json.dumps(data["_snapshot"], ensure_ascii=False),
        messages_json=json.dumps(stored, ensure_ascii=False),
        notify_telegram=bool(notify_telegram),
        email_state="sending" if any(m["email"] and m["email"]["status"] == "pending" for m in stored) else None,
    )
    db.add(pub)
    db.flush()
    return pub


# ---------------------------------------------------------------------------
# Email (αποστολή μέσω CRM — βλ. services/crm_mail.py)
# ---------------------------------------------------------------------------

def email_payload(*, to: str, teacher: str, title: str, note: str | None, changes: list[str],
                  first: bool, entries: list[dict], ics: str | None, test: bool = False) -> dict:
    """Ό,τι χρειάζεται το CRM για να φτιάξει το email + PDF (όχι HTML εδώ)."""
    return {
        "to": to, "teacher": teacher, "title": title, "note": note or "", "changes": changes,
        "first": first, "test": test, "ics": ics or "",
        "entries": [{"day": e["day"], "start": e["start"], "end": e["end"],
                     "subject": _subject_of(e), "klass": _klass_of(e), "room": e["room"]}
                    for e in sorted(entries, key=_entry_order)],
    }


def _ics_for(db: Session, solution_id: int | None, teacher_id: int) -> str | None:
    if solution_id is None:
        return None
    from backend.routers.exports import build_ics
    try:
        return build_ics(db, solution_id, teacher_id=teacher_id)
    except Exception:  # noqa: BLE001 — το .ics είναι bonus, όχι λόγος να μη φύγει το email
        return None


def send_emails(db: Session, publication_id: int, sender) -> dict:
    """Στέλνει τα «pending» email μιας δημοσίευσης, ένα-ένα, με commit μετά από
    το καθένα (η πρόοδος φαίνεται ζωντανά). `sender(payload) -> (ok, error)`."""
    pub = db.query(SolutionPublication).filter(SolutionPublication.id == publication_id).first()
    if pub is None:
        return {}
    snapshot = json.loads(pub.snapshot_json or "[]")
    first = latest_before(db, pub) is None
    messages = _messages(pub)
    for m in messages:
        mail = m.get("email")
        if not mail or mail.get("status") != "pending":
            continue
        payload = email_payload(
            to=mail["to"], teacher=m["teacher"], title=pub.solution_name, note=pub.note,
            changes=m.get("change_lines") or [], first=first,
            entries=[e for e in snapshot if e["teacher_id"] == m["teacher_id"]],
            ics=_ics_for(db, pub.solution_id, m["teacher_id"]))
        try:
            ok, error = sender(payload)
        except Exception as exc:  # noqa: BLE001
            ok, error = False, str(exc)
        mail.update({"status": "sent" if ok else "failed", "error": None if ok else (error or "άγνωστο σφάλμα"),
                     "at": utcnow_naive().isoformat()})
        pub.messages_json = json.dumps(messages, ensure_ascii=False)
        db.commit()
    pub.email_state = "done"
    db.commit()
    return _email_counts(messages)


def request_emails(db: Session, publication_id: int, teacher_ids: list[int]) -> SolutionPublication:
    """✉️ Email για ΥΠΑΡΧΟΥΣΑ δημοσίευση (π.χ. δημοσιεύτηκε χωρίς email, ή
    ξαναστείλιμο σε όσους απέτυχαν). Μόνο η πιο πρόσφατη του σεναρίου — μια
    παλιότερη θα έστελνε ξεπερασμένο πρόγραμμα. Χωρίς commit."""
    pub = db.query(SolutionPublication).filter(SolutionPublication.id == publication_id).first()
    if pub is None:
        raise LookupError("Η δημοσίευση δεν βρέθηκε.")
    if latest_publication(db, pub.term_id).id != pub.id:
        raise PublishError("not_latest", "Υπάρχει νεότερη δημοσίευση — στείλε από εκείνη.")
    if pub.email_state == "sending":
        raise PublishError("sending", "Στέλνονται ήδη email για αυτή τη δημοσίευση.")
    contacts = {t.id: (t.email or "").strip() for t in db.query(Teacher).all()}
    wanted = set(teacher_ids)
    messages = _messages(pub)
    queued = 0
    for m in messages:
        if m["teacher_id"] not in wanted:
            continue
        to = contacts.get(m["teacher_id"], "")
        m["email"] = {"to": to, "status": "pending"} if to else {"to": "", "status": "no_email"}
        queued += bool(to)
    if not queued:
        raise PublishError("no_recipients", "Κανένας από τους επιλεγμένους δεν έχει email.")
    pub.messages_json = json.dumps(messages, ensure_ascii=False)
    pub.email_state = "sending"
    db.flush()
    return pub


def send_test_email(db: Session, solution_id: int, teacher_id: int, to: str, sender) -> tuple[bool, str | None]:
    """Δοκιμαστικό: το email ενός καθηγητή, όπως θα έφευγε ΤΩΡΑ, σε άλλη διεύθυνση."""
    data = preview(db, solution_id)
    m = next((x for x in data["teachers"] if x["teacher_id"] == teacher_id), None)
    if m is None:
        raise LookupError("Ο καθηγητής δεν έχει ώρες σε αυτό το πρόγραμμα.")
    payload = email_payload(
        to=to, teacher=m["teacher"], title=data["solution"]["name"], note=None,
        changes=change_lines(m["changes"]), first=data["first"],
        entries=data["_entries"].get(teacher_id, []), ics=_ics_for(db, solution_id, teacher_id), test=True)
    return sender(payload)


def latest_before(db: Session, pub: SolutionPublication) -> SolutionPublication | None:
    return (db.query(SolutionPublication)
            .filter(SolutionPublication.term_id == pub.term_id, SolutionPublication.id < pub.id)
            .order_by(SolutionPublication.id.desc()).first())


def pending_telegram(db: Session) -> list[dict]:
    """Δημοσιεύσεις που περιμένουν το bot (παλαιότερες πρώτα). Όσο στέλνονται
    email περιμένουμε, ώστε η σύνοψη να λέει πόσα έφυγαν — εκτός αν «κόλλησε»."""
    stale = utcnow_naive() - timedelta(minutes=EMAIL_STALE_MINUTES)
    rows = (db.query(SolutionPublication)
            .filter(SolutionPublication.notify_telegram == True,  # noqa: E712
                    SolutionPublication.telegram_sent_at.is_(None),
                    or_(SolutionPublication.email_state.is_(None),
                        SolutionPublication.email_state != "sending",
                        SolutionPublication.published_at < stale))
            .order_by(SolutionPublication.id)
            .limit(_TELEGRAM_BATCH)
            .all())
    return [publication_detail(db, p.id) for p in rows]
