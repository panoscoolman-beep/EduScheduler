"""Slot-level diff δύο λύσεων — «τι άλλαξε μετά το regenerate;»

Το solution_metrics.compare απαντά «ποια λύση είναι καλύτερη» με aggregates·
αυτό εδώ απαντά το λειτουργικό ερώτημα του regenerate-μέσα-στη-χρονιά:
ποια μαθήματα μετακινήθηκαν (από πού → πού), τι προστέθηκε/αφαιρέθηκε,
και πώς άλλαξε ο φόρτος κάθε καθηγητή. Pure read — no writes.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session, joinedload

from backend.models import Lesson, Period, TimetableSlot, TimetableSolution

_GREEK_DAYS = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]

# Θέση slot: (day_of_week, period_id, classroom_id) — αλλαγή αίθουσας
# μετράει ως μετακίνηση (ο καθηγητής/μαθητές πάνε αλλού).
_Position = tuple[int, int, int | None]


def _positions_by_lesson(db: Session, solution_id: int) -> dict[int, list[_Position]]:
    slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .all()
    )
    out: dict[int, list[_Position]] = defaultdict(list)
    for s in slots:
        if s.day_of_week is None or s.period_id is None:
            continue
        out[s.lesson_id].append((s.day_of_week, s.period_id, s.classroom_id))
    return out


def _lesson_labels(db: Session, lesson_ids: set[int]) -> dict[int, dict]:
    rows = (
        db.query(Lesson)
        .options(
            joinedload(Lesson.subject),
            joinedload(Lesson.school_class),
            joinedload(Lesson.teacher),
        )
        .filter(Lesson.id.in_(lesson_ids))
        .all()
    ) if lesson_ids else []
    out = {}
    for l in rows:
        subject = l.subject.name if l.subject else "Μάθημα"
        klass = l.school_class.name if l.school_class else ""
        out[l.id] = {
            "label": f"{subject} ({klass})" if klass else subject,
            "teacher": l.teacher.name if l.teacher else "—",
        }
    return out


def _describe(pos: _Position, periods: dict[int, Period], rooms: dict[int, str]) -> dict:
    day, period_id, room_id = pos
    p = periods.get(period_id)
    return {
        "day": day,
        "day_name": _GREEK_DAYS[day] if 0 <= day < len(_GREEK_DAYS) else str(day),
        "period_id": period_id,
        "period_name": p.name if p else str(period_id),
        "time": f"{p.start_time}–{p.end_time}" if p else "",
        "room": rooms.get(room_id, "") if room_id is not None else "",
    }


def compute_diff(db: Session, base_id: int, other_id: int) -> dict | None:
    """Diff base→other. None αν λείπει κάποια από τις δύο λύσεις."""
    base_sol = db.query(TimetableSolution).filter(TimetableSolution.id == base_id).first()
    other_sol = db.query(TimetableSolution).filter(TimetableSolution.id == other_id).first()
    if not base_sol or not other_sol:
        return None

    base_pos = _positions_by_lesson(db, base_id)
    other_pos = _positions_by_lesson(db, other_id)
    lesson_ids = set(base_pos) | set(other_pos)
    labels = _lesson_labels(db, lesson_ids)
    periods = {p.id: p for p in db.query(Period).all()}
    from backend.models import Classroom

    rooms = {r.id: r.name for r in db.query(Classroom).all()}

    moved: list[dict] = []
    added: list[dict] = []
    removed: list[dict] = []
    unchanged = 0

    for lid in sorted(lesson_ids):
        info = labels.get(lid, {"label": f"lesson {lid}", "teacher": "—"})
        b = sorted(base_pos.get(lid, []))
        o = sorted(other_pos.get(lid, []))
        b_set, o_set = set(b), set(o)
        unchanged += len(b_set & o_set)
        gone = sorted(b_set - o_set)   # θέσεις που χάθηκαν από τη base
        new = sorted(o_set - b_set)    # θέσεις που εμφανίστηκαν στην other
        # Ζευγάρωμα gone↔new = «μετακίνηση»· ό,τι περισσέψει = added/removed.
        for from_p, to_p in zip(gone, new):
            moved.append({
                "lesson": info["label"],
                "teacher": info["teacher"],
                "from": _describe(from_p, periods, rooms),
                "to": _describe(to_p, periods, rooms),
            })
        for extra in gone[len(new):]:
            removed.append({
                "lesson": info["label"],
                "teacher": info["teacher"],
                "at": _describe(extra, periods, rooms),
            })
        for extra in new[len(gone):]:
            added.append({
                "lesson": info["label"],
                "teacher": info["teacher"],
                "at": _describe(extra, periods, rooms),
            })

    # Φόρτος ανά καθηγητή (τοποθετημένες ώρες) και στις δύο λύσεις.
    def _hours_by_teacher(pos_by_lesson: dict[int, list[_Position]]) -> dict[str, int]:
        hours: dict[str, int] = defaultdict(int)
        for lid, positions in pos_by_lesson.items():
            teacher = labels.get(lid, {}).get("teacher", "—")
            hours[teacher] += len(positions)
        return hours

    base_hours = _hours_by_teacher(base_pos)
    other_hours = _hours_by_teacher(other_pos)
    teacher_load = [
        {
            "teacher": t,
            "base_hours": base_hours.get(t, 0),
            "other_hours": other_hours.get(t, 0),
            "delta": other_hours.get(t, 0) - base_hours.get(t, 0),
        }
        for t in sorted(set(base_hours) | set(other_hours))
    ]

    return {
        "base": {"id": base_sol.id, "name": base_sol.name},
        "other": {"id": other_sol.id, "name": other_sol.name},
        "moved": moved,
        "added": added,
        "removed": removed,
        "unchanged_count": unchanged,
        "teacher_load": teacher_load,
    }
