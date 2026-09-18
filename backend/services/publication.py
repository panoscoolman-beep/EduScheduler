"""📢 Δημοσίευση προγράμματος — «τι άλλαξε για σένα» ανά καθηγητή.

Η δημοσίευση κρατά αυτοτελές στιγμιότυπο (snapshot) των τοποθετημένων ωρών.
Η επόμενη δημοσίευση του ίδιου σεναρίου συγκρίνεται με την προηγούμενη και
βγάζει για κάθε καθηγητή τις αλλαγές του και το πλήρες νέο πρόγραμμά του,
σε απλό κείμενο έτοιμο για προώθηση (Telegram/email/αντιγραφή).

Τίποτα εδώ δεν στέλνει μηνύματα: το bot του CRM παραλαμβάνει τα μηνύματα
και τα στέλνει ΜΟΝΟ στον ιδιοκτήτη, που τα προωθεί.
"""
from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy.orm import Session, joinedload

from backend.models import (
    Classroom, Lesson, Period, SolutionPublication, Teacher, TimetableSlot, TimetableSolution,
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
    if changes is not None:
        parts += ["🔄 Τι άλλαξε για σένα:", *_change_lines(changes), ""]
    if entries:
        parts += [f"🗓 Το πρόγραμμά σου ({len(entries)} ώρες/εβδομάδα):", *schedule_lines(entries)]
    else:
        parts.append("🗓 Δεν έχεις πλέον ώρες σε αυτό το πρόγραμμα.")
    return "\n".join(parts).strip()


def build_messages(previous: list[dict] | None, current: list[dict]) -> list[dict]:
    """Ένα μήνυμα ανά επηρεαζόμενο καθηγητή (όλοι, αν είναι η πρώτη δημοσίευση)."""
    by_teacher: dict[int, list[dict]] = defaultdict(list)
    names: dict[int, str] = {}
    for e in (previous or []) + current:
        names.setdefault(e["teacher_id"], e["teacher"])
    for e in current:
        by_teacher[e["teacher_id"]].append(e)
        names[e["teacher_id"]] = e["teacher"]

    if previous is None:
        affected = {tid: None for tid in by_teacher}
    else:
        affected = teacher_changes(previous, current)
    out = []
    for tid, changes in affected.items():
        entries = by_teacher.get(tid, [])
        out.append({
            "teacher_id": tid,
            "teacher": names.get(tid, "—"),
            "hours": len(entries),
            "changes": changes,
            "message": teacher_message(names.get(tid, "—"), entries, changes),
        })
    return sorted(out, key=lambda m: m["teacher"])


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

def latest_publication(db: Session, term_id: int) -> SolutionPublication | None:
    return (db.query(SolutionPublication)
            .filter(SolutionPublication.term_id == term_id)
            .order_by(SolutionPublication.published_at.desc(), SolutionPublication.id.desc())
            .first())


def publication_summary(pub: SolutionPublication | None) -> dict | None:
    if pub is None:
        return None
    return {
        "id": pub.id,
        "solution_id": pub.solution_id,
        "solution_name": pub.solution_name,
        "published_at": pub.published_at.isoformat() if pub.published_at else None,
        "note": pub.note,
        "teachers_notified": len(json.loads(pub.messages_json or "[]")),
        "notify_telegram": pub.notify_telegram,
        "telegram_sent_at": pub.telegram_sent_at.isoformat() if pub.telegram_sent_at else None,
    }


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
    for m in messages:
        t = contacts.get(m["teacher_id"])
        m["email"] = (t.email or "") if t else ""
        m["phone"] = (t.phone or "") if t else ""
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
        "teachers": messages,
        "_snapshot": current,
    }


def publish(db: Session, solution_id: int, note: str | None, notify_telegram: bool) -> SolutionPublication:
    """Καταγράφει τη δημοσίευση (χωρίς commit — το κάνει ο router)."""
    data = preview(db, solution_id)
    if not data["placed"]:
        raise PublishError("empty", "Το πρόγραμμα δεν έχει καμία τοποθετημένη ώρα.")
    if not data["first"] and not data["teachers"]:
        raise PublishError("no_changes", "Δεν άλλαξε τίποτα από την τελευταία δημοσίευση.")
    sol = db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    pub = SolutionPublication(
        term_id=sol.term_id,
        solution_id=sol.id,
        solution_name=sol.name,
        note=(note or "").strip() or None,
        snapshot_json=json.dumps(data["_snapshot"], ensure_ascii=False),
        messages_json=json.dumps(
            [{"teacher_id": m["teacher_id"], "teacher": m["teacher"], "message": m["message"]}
             for m in data["teachers"]], ensure_ascii=False),
        notify_telegram=bool(notify_telegram),
    )
    db.add(pub)
    db.flush()
    return pub


def pending_telegram(db: Session) -> list[dict]:
    """Δημοσιεύσεις που περιμένουν να τις στείλει το bot (παλαιότερες πρώτα)."""
    rows = (db.query(SolutionPublication)
            .filter(SolutionPublication.notify_telegram == True,  # noqa: E712
                    SolutionPublication.telegram_sent_at.is_(None))
            .order_by(SolutionPublication.id)
            .limit(_TELEGRAM_BATCH)
            .all())
    return [{**publication_summary(p), "messages": json.loads(p.messages_json or "[]")} for p in rows]
