"""Ονομαστική αναφορά soft-constraint παραβιάσεων μιας λύσης.

Το solution_metrics δίνει aggregates (πόσα κενά συνολικά)· εδώ απαντάμε
ΠΟΙΟΣ/ΠΟΤΕ/ΠΟΥ: «ο Νικολάου έχει κενό τη 2η ώρα της Δευτέρας», «η Φυσική
του Γ1 πέφτει 7η ώρα Τρίτη» — ώστε το tuning των βαρών στους Περιορισμούς
να γίνεται με στόχο, όχι στα τυφλά. Pure read — no writes.

Οι ώρες συγκρίνονται με βάση Period.sort_order (ΟΧΙ τα ids) και «αργή»
ώρα = δείκτης > LATE_THRESHOLD_INDEX στα sort_order-ταξινομημένα teaching
periods. ΠΡΟΣΟΧΗ: το solution_metrics (καρτέλα «Σύγκριση») χρησιμοποιεί
ΠΡΟΣΕΓΓΙΣΤΙΚΟΥΣ υπολογισμούς (raw period_ids / διάμεσο) — τα νούμερά του
μπορεί να διαφέρουν από εδώ· αυτή η αναφορά είναι η πιο ακριβής των δύο.
TODO: ευθυγράμμιση του solution_metrics με αυτούς τους helpers.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import pstdev

from sqlalchemy.orm import Session, joinedload

from backend.models import Lesson, Period, TimetableSlot, TimetableSolution
from backend.services.solution_metrics import SolutionMetrics

_GREEK_DAYS = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]


def compute_violations(db: Session, solution_id: int) -> dict | None:
    """Named soft-violations report. None αν δεν υπάρχει η λύση."""
    sol = db.query(TimetableSolution).filter(TimetableSolution.id == solution_id).first()
    if not sol:
        return None

    slots = (
        db.query(TimetableSlot)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .options(
            joinedload(TimetableSlot.lesson).joinedload(Lesson.teacher),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.subject),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.school_class),
        )
        .all()
    )

    teaching = (
        db.query(Period)
        .filter(Period.is_break == False)  # noqa: E712
        .order_by(Period.sort_order)
        .all()
    )
    order_index = {p.id: i for i, p in enumerate(teaching)}   # sort_order → 0-based δείκτης
    period_by_id = {p.id: p for p in teaching}

    def _day_name(d: int) -> str:
        return _GREEK_DAYS[d] if 0 <= d < len(_GREEK_DAYS) else str(d)

    # ── Κενά καθηγητών: ανά (καθηγητής, μέρα), τρύπες ανάμεσα σε κατειλημμένους δείκτες
    by_teacher_day: dict[tuple[str, int], set[int]] = defaultdict(set)
    for s in slots:
        if s.lesson and s.lesson.teacher and s.day_of_week is not None:
            idx = order_index.get(s.period_id)
            if idx is not None:
                by_teacher_day[(s.lesson.teacher.name, s.day_of_week)].add(idx)

    teacher_gaps: list[dict] = []
    gap_total = 0
    for (teacher, day), indices in sorted(by_teacher_day.items()):
        lo, hi = min(indices), max(indices)
        holes = [i for i in range(lo + 1, hi) if i not in indices]
        if not holes:
            continue
        gap_total += len(holes)
        teacher_gaps.append({
            "teacher": teacher,
            "day": day,
            "day_name": _day_name(day),
            "gap_periods": [teaching[i].name for i in holes],
        })

    # ── Αργές ώρες: δείκτης > LATE_THRESHOLD_INDEX (ίδιο με solution_metrics)
    late_threshold = SolutionMetrics.LATE_THRESHOLD_INDEX
    late_slots: list[dict] = []
    for s in slots:
        idx = order_index.get(s.period_id)
        if idx is None or idx <= late_threshold or s.day_of_week is None:
            continue
        lesson = s.lesson
        late_slots.append({
            "day": s.day_of_week,
            "day_name": _day_name(s.day_of_week),
            "period_name": period_by_id[s.period_id].name,
            "time": f"{period_by_id[s.period_id].start_time}–{period_by_id[s.period_id].end_time}",
            "subject": lesson.subject.name if lesson and lesson.subject else "—",
            "class_name": lesson.school_class.name if lesson and lesson.school_class else "—",
            "teacher": lesson.teacher.name if lesson and lesson.teacher else "—",
        })
    late_slots.sort(key=lambda x: (x["day"], x["period_name"]))

    # ── Φόρτος ανά καθηγητή (ώρες) + τυπική απόκλιση (δικαιοσύνη κατανομής)
    hours: dict[str, int] = defaultdict(int)
    for s in slots:
        if s.lesson and s.lesson.teacher:
            hours[s.lesson.teacher.name] += 1
    workload = [
        {"teacher": t, "hours": h}
        for t, h in sorted(hours.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    stddev = round(pstdev(hours.values()), 2) if len(hours) > 1 else 0.0

    return {
        "solution": {"id": sol.id, "name": sol.name, "score": sol.score},
        "teacher_gaps": teacher_gaps,
        "late_slots": late_slots,
        "workload": workload,
        "summary": {
            "gap_total": gap_total,
            "late_total": len(late_slots),
            "workload_stddev": stddev,
        },
    }
