"""Timetable exports: iCalendar (.ics) feeds and print-friendly HTML.

Endpoints (mounted under /api/exports):
    GET /ics?solution_id=&teacher_id=|student_id=   → .ics download
    GET /print?solution_id=&teacher_id=|student_id= → printable HTML grid

Both filter a solution's slots down to one teacher's or one student's
lessons. The frontend fetches them with the normal auth flow and hands
the result to the browser (download / print dialog).
"""

from __future__ import annotations

import datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import (
    Lesson,
    Period,
    Student,
    StudentClassEnrollment,
    Teacher,
    TimetableSlot,
    TimetableSolution,
)

router = APIRouter()

_GREEK_DAYS = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]


# ---------------------------------------------------------------------------
# Shared loading / filtering
# ---------------------------------------------------------------------------

def _load_filtered_slots(
    db: Session,
    solution_id: int,
    teacher_id: int | None,
    student_id: int | None,
) -> tuple[TimetableSolution, list[TimetableSlot], str]:
    """Return (solution, placed slots for the filter, filter label)."""
    if (teacher_id is None) == (student_id is None):
        raise HTTPException(
            status_code=400,
            detail="Δώσε ακριβώς ένα από teacher_id ή student_id",
        )

    solution = (
        db.query(TimetableSolution)
        .filter(TimetableSolution.id == solution_id)
        .first()
    )
    if not solution:
        raise HTTPException(status_code=404, detail="Η λύση δεν βρέθηκε")

    query = (
        db.query(TimetableSlot)
        .join(Lesson, TimetableSlot.lesson_id == Lesson.id)
        .filter(
            TimetableSlot.solution_id == solution_id,
            TimetableSlot.is_unplaced == False,  # noqa: E712
        )
        .options(
            joinedload(TimetableSlot.lesson).joinedload(Lesson.subject),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.teacher),
            joinedload(TimetableSlot.lesson).joinedload(Lesson.school_class),
            joinedload(TimetableSlot.classroom),
        )
    )

    if teacher_id is not None:
        teacher = db.query(Teacher).filter(Teacher.id == teacher_id).first()
        if not teacher:
            raise HTTPException(status_code=404, detail="Ο καθηγητής δεν βρέθηκε")
        label = teacher.name
        slots = query.filter(Lesson.teacher_id == teacher_id).all()
    else:
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            raise HTTPException(status_code=404, detail="Ο μαθητής δεν βρέθηκε")
        label = f"{student.first_name} {student.last_name}"
        class_ids = [
            e.class_id
            for e in db.query(StudentClassEnrollment)
            .filter(StudentClassEnrollment.student_id == student_id)
            .all()
        ]
        slots = query.filter(Lesson.class_id.in_(class_ids)).all() if class_ids else []

    return solution, slots, label


def _periods_by_id(db: Session) -> dict[int, Period]:
    return {p.id: p for p in db.query(Period).all()}


# ---------------------------------------------------------------------------
# ICS export
# ---------------------------------------------------------------------------

def _next_weekday(base: datetime.date, weekday: int) -> datetime.date:
    """Next date (incl. today) that falls on the given weekday (Mon=0)."""
    return base + datetime.timedelta(days=(weekday - base.weekday()) % 7)


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


@router.get("/ics")
def export_ics(
    solution_id: int,
    teacher_id: int | None = None,
    student_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Weekly-recurring iCalendar feed for one teacher's or student's
    timetable. Import the file into Google Calendar / Outlook / Apple
    Calendar — each lesson becomes a weekly repeating event."""
    _, slots, label = _load_filtered_slots(db, solution_id, teacher_id, student_id)
    periods = _periods_by_id(db)
    today = datetime.date.today()
    stamp = "20260101T000000Z"  # static DTSTAMP: feed is deterministic per solution

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//EduScheduler//Timetable//EL",
        f"X-WR-CALNAME:Πρόγραμμα {_ics_escape(label)}",
        "X-WR-TIMEZONE:Europe/Athens",
    ]

    for slot in slots:
        period = periods.get(slot.period_id)
        if not period or slot.day_of_week is None:
            continue
        start_date = _next_weekday(today, slot.day_of_week)
        start_hm = period.start_time.replace(":", "") + "00"
        end_hm = period.end_time.replace(":", "") + "00"
        lesson = slot.lesson
        subject = lesson.subject.name if lesson.subject else "Μάθημα"
        klass = lesson.school_class.name if lesson.school_class else ""
        teacher = lesson.teacher.name if lesson.teacher else ""
        room = slot.classroom.name if slot.classroom else ""

        summary = subject if teacher_id is not None else f"{subject} ({teacher})"
        description = " · ".join(x for x in [klass, teacher, room] if x)

        lines += [
            "BEGIN:VEVENT",
            f"UID:eduscheduler-slot-{slot.id}@korifi",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID=Europe/Athens:{start_date.strftime('%Y%m%d')}T{start_hm}",
            f"DTEND;TZID=Europe/Athens:{start_date.strftime('%Y%m%d')}T{end_hm}",
            "RRULE:FREQ=WEEKLY",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:{_ics_escape(description)}",
            f"LOCATION:{_ics_escape(room)}",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    body = "\r\n".join(lines) + "\r\n"
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="timetable_{teacher_id or student_id}.ics"'
            )
        },
    )


# ---------------------------------------------------------------------------
# Print-friendly HTML
# ---------------------------------------------------------------------------

@router.get("/print", response_class=HTMLResponse)
def export_print(
    solution_id: int,
    teacher_id: int | None = None,
    student_id: int | None = None,
    db: Session = Depends(get_db),
):
    """A5-style printable weekly grid. The frontend opens this in a new
    window and triggers the browser's print dialog (→ paper or PDF)."""
    solution, slots, label = _load_filtered_slots(db, solution_id, teacher_id, student_id)
    periods = sorted(_periods_by_id(db).values(), key=lambda p: p.sort_order)
    teaching_periods = [p for p in periods if not p.is_break]
    days = list(range(5))  # Δευτέρα–Παρασκευή

    grid: dict[tuple[int, int], list[str]] = {}
    for slot in slots:
        if slot.day_of_week is None:
            continue
        lesson = slot.lesson
        subject = lesson.subject.short_name or lesson.subject.name if lesson.subject else "—"
        detail = (
            (lesson.school_class.short_name or lesson.school_class.name)
            if teacher_id is not None and lesson.school_class
            else (lesson.teacher.short_name or lesson.teacher.name) if lesson.teacher else ""
        )
        room = slot.classroom.name if slot.classroom else ""
        cell = f"<b>{escape(subject)}</b>"
        if detail:
            cell += f"<br><small>{escape(detail)}</small>"
        if room:
            cell += f"<br><small>🏫 {escape(room)}</small>"
        grid.setdefault((slot.day_of_week, slot.period_id), []).append(cell)

    header_cells = "".join(f"<th>{d}</th>" for d in _GREEK_DAYS[:5])
    rows_html = []
    for p in teaching_periods:
        cells = "".join(
            f"<td>{'<hr>'.join(grid.get((d, p.id), [])) or ''}</td>" for d in days
        )
        rows_html.append(
            f"<tr><th class='time'>{escape(p.start_time)}–{escape(p.end_time)}</th>{cells}</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="utf-8">
<title>Πρόγραμμα — {escape(label)}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 24px; color: #1a1a2e; }}
  h1 {{ font-size: 20px; margin-bottom: 2px; }}
  .sub {{ color: #666; font-size: 12px; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #999; padding: 6px 8px; text-align: center;
            font-size: 12px; vertical-align: top; }}
  thead th {{ background: #003366; color: white; }}
  th.time {{ background: #eef2f7; white-space: nowrap; }}
  td hr {{ border: none; border-top: 1px dashed #bbb; margin: 4px 0; }}
  @media print {{
    body {{ margin: 8mm; }}
    .noprint {{ display: none; }}
  }}
</style>
</head>
<body>
<h1>📅 Εβδομαδιαίο Πρόγραμμα — {escape(label)}</h1>
<div class="sub">Λύση: {escape(solution.name or str(solution.id))} ·
Εκτυπώθηκε {datetime.date.today().strftime('%d/%m/%Y')} · Φροντιστήριο ΚΟΡΥΦΗ</div>
<table>
  <thead><tr><th class="time">Ώρα</th>{header_cells}</tr></thead>
  <tbody>{''.join(rows_html)}</tbody>
</table>
<p class="noprint" style="margin-top:16px">
  <button onclick="window.print()" style="padding:8px 16px">🖨️ Εκτύπωση / Αποθήκευση PDF</button>
</p>
</body>
</html>"""
    return HTMLResponse(content=html)
