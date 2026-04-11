"""
SQLAlchemy ORM Models — All database entities for EduScheduler.
"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Text,
    ForeignKey, DateTime, UniqueConstraint, CheckConstraint, Table
)
from sqlalchemy.orm import relationship

from backend.database import Base


class SchoolSettings(Base):
    """Global school/institution settings."""

    __tablename__ = "school_settings"

    id = Column(Integer, primary_key=True, default=1)
    school_name = Column(String(200), nullable=False, default="Το Σχολείο μου")
    days_per_week = Column(Integer, nullable=False, default=5)
    academic_year = Column(String(20))
    institution_type = Column(String(50), default="frontistirio")  # frontistirio / school


class Period(Base):
    """A teaching period / time slot within a day."""

    __tablename__ = "periods"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    short_name = Column(String(10), nullable=False)
    start_time = Column(String(5), nullable=False)  # "08:15"
    end_time = Column(String(5), nullable=False)    # "09:00"
    is_break = Column(Boolean, default=False)
    sort_order = Column(Integer, nullable=False)

    # Relationships
    availabilities = relationship("TeacherAvailability", back_populates="period", cascade="all, delete-orphan")
    timetable_slots = relationship("TimetableSlot", back_populates="period", cascade="all, delete-orphan")


class Teacher(Base):
    """A teacher / instructor."""

    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    short_name = Column(String(20), nullable=False, unique=True)
    email = Column(String(200))
    phone = Column(String(30))
    max_periods_per_day = Column(Integer)
    max_periods_per_week = Column(Integer)
    min_periods_per_day = Column(Integer, default=0)
    color = Column(String(7), default="#3B82F6")

    # Relationships
    availabilities = relationship("TeacherAvailability", back_populates="teacher", cascade="all, delete-orphan")
    lessons = relationship("Lesson", back_populates="teacher", cascade="all, delete-orphan")


class TeacherAvailability(Base):
    """Teacher time-off / availability per day+period."""

    __tablename__ = "teacher_availability"

    id = Column(Integer, primary_key=True, autoincrement=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 4=Friday
    period_id = Column(Integer, ForeignKey("periods.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, default="available")  # available / unavailable / preferred

    __table_args__ = (
        UniqueConstraint("teacher_id", "day_of_week", "period_id", name="uq_teacher_day_period"),
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_day_range"),
        CheckConstraint("status IN ('available', 'unavailable', 'preferred')", name="ck_status_values"),
    )

    # Relationships
    teacher = relationship("Teacher", back_populates="availabilities")
    period = relationship("Period", back_populates="availabilities")


class Subject(Base):
    """A subject / course."""

    __tablename__ = "subjects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    short_name = Column(String(20), nullable=False, unique=True)
    color = Column(String(7), default="#8B5CF6")
    requires_special_room = Column(Boolean, default=False)
    special_room_type = Column(String(50))  # lab / gym / computer_lab

    # Relationships
    lessons = relationship("Lesson", back_populates="subject", cascade="all, delete-orphan")


class SchoolClass(Base):
    """A class / section (e.g. A1, B2)."""

    __tablename__ = "classes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    short_name = Column(String(20), nullable=False, unique=True)
    grade_level = Column(Integer)  # 1=A, 2=B, 3=C
    student_count = Column(Integer, default=0)
    home_room_id = Column(Integer, ForeignKey("classrooms.id", ondelete="SET NULL"))

    # Relationships
    home_room = relationship("Classroom", foreign_keys=[home_room_id])
    lessons = relationship("Lesson", back_populates="school_class", cascade="all, delete-orphan")
    enrollments = relationship("StudentClassEnrollment", back_populates="school_class", cascade="all, delete-orphan")

    @property
    def student_ids(self):
        return [enrollment.student_id for enrollment in self.enrollments]


class Student(Base):
    """A student in the tutoring center."""

    __tablename__ = "students"

    id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(200))
    phone = Column(String(30))
    
    # Relationships
    enrollments = relationship("StudentClassEnrollment", back_populates="student", cascade="all, delete-orphan")

    @property
    def full_name(self):
        return f"{self.last_name} {self.first_name}"


class StudentClassEnrollment(Base):
    """Mapping between a Student and a SchoolClass (Many-to-Many)."""

    __tablename__ = "student_class_enrollments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    enrolled_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    student = relationship("Student", back_populates="enrollments")
    school_class = relationship("SchoolClass", back_populates="enrollments")

    __table_args__ = (
        UniqueConstraint("student_id", "class_id", name="uq_student_class"),
    )


class Classroom(Base):
    """A physical classroom / room."""

    __tablename__ = "classrooms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    short_name = Column(String(20), nullable=False, unique=True)
    capacity = Column(Integer, default=30)
    room_type = Column(String(50), default="regular")  # regular / lab / gym / computer_lab
    building = Column(String(100))

    # Relationships
    lessons = relationship("Lesson", back_populates="classroom")
    timetable_slots = relationship("TimetableSlot", back_populates="classroom")


class Lesson(Base):
    """
    A Lesson Card — the CORE entity.
    Links Subject + Teacher + Class + (optional) Room + scheduling requirements.
    """

    __tablename__ = "lessons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subject_id = Column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="SET NULL"))
    periods_per_week = Column(Integer, nullable=False, default=1)
    duration = Column(Integer, nullable=False, default=1)  # 1=single, 2=double period
    is_locked = Column(Boolean, default=False)

    # Relationships
    subject = relationship("Subject", back_populates="lessons")
    teacher = relationship("Teacher", back_populates="lessons")
    school_class = relationship("SchoolClass", back_populates="lessons")
    classroom = relationship("Classroom", back_populates="lessons")
    timetable_slots = relationship("TimetableSlot", back_populates="lesson", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("periods_per_week >= 1 AND periods_per_week <= 20", name="ck_periods_range"),
        CheckConstraint("duration >= 1 AND duration <= 4", name="ck_duration_range"),
    )


class Constraint(Base):
    """A scheduling constraint (hard or soft)."""

    __tablename__ = "constraints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    constraint_type = Column(String(10), nullable=False)  # hard / soft
    category = Column(String(50), nullable=False)  # teacher / class / subject / room / general
    rule = Column(Text, nullable=False)  # JSON-encoded rule definition
    weight = Column(Integer, default=50)  # 0-100 importance for soft constraints
    is_active = Column(Boolean, default=True)
    entity_id = Column(Integer)  # Optional: specific entity
    entity_type = Column(String(50))  # teacher / class / etc.

    __table_args__ = (
        CheckConstraint("constraint_type IN ('hard', 'soft')", name="ck_constraint_type"),
        CheckConstraint("weight >= 0 AND weight <= 100", name="ck_weight_range"),
    )


class TimetableSolution(Base):
    """A generated timetable solution."""

    __tablename__ = "timetable_solutions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="draft")  # draft / generating / optimal / feasible / infeasible
    score = Column(Float)
    metadata_json = Column(Text)  # JSON with solver stats
    soft_violations = Column(Text)  # JSON list of violated soft constraints

    # Relationships
    slots = relationship("TimetableSlot", back_populates="solution", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'generating', 'optimal', 'feasible', 'infeasible')",
            name="ck_solution_status",
        ),
    )


class TimetableSlot(Base):
    """A single assigned slot in a timetable solution."""

    __tablename__ = "timetable_slots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    solution_id = Column(Integer, ForeignKey("timetable_solutions.id", ondelete="CASCADE"), nullable=False)
    lesson_id = Column(Integer, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0-4
    period_id = Column(Integer, ForeignKey("periods.id", ondelete="CASCADE"), nullable=False)
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False)
    is_locked = Column(Boolean, default=False)

    # Relationships
    solution = relationship("TimetableSolution", back_populates="slots")
    lesson = relationship("Lesson", back_populates="timetable_slots")
    period = relationship("Period", back_populates="timetable_slots")
    classroom = relationship("Classroom", back_populates="timetable_slots")

    __table_args__ = (
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_slot_day_range"),
    )
