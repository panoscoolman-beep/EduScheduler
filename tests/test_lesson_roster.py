"""👥 Μαθητές ανά κάρτα: «το ένα δίωρο Φυσικής το κάνει σε άλλο τμήμα».

Χωρίς εξαιρέσεις η συμπεριφορά μένει ίδια με τις εγγραφές τμημάτων· με
εξαιρέσεις, ΟΛΑ (solver, σύρσιμο, κενά, εκτυπώσεις) βλέπουν την αλήθεια.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database import Base, get_db
from backend.models import (
    Classroom, Lesson, LessonStudentOverride, Period, SchoolClass, SchoolSettings, Student,
    StudentClassEnrollment, Subject, Teacher, Term, TimetableSlot, TimetableSolution,
)
from backend.routers import exports as exports_router
from backend.routers import lessons as lessons_router
from backend.routers import solver as solver_router
from backend.services import gaps_report, lesson_roster
from backend.services.slot_placement import build_placement_map


@pytest.fixture()
def env():
    """Δύο τμήματα Φυσικής (Α: Δευ 1η, Β: Δευ 2η) με έναν μαθητή στο καθένα."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    s.add(SchoolSettings(school_name="T", days_per_week=5, institution_type="frontistirio"))
    term = Term(name="Χ", is_active=True)
    subj = Subject(name="ΦΥΣΙΚΗ", short_name="Φ", color="#000000")
    teacher = Teacher(name="ΓΕΩΡΓΕΛΛΗΣ", short_name="ΓΕΩ", color="#000000")
    teacher2 = Teacher(name="ΓΚΟΥΓΚΗ", short_name="ΓΚΟ", color="#000000")
    ca, cb = SchoolClass(name="ΤΜΗΜΑ Α", short_name="Α"), SchoolClass(name="ΤΜΗΜΑ Β", short_name="Β")
    room = Classroom(name="Αίθ 1", short_name="Α1", room_type="regular")
    room2 = Classroom(name="Αίθ 2", short_name="Α2", room_type="regular")
    p1 = Period(name="1η", short_name="1", start_time="14:00", end_time="15:00", is_break=False, sort_order=1)
    p2 = Period(name="2η", short_name="2", start_time="15:00", end_time="16:00", is_break=False, sort_order=2)
    ignatis = Student(first_name="ΙΓΝΑΤΗΣ", last_name="ΜΟΥΤΑΦΗΣ", grade="Β΄ Λυκείου")
    dimitra = Student(first_name="ΔΗΜΗΤΡΑ", last_name="ΠΑΣΒΟΥΡΗ", grade="Β΄ Λυκείου")
    s.add_all([term, subj, teacher, teacher2, ca, cb, room, room2, p1, p2, ignatis, dimitra])
    s.commit()
    s.add_all([StudentClassEnrollment(student_id=ignatis.id, class_id=ca.id),
               StudentClassEnrollment(student_id=dimitra.id, class_id=cb.id)])
    sol = TimetableSolution(name="ΧΕΙΜΕΡΙΝΟ", status="optimal", term_id=term.id)
    la = Lesson(subject_id=subj.id, teacher_id=teacher.id, class_id=ca.id, periods_per_week=1, term_id=term.id)
    lb = Lesson(subject_id=subj.id, teacher_id=teacher2.id, class_id=cb.id, periods_per_week=1, term_id=term.id)
    s.add_all([sol, la, lb])
    s.commit()
    sa = TimetableSlot(solution_id=sol.id, lesson_id=la.id, day_of_week=0, period_id=p1.id,
                       classroom_id=room.id, is_unplaced=False)
    sb = TimetableSlot(solution_id=sol.id, lesson_id=lb.id, day_of_week=0, period_id=p2.id,
                       classroom_id=room2.id, is_unplaced=False)
    s.add_all([sa, sb])
    s.commit()
    app = FastAPI()
    app.include_router(lessons_router.router, prefix="/api/lessons")
    app.include_router(solver_router.router, prefix="/api/solver")
    app.include_router(exports_router.router, prefix="/api/exports")

    def override_db():
        yield s

    app.dependency_overrides[get_db] = override_db
    c = TestClient(app)
    c.s, c.sol, c.la, c.lb, c.sa, c.sb = s, sol, la, lb, sa, sb
    c.ignatis, c.dimitra, c.p1, c.p2, c.room, c.room2 = ignatis, dimitra, p1, p2, room, room2
    yield c
    s.close()


# --- service -------------------------------------------------------------------

def test_roster_is_the_class_until_overrides_say_otherwise(env):
    assert lesson_roster.students_of(env.s, env.la) == {env.ignatis.id}
    env.s.add_all([LessonStudentOverride(lesson_id=env.la.id, student_id=env.ignatis.id, mode="remove"),
                   LessonStudentOverride(lesson_id=env.la.id, student_id=env.dimitra.id, mode="add")])
    env.s.commit()
    assert lesson_roster.students_of(env.s, env.la) == {env.dimitra.id}
    assert lesson_roster.lesson_ids_for_student(env.s, env.dimitra.id, [env.la, env.lb]) == {env.la.id, env.lb.id}


def test_set_roster_writes_minimal_overrides_and_clears_them(env):
    assert lesson_roster.set_roster(env.s, env.la, [env.dimitra.id]) == {"attending": 1, "excluded": 1, "added": 1}
    env.s.commit()
    assert {(o.student_id, o.mode) for o in env.s.query(LessonStudentOverride).all()} == \
        {(env.ignatis.id, "remove"), (env.dimitra.id, "add")}
    lesson_roster.set_roster(env.s, env.la, [env.ignatis.id])     # πίσω στο τμήμα
    env.s.commit()
    assert env.s.query(LessonStudentOverride).count() == 0


# --- endpoints ------------------------------------------------------------------

def test_list_and_update_roster_with_conflict_confirmation(env):
    body = env.get(f"/api/lessons/{env.la.id}/students").json()
    assert [(x["name"], x["attends"], x["source"]) for x in body["students"]] == \
        [("ΜΟΥΤΑΦΗΣ ΙΓΝΑΤΗΣ", True, "τμήμα")]
    # Άλλη ώρα → καμία επικάλυψη
    ok = env.put(f"/api/lessons/{env.lb.id}/students", json={"attending": [env.dimitra.id, env.ignatis.id]})
    assert ok.status_code == 200 and ok.json()["added"] == 1
    # Τα δύο μαθήματα πάνε στην ΙΔΙΑ ώρα (άλλος καθηγητής, άλλη αίθουσα) →
    # τώρα η προσθήκη είναι επικάλυψη και ζητά επιβεβαίωση.
    env.put(f"/api/lessons/{env.lb.id}/students", json={"attending": [env.dimitra.id]})
    env.put(f"/api/solver/solutions/{env.sol.id}/slots/{env.sb.id}",
            json={"day_of_week": 0, "period_id": env.p1.id, "classroom_id": env.room2.id})
    clash = env.put(f"/api/lessons/{env.lb.id}/students",
                    json={"attending": [env.dimitra.id, env.ignatis.id]})
    assert clash.status_code == 409
    d = clash.json()["detail"]
    assert d["requires_force"] and "ΜΟΥΤΑΦΗΣ ΙΓΝΑΤΗΣ" in d["message"] and "ΦΥΣΙΚΗ" in d["message"]
    forced = env.put(f"/api/lessons/{env.lb.id}/students?force=true",
                     json={"attending": [env.dimitra.id, env.ignatis.id]})
    assert forced.status_code == 200
    assert env.put("/api/lessons/999/students", json={"attending": []}).status_code == 404


# --- όλο το σύστημα βλέπει τη σωστή λίστα ----------------------------------------

def test_placement_map_and_drag_respect_the_roster(env):
    """Ο Ιγνάτης φεύγει από το τμήμα Α και πάει στο Β: η Δευ 2η γίνεται
    απαγορευμένη για το μάθημα του Α (κοινός μαθητής) αντί για ελεύθερη."""
    before = {(c["day"], c["period_id"]): c for c in build_placement_map(env.s, env.sa)["cells"]}
    assert before[(0, env.p2.id)]["ok"] is True
    lesson_roster.set_roster(env.s, env.lb, [env.dimitra.id, env.ignatis.id])
    env.s.commit()
    after = {(c["day"], c["period_id"]): c for c in build_placement_map(env.s, env.sa)["cells"]}
    cell = after[(0, env.p2.id)]
    assert cell["ok"] is False and cell["code"] == "shared_student" and "ΜΟΥΤΑΦΗΣ" in cell["reason"]
    # …και ο enforcer του drop συμφωνεί (agreement με τον χάρτη)
    res = env.put(f"/api/solver/solutions/{env.sol.id}/slots/{env.sa.id}",
                  json={"day_of_week": 0, "period_id": env.p2.id})
    assert res.status_code == 400 and "ΜΟΥΤΑΦΗΣ" in str(res.json()["detail"])


def test_gaps_and_student_export_follow_the_roster(env):
    lesson_roster.set_roster(env.s, env.lb, [env.dimitra.id, env.ignatis.id])   # +2η ώρα
    env.s.commit()
    rep = gaps_report.gaps_report(env.s, env.sol.id)
    hours = {r["name"]: r["weekly_hours"] for r in rep["students"]}
    assert hours == {"ΜΟΥΤΑΦΗΣ ΙΓΝΑΤΗΣ": 2, "ΠΑΣΒΟΥΡΗ ΔΗΜΗΤΡΑ": 1}
    ics = env.get(f"/api/exports/ics?solution_id={env.sol.id}&student_id={env.ignatis.id}").text
    assert ics.count("BEGIN:VEVENT") == 2                      # και το μάθημα του άλλου τμήματος
    lesson_roster.set_roster(env.s, env.lb, [env.dimitra.id])  # φεύγει ξανά
    env.s.commit()
    ics2 = env.get(f"/api/exports/ics?solution_id={env.sol.id}&student_id={env.ignatis.id}").text
    assert ics2.count("BEGIN:VEVENT") == 1
