"""«📋 Έλεγχος δεδομένων» πριν από τη Δημιουργία Ωρολογίου.

Συμπληρώνει τον έλεγχο εφικτότητας (που βλέπει υπερφόρτωση καθηγητών/
αιθουσών): εδώ ελέγχεται αν τα ΔΕΔΟΜΕΝΑ είναι πλήρη — μαθητές που δεν θα
μπουν πουθενά, μαθήματα για κανέναν, σενάριο χωρίς ημερομηνίες. Read-only.

Κάθε έλεγχος: {key, level: 'warning'|'info', title, hint, count, names}.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.models import Lesson, SchoolClass, Student, StudentClassEnrollment, Term

MAX_NAMES = 15


def _student_name(s: Student) -> str:
    return f"{s.last_name or ''} {s.first_name or ''}".strip()


def _check(key, level, title, hint, names) -> dict:
    names = sorted(names)
    return {"key": key, "level": level, "title": title, "hint": hint,
            "count": len(names), "names": names[:MAX_NAMES]}


def readiness(db: Session, term_id: int) -> dict:
    term = db.query(Term).filter(Term.id == term_id).first()
    students = db.query(Student).all()
    classes = {c.id: c for c in db.query(SchoolClass).all()}
    enrolled: dict[int, set[int]] = {}
    for sid, cid in db.query(StudentClassEnrollment.student_id, StudentClassEnrollment.class_id).all():
        enrolled.setdefault(sid, set()).add(cid)
    class_sizes: dict[int, int] = {}
    for cids in enrolled.values():
        for cid in cids:
            class_sizes[cid] = class_sizes.get(cid, 0) + 1
    lesson_classes = {cid for (cid,) in db.query(Lesson.class_id).filter(Lesson.term_id == term_id).all()}

    checks = [
        _check("students_without_class", "warning", "Μαθητές χωρίς κανένα τμήμα",
               "Δεν θα μπουν στο πρόγραμμα. Βάλ' τους σε τμήμα από την καρτέλα Μαθητές (🏫).",
               [_student_name(s) for s in students if not enrolled.get(s.id)]),
        _check("empty_classes_with_lessons", "warning", "Τμήματα χωρίς μαθητές που έχουν μαθήματα",
               "Τα μαθήματά τους θα πιάνουν καθηγητή και αίθουσα για κανέναν. Πρόσθεσε μαθητές "
               "ή καθάρισέ τα (🧹 στην Παλέτα).",
               [classes[cid].name for cid in lesson_classes if cid in classes and not class_sizes.get(cid)]),
        _check("students_without_lessons", "warning", "Μαθητές σε τμήματα χωρίς μάθημα σε αυτό το σενάριο",
               "Είναι σε τμήμα, αλλά κανένα τμήμα τους δεν έχει μάθημα-κάρτα εδώ — δεν θα έχουν ώρες.",
               [_student_name(s) for s in students
                if enrolled.get(s.id) and not (enrolled[s.id] & lesson_classes)]),
        _check("students_without_grade", "info", "Μαθητές χωρίς τάξη",
               "Δεν επηρεάζει το πρόγραμμα· χρειάζεται για φίλτρα, εξαγωγές και συγχρονισμό με το CRM.",
               [_student_name(s) for s in students if not (s.grade or "").strip()]),
    ]
    if term is not None and not (term.start_date and term.end_date):
        checks.append({"key": "term_without_dates", "level": "info",
                       "title": f"Το σενάριο «{term.name}» δεν έχει ημερομηνίες",
                       "hint": "Χωρίς αυτές το ημερολόγιο (ICS) δεν ξέρει αργίες και λήξη. "
                               "Σενάρια → 📅 Ημερομηνίες.",
                       "count": 1, "names": []})
    checks = [c for c in checks if c["count"]]
    return {
        "term_id": term_id,
        "term_name": term.name if term else "",
        "ok": not any(c["level"] == "warning" for c in checks),
        "checks": checks,
    }
