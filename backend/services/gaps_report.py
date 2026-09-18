"""🕳 Κενά & ώρες ανά μαθητή/καθηγητή — με προτάσεις διόρθωσης.

«Κενό» = ελεύθερη διδακτική ώρα ανάμεσα στο πρώτο και το τελευταίο μάθημα
μιας μέρας (τα διαλείμματα δεν μετράνε). Τα κενά μετρώνται στη σειρά των
διδακτικών ωρών (Period.sort_order), όπως στο violations_report.

Πρόταση διόρθωσης = μετακίνηση ΜΙΑΣ μη κλειδωμένης ώρας σε ένα κενό, που
μειώνει τα ΣΥΝΟΛΙΚΑ κενά όλων όσων επηρεάζει (καθηγητής + μαθητές του
τμήματος) και περνά τους ίδιους ελέγχους με το drag & drop
(build_placement_map). Pure read — η εφαρμογή γίνεται από το κανονικό PUT
του slot, άρα γράφεται στο ιστορικό και αναιρείται.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, joinedload

from backend.models import (
    Lesson, Period, Student, StudentClassEnrollment, Teacher, TimetableSlot,
)
from backend.services import placement_conflicts as pc
from backend.services.slot_placement import build_placement_map

_DAYS = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
KINDS = ("student", "teacher")

Cell = tuple[int, int]   # (μέρα, δείκτης διδακτικής ώρας)


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------

def day_holes(indices) -> list[int]:
    """Δείκτες-κενά ανάμεσα στην πρώτη και την τελευταία ώρα μιας μέρας."""
    idx = set(indices)
    if len(idx) < 2:
        return []
    return [i for i in range(min(idx), max(idx)) if i not in idx]


def gap_count(cells) -> int:
    by_day: dict[int, set[int]] = defaultdict(set)
    for day, i in cells:
        by_day[day].add(i)
    return sum(len(day_holes(v)) for v in by_day.values())


def hole_runs(holes: list[int]) -> list[list[int]]:
    """[3, 4, 7] → [[3, 4], [7]] — συνεχόμενα κενά ως ένα διάστημα."""
    runs: list[list[int]] = []
    for i in sorted(holes):
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def move_delta(people_cells: dict, src: Cell, dst: Cell) -> dict:
    """Μεταβολή κενών ανά άτομο αν μια ώρα πάει src → dst (αρνητικό = καλύτερα)."""
    out = {}
    for person, cells in people_cells.items():
        after = (set(cells) - {src}) | {dst}
        out[person] = gap_count(after) - gap_count(cells)
    return out


# ---------------------------------------------------------------------------
# Φόρτωση
# ---------------------------------------------------------------------------

@dataclass
class _Placed:
    slot_id: int
    lesson_id: int
    teacher_id: int
    class_id: int
    label: str
    day: int
    period_id: int
    locked: bool


@dataclass
class _Context:
    periods: list[Period]
    index: dict[int, int]                      # period_id → δείκτης
    placed: list[_Placed]
    class_students: dict[int, set[int]]
    cells: dict[tuple[str, int], set[Cell]] = field(default_factory=dict)
    slots_of: dict[tuple[str, int], list[_Placed]] = field(default_factory=dict)

    def people_of(self, p: _Placed) -> list[tuple[str, int]]:
        return [("teacher", p.teacher_id)] + [("student", s) for s in self.class_students.get(p.class_id, ())]


def _load(db: Session, solution_id: int) -> _Context:
    periods = (db.query(Period).filter(Period.is_break == False)  # noqa: E712
               .order_by(Period.sort_order).all())
    index = {p.id: i for i, p in enumerate(periods)}
    slots = (db.query(TimetableSlot)
             .options(joinedload(TimetableSlot.lesson).joinedload(Lesson.subject),
                      joinedload(TimetableSlot.lesson).joinedload(Lesson.school_class))
             .filter(TimetableSlot.solution_id == solution_id,
                     TimetableSlot.is_unplaced == False)  # noqa: E712
             .all())
    placed = []
    for s in slots:
        l = s.lesson
        if l is None or s.day_of_week is None or s.period_id not in index:
            continue
        subject = l.subject.name if l.subject else "Μάθημα"
        klass = l.school_class.name if l.school_class else ""
        placed.append(_Placed(s.id, l.id, l.teacher_id, l.class_id,
                              f"{subject} ({klass})" if klass else subject,
                              s.day_of_week, s.period_id, bool(s.is_locked)))
    class_ids = {p.class_id for p in placed}
    class_students: dict[int, set[int]] = defaultdict(set)
    if class_ids:
        for cid, sid in (db.query(StudentClassEnrollment.class_id, StudentClassEnrollment.student_id)
                         .filter(StudentClassEnrollment.class_id.in_(class_ids)).all()):
            class_students[cid].add(sid)
    ctx = _Context(periods, index, placed, class_students)
    for p in placed:
        cell = (p.day, index[p.period_id])
        for person in ctx.people_of(p):
            ctx.cells.setdefault(person, set()).add(cell)
            ctx.slots_of.setdefault(person, []).append(p)
    return ctx


def _names(db: Session) -> dict[tuple[str, int], str]:
    names = {("teacher", t.id): t.name for t in db.query(Teacher).all()}
    names.update({("student", s.id): pc.student_display(s) for s in db.query(Student).all()})
    return names


def _cell_text(ctx: _Context, day: int, idx: int) -> str:
    p = ctx.periods[idx]
    return f"{_DAYS[day] if 0 <= day < 7 else day} {p.start_time}"


# ---------------------------------------------------------------------------
# Αναφορά
# ---------------------------------------------------------------------------

def gaps_report(db: Session, solution_id: int) -> dict:
    ctx = _load(db, solution_id)
    names = _names(db)
    grades = {s.id: s.grade or "" for s in db.query(Student.id, Student.grade).all()}
    rows = {k: [] for k in KINDS}
    for (kind, pid), cells in ctx.cells.items():
        by_day: dict[int, set[int]] = defaultdict(set)
        for day, i in cells:
            by_day[day].add(i)
        gaps = []
        for day in sorted(by_day):
            for run in hole_runs(day_holes(by_day[day])):
                first, last = ctx.periods[run[0]], ctx.periods[run[-1]]
                gaps.append({"day": day, "day_name": _DAYS[day] if 0 <= day < 7 else str(day),
                             "from": first.start_time, "to": last.end_time, "hours": len(run)})
        rows[kind].append({
            "id": pid,
            "name": names.get((kind, pid), "—"),
            "grade": grades.get(pid, "") if kind == "student" else "",
            "weekly_hours": len(cells),
            "days": len(by_day),
            "gap_total": sum(g["hours"] for g in gaps),
            "gaps": gaps,
        })
    for kind in KINDS:
        rows[kind].sort(key=lambda r: (-r["gap_total"], r["name"]))
    return {
        "students": rows["student"],
        "teachers": rows["teacher"],
        "totals": {f"{k}_gaps": sum(r["gap_total"] for r in rows[k]) for k in KINDS},
    }


# ---------------------------------------------------------------------------
# Προτάσεις
# ---------------------------------------------------------------------------

def suggestions(db: Session, solution_id: int, kind: str, person_id: int, day: int,
                limit: int = 3) -> list[dict]:
    """Μετακινήσεις μίας ώρας που κλείνουν κενό του ατόμου τη μέρα `day`,
    με καθαρή μείωση κενών για όλους τους επηρεαζόμενους."""
    ctx = _load(db, solution_id)
    person = (kind, person_id)
    mine = ctx.cells.get(person, set())
    holes = day_holes(i for d, i in mine if d == day)
    if not holes:
        return []
    names = _names(db)
    maps: dict[int, dict] = {}
    found = []
    for p in ctx.slots_of.get(person, []):
        if p.locked:
            continue
        src = (p.day, ctx.index[p.period_id])
        affected = {who: ctx.cells.get(who, set()) for who in ctx.people_of(p)}
        for hole in holes:
            dst = (day, hole)
            delta = move_delta(affected, src, dst)
            total = sum(delta.values())
            if total >= 0:
                continue
            if p.slot_id not in maps:
                slot = db.query(TimetableSlot).filter(TimetableSlot.id == p.slot_id).first()
                maps[p.slot_id] = {(c["day"], c["period_id"]): c for c in build_placement_map(db, slot)["cells"]}
            cell = maps[p.slot_id].get((day, ctx.periods[hole].id))
            if not cell or not cell["ok"]:
                continue
            changed = sorted(((names.get(w, "—"), d) for w, d in delta.items() if d), key=lambda x: (x[1], x[0]))
            found.append({
                "slot_id": p.slot_id,
                "lesson": p.label,
                "from": _cell_text(ctx, *src),
                "to": _cell_text(ctx, *dst),
                "day_of_week": day,
                "period_id": ctx.periods[hole].id,
                "gap_delta": total,
                "same_day": p.day == day,
                "effects": [{"name": n, "delta": d} for n, d in changed],
            })
    found.sort(key=lambda s: (s["gap_delta"], not s["same_day"], s["lesson"]))
    return found[:limit]
