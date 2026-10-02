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
import re
from collections import Counter, defaultdict

from datetime import timedelta

from sqlalchemy import or_, text
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
    # 👥 Ονόματα μαθητών ανά κάρτα (αυτόματα) — ο καθηγητής βλέπει ΠΟΙΟΥΣ έχει.
    from backend.services import lesson_roster
    lessons = list({s.lesson for s in slots if s.lesson})
    roster_names = lesson_roster.display_names(db, lessons)
    roster_ids = lesson_roster.roster_map(db, lessons)   # για τη σύγκριση (όχι για προβολή)
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
            "color": (lesson.subject.color if lesson.subject else None) or "#3B82F6",
            "klass": klass,
            "students": roster_names.get(lesson.id, []),
            "room_short": room_shorts.get(s.classroom_id, "") if s.classroom_id else "",
            # Ταυτότητα τμήματος/μαθητών για το «τι άλλαξε» (όχι ονόματα: η
            # μετονομασία δεν είναι αλλαγή). Παλιά στιγμιότυπα δεν τα έχουν.
            "class_id": lesson.class_id,
            "student_ids": sorted(roster_ids.get(lesson.id, ())),
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

    Ταυτότητα ώρας = (θέση, μάθημα, τμήμα) — το τμήμα με το id του, ΟΧΙ το
    id ή το όνομα της κάρτας: έτσι ούτε η μετονομασία τμήματος ούτε μια κάρτα
    που σβήστηκε και ξαναφτιάχτηκε στις ίδιες ώρες βγάζουν ψεύτικο «➖
    καταργείται / ➕ νέα ώρα». Ό,τι μένει ζευγαρώνεται ανά (μάθημα, τμήμα) και
    γίνεται «μετακίνηση» — έτσι φαίνεται και η ανταλλαγή ωρών δύο τμημάτων.
    Ίδια ώρα με άλλους μαθητές → «👥» (ποιοι μπήκαν/βγήκαν).

    Παλιά στιγμιότυπα (πριν το class_id): ταυτότητα (θέση, μάθημα) και
    ζευγάρωμα ανά μάθημα, όπως πριν· οι μαθητές συγκρίνονται με τα ονόματα.
    """
    def by_teacher(entries):
        grouped: dict[int, list[dict]] = defaultdict(list)
        for e in entries:
            grouped[e["teacher_id"]].append(e)
        return grouped

    by_class = all("class_id" in e for e in previous) and all("class_id" in e for e in current)

    def key(e):
        base = (_position(e), _subject_of(e))
        return base + (e.get("class_id") or 0,) if by_class else base

    def group(k):                      # ζευγάρωμα μετακινήσεων
        return k[1:] if by_class else k[1]

    prev, cur = by_teacher(previous), by_teacher(current)
    out: dict[int, dict] = {}
    for tid in sorted(set(prev) | set(cur)):
        before = {key(e): e for e in prev.get(tid, [])}
        after = {key(e): e for e in cur.get(tid, [])}
        same = [(before[k], after[k]) for k in sorted(before.keys() & after.keys())]
        gone_keys = sorted(before.keys() - after.keys())
        new_keys = sorted(after.keys() - before.keys())
        gone_by_group: dict = defaultdict(list)
        for k in gone_keys:
            gone_by_group[group(k)].append(k)
        moved, new_left = [], []
        for k in new_keys:
            candidates = gone_by_group.get(group(k))
            if candidates:
                moved.append({"from": before[candidates.pop(0)], "to": after[k]})
            else:
                new_left.append(k)
        gone_left = [k for rest in gone_by_group.values() for k in rest]
        regrouped = []
        if by_class:
            # Ίδια ώρα & μάθημα, άλλο τμήμα (π.χ. ξαναφτιαγμένο τμήμα): όχι
            # «➖/➕» — μετρά μόνο αν άλλαξαν οι μαθητές (👥 παρακάτω).
            gone_at: dict = defaultdict(list)
            for k in gone_left:
                gone_at[k[:2]].append(k)
            still_new = []
            for k in new_left:
                if gone_at.get(k[:2]):
                    regrouped.append((before[gone_at[k[:2]].pop(0)], after[k]))
                else:
                    still_new.append(k)
            new_left = still_new
            gone_left = [k for rest in gone_at.values() for k in rest]
        roster_pairs = same + regrouped + ([(m["from"], m["to"]) for m in moved] if by_class else [])
        roster = _roster_changes(roster_pairs)
        added = [after[k] for k in new_left]
        removed = [before[k] for k in gone_left]
        if not (moved or added or removed or roster):
            continue
        out[tid] = {"moved": moved, "added": added,
                    "removed": sorted(removed, key=_entry_order), "roster": roster}
    return out


def _minus(items: list[str], other: list[str]) -> list[str]:
    """Όσα από το items δεν υπάρχουν στο other (με πολλαπλότητα, κρατά τη σειρά)."""
    left = Counter(other)
    out = []
    for x in items:
        if left[x]:
            left[x] -= 1
        else:
            out.append(x)
    return out


def _roster_changes(pairs: list[tuple[dict, dict]]) -> list[dict]:
    """👥 Ίδια ώρα (ή ίδιο τμήμα που μετακινήθηκε) με άλλους μαθητές.

    Μετρά μόνο ό,τι βλέπει ο καθηγητής: άλλαξαν τα ονόματα ΚΑΙ (όπου υπάρχουν
    ids) οι ίδιοι οι μαθητές — η μετονομασία μαθητή δεν είναι αλλαγή. Μία
    γραμμή ανά (μάθημα-τμήμα, ποιοι μπήκαν/βγήκαν), με τις ώρες όπου ισχύει."""
    groups: dict[tuple, dict] = {}
    for before, after in pairs:
        if "students" not in before or "students" not in after:
            continue                     # πολύ παλιό στιγμιότυπο: δεν ξέρουμε ποιοι ήταν
        old, new = before.get("students") or [], after.get("students") or []
        if Counter(old) == Counter(new):
            continue
        if ("student_ids" in before and "student_ids" in after
                and sorted(before["student_ids"]) == sorted(after["student_ids"])):
            continue
        joined, left = _minus(new, old), _minus(old, new)
        k = (after["label"], tuple(joined), tuple(left))
        g = groups.setdefault(k, {"label": after["label"], "subject": _subject_of(after),
                                  "joined": joined, "left": left, "entries": []})
        g["entries"].append(after)
    for g in groups.values():
        g["entries"].sort(key=_entry_order)
    return sorted(groups.values(), key=lambda g: _entry_order(g["entries"][0]))


def _roster_text(r: dict) -> str:
    parts = []
    if r["joined"]:
        parts.append("+ " + ", ".join(r["joined"]))
    if r["left"]:
        parts.append("− " + ", ".join(r["left"]))
    return "μαθητές: " + " · ".join(parts)


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
    lines += [f"• 👥 {r['label']}: {', '.join(_when(e) for e in r['entries'])} — {_roster_text(r)}"
              for r in changes.get("roster") or []]
    return lines


def _merged_blocks(entries: list[dict]) -> list[dict]:
    """Συνεχόμενες ώρες ίδιου μαθήματος/αίθουσας ΚΑΙ ίδιων μαθητών → ένα μπλοκ
    (16:00–18:00). Με άλλους μαθητές (άλλη κάρτα του τμήματος) μένουν χωριστά,
    αλλιώς το μπλοκ θα έδειχνε μόνο τους μαθητές της πρώτης ώρας."""
    blocks: list[dict] = []
    for e in sorted(entries, key=_entry_order):
        last = blocks[-1] if blocks else None
        if (last and last["day"] == e["day"] and last["label"] == e["label"]
                and last["room"] == e["room"] and last["end"] == e["start"]
                and last.get("students") == e.get("students")):
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
        lines.append(f"  {b['start']}–{b['end']} {_subject_of(b)}{_room(b)}")
        who = _klass_of(b)
        if who:
            lines.append(f"      {who}")
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
    """Το μάθημα χωρίς το τμήμα. Παλιά στιγμιότυπα (πριν τις 20/9) έχουν μόνο
    `label` τύπου «ΦΥΣΙΚΗ Β (ΤΜΗΜΑ)» — κόβουμε την παρένθεση ώστε να
    συγκρίνονται σωστά με τα νέα."""
    if e.get("subject"):
        return e["subject"]
    return re.sub(r"\s*\([^()]*\)\s*$", "", e.get("label", "")) or e.get("label", "")


def _klass_of(e: dict) -> str:
    """Ποιοι είναι μέσα: ονόματα μαθητών (αυτόματα)· αν λείπουν, το τμήμα."""
    return ", ".join(e.get("students") or []) or e.get("klass", "")


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
        parts += [f"• 👥 {esc(r['subject'])}: {', '.join(_short_when(e) for e in r['entries'])}"
                  f" — {esc(_roster_text(r))}" for r in changes.get("roster") or []]
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
    empty = {"moved": [], "added": [], "removed": [], "roster": []}
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


_LOCK_NAMESPACE = 0x45445350   # «EDSP»: δικός μας χώρος για τα advisory locks


def _lock_term(db: Session, term_id: int) -> None:
    """Σειριοποιεί «📢 Δημοσίευση» / «✉️ Αποστολή email» ανά σενάριο ως το
    commit της συναλλαγής: δύο αιτήματα που επικαλύπτονται (διπλό κλικ, δύο
    καρτέλες) δεν βγάζουν δύο δημοσιεύσεις ούτε διπλά email — το 2ο περιμένει
    και ξαναελέγχει (409 no_changes / sending). Postgres advisory xact lock·
    σε άλλη βάση (SQLite των tests) δεν κάνει τίποτα."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"),
                   {"ns": _LOCK_NAMESPACE, "key": int(term_id)})


def publish(db: Session, solution_id: int, note: str | None, notify_telegram: bool,
            email_teacher_ids: list[int] | None = None) -> SolutionPublication:
    """Καταγράφει τη δημοσίευση (χωρίς commit — το κάνει ο router). Τα email
    ΔΕΝ στέλνονται εδώ: σημειώνονται «pending» και τα στέλνει το send_emails."""
    sol = db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    if sol is not None and sol.term_id is not None:
        _lock_term(db, sol.term_id)   # ΠΡΙΝ διαβαστεί η τελευταία δημοσίευση
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

# Όρια του CRM (korifi-crm backend/routers/eds_mail.py) — πάνω από αυτά το
# email απορρίπτεται ολόκληρο με «CRM 422».
_CRM_KLASS_MAX = 200
_CRM_ROOM_MAX = 100
_CRM_CHANGES_MAX = 100
_CRM_CELL_NAMES = 3        # όσα ονόματα δείχνει ο πίνακας του email (CRM short_klass)


def _email_klass(e: dict) -> str:
    """Οι μαθητές της ώρας για το email, μέσα στο όριο του CRM. Μεγάλο τμήμα
    (~16+ μαθητές) → «Α Α., Β Β., Γ Γ. +17»: ίδια μορφή με τον πίνακα του
    email, ώστε και εκεί το «+N» να βγαίνει σωστό (ποτέ σιωπηλή αποκοπή)."""
    text_ = _klass_of(e)
    if len(text_) <= _CRM_KLASS_MAX:
        return text_
    names = e.get("students") or []
    for keep in range(min(_CRM_CELL_NAMES, len(names) - 1), 0, -1):
        short = ", ".join(names[:keep]) + f" +{len(names) - keep}"
        if len(short) <= _CRM_KLASS_MAX:
            return short
    return text_[:_CRM_KLASS_MAX - 1] + "…"


def _email_changes(changes: list[str]) -> list[str]:
    if len(changes) <= _CRM_CHANGES_MAX:
        return changes
    rest = len(changes) - (_CRM_CHANGES_MAX - 1)
    return changes[:_CRM_CHANGES_MAX - 1] + [f"…και άλλες {rest} αλλαγές — δες το πλήρες πρόγραμμα."]


def email_payload(*, to: str, teacher: str, title: str, note: str | None, changes: list[str],
                  first: bool, entries: list[dict], ics: str | None, test: bool = False) -> dict:
    """Ό,τι χρειάζεται το CRM για να φτιάξει το email + PDF (όχι HTML εδώ)."""
    def room(e):
        value = e["room"] or ""
        return value if len(value) <= _CRM_ROOM_MAX else value[:_CRM_ROOM_MAX - 1] + "…"

    return {
        "to": to, "teacher": teacher, "title": title, "note": note or "", "changes": _email_changes(changes),
        "first": first, "test": test, "ics": ics or "",
        "entries": [{"day": e["day"], "start": e["start"], "end": e["end"],
                     "subject": _subject_of(e), "klass": _email_klass(e), "room": room(e),
                     "color": e.get("color") or "#3B82F6"}
                    for e in sorted(entries, key=_entry_order)],
    }


def _ics_for(db: Session, term_id: int | None, teacher: str, teacher_id: int,
             entries: list[dict]) -> str | None:
    """Το .ics του email από τις ΙΔΙΕΣ ώρες με το σώμα του (στιγμιότυπο της
    δημοσίευσης / προεπισκόπηση) — όχι από το ζωντανό πρόγραμμα, που μπορεί
    να άλλαξε στο μεταξύ (τότε το email έλεγε άλλα στο σώμα κι άλλα στο .ics)."""
    from backend.routers.exports import render_ics
    try:
        events = [{"lesson_id": e.get("lesson_id"), "day": e["day"], "period_id": e.get("period_id"),
                   "start": e["start"], "end": e["end"], "subject": _subject_of(e),
                   "klass": e.get("klass") or "", "teacher": e.get("teacher") or teacher,
                   "room": e.get("room") or ""}
                  for e in entries]
        return render_ics(db, term_id, teacher, events, teacher_id=teacher_id)
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
        try:   # και η προετοιμασία μέσα: ένα σφάλμα χαλάει ΕΝΑ email, όχι όλη την αποστολή
            entries = [e for e in snapshot if e["teacher_id"] == m["teacher_id"]]
            payload = email_payload(
                to=mail["to"], teacher=m["teacher"], title=pub.solution_name, note=pub.note,
                changes=m.get("change_lines") or [], first=first, entries=entries,
                ics=_ics_for(db, pub.term_id, m["teacher"], m["teacher_id"], entries))
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
    _lock_term(db, pub.term_id)
    db.refresh(pub)   # ό,τι πρόλαβε να κάνει commit ένα παράλληλο αίτημα (π.χ. «sending»)
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
    entries = data["_entries"].get(teacher_id, [])
    term_id = (db.query(TimetableSolution.term_id)
               .filter(TimetableSolution.id == solution_id).scalar())
    payload = email_payload(
        to=to, teacher=m["teacher"], title=data["solution"]["name"], note=None,
        changes=change_lines(m["changes"]), first=data["first"], entries=entries,
        ics=_ics_for(db, term_id, m["teacher"], teacher_id, entries), test=True)
    return sender(payload)


EMAIL_INTERRUPTED = "Η αποστολή διακόπηκε (επανεκκίνηση του EduScheduler) — στείλε ξανά."
EMAIL_ABORTED = "Η αποστολή σταμάτησε από σφάλμα — στείλε ξανά."


def _abandon_pending(pub: SolutionPublication, reason: str) -> int:
    """«pending» → «failed» (με την αιτία) και τέλος το «sending», ώστε το
    «✉️ Αποστολή email» να μπορεί να τα ξαναστείλει. ΠΟΤΕ δεν στέλνει μόνο του."""
    try:
        messages = _messages(pub)
    except (TypeError, ValueError):
        pub.email_state = "done"   # χαλασμένο JSON: δεν το αγγίζουμε, απλώς ξεκολλάει
        return 0
    now = utcnow_naive().isoformat()
    abandoned = 0
    for m in messages:
        mail = m.get("email")
        if mail and mail.get("status") == "pending":
            mail.update({"status": "failed", "error": reason, "at": now})
            abandoned += 1
    if abandoned:
        pub.messages_json = json.dumps(messages, ensure_ascii=False)
    pub.email_state = "done"
    return abandoned


def abandon_emails(db: Session, publication_id: int, reason: str = EMAIL_ABORTED) -> int:
    """Η αποστολή μιας δημοσίευσης σταμάτησε από σφάλμα: ό,τι έμεινε «pending»
    γίνεται «failed». Με commit. Επιστρέφει πόσα email σημειώθηκαν."""
    pub = db.query(SolutionPublication).filter(SolutionPublication.id == publication_id).first()
    if pub is None or pub.email_state != "sending":
        return 0
    abandoned = _abandon_pending(pub, reason)
    db.commit()
    return abandoned


def recover_interrupted_emails(db: Session) -> int:
    """Κατά την εκκίνηση: όποια δημοσίευση είναι ακόμα «sending» είναι ορφανή
    (ένα μόνο process uvicorn — καμία αποστολή δεν τρέχει πριν σηκωθεί η
    εφαρμογή), π.χ. το deploy σκότωσε την αποστολή στη μέση. Τα email που
    δεν πρόλαβαν γίνονται «failed» για ξαναστείλιμο από τον χρήστη. Με commit.
    Επιστρέφει πόσες δημοσιεύσεις ξεκόλλησαν."""
    stuck = db.query(SolutionPublication).filter(SolutionPublication.email_state == "sending").all()
    for pub in stuck:
        _abandon_pending(pub, EMAIL_INTERRUPTED)
    if stuck:
        db.commit()
    return len(stuck)


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
