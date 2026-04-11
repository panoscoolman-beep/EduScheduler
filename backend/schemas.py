"""
Pydantic schemas for request/response validation.
"""

from pydantic import BaseModel, Field


# ─── Period ─────────────────────────────────────────────

class PeriodBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["1η Ώρα"])
    short_name: str = Field(..., min_length=1, max_length=10, examples=["1"])
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", examples=["08:15"])
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", examples=["09:00"])
    is_break: bool = False
    sort_order: int = Field(..., ge=0)


class PeriodCreate(PeriodBase):
    pass


class PeriodResponse(PeriodBase):
    id: int

    class Config:
        from_attributes = True


# ─── Teacher ────────────────────────────────────────────

class TeacherBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, examples=["Γιάννης Νικολάου"])
    short_name: str = Field(..., min_length=1, max_length=20, examples=["ΓΝ"])
    email: str | None = None
    phone: str | None = None
    max_periods_per_day: int | None = Field(None, ge=1, le=12)
    max_periods_per_week: int | None = Field(None, ge=1, le=60)
    min_periods_per_day: int = Field(0, ge=0, le=12)
    color: str = Field("#3B82F6", pattern=r"^#[0-9A-Fa-f]{6}$")


class TeacherCreate(TeacherBase):
    pass


class TeacherResponse(TeacherBase):
    id: int

    class Config:
        from_attributes = True


# ─── Teacher Availability ──────────────────────────────

class TeacherAvailabilityBase(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    period_id: int
    status: str = Field("available", pattern=r"^(available|unavailable|preferred)$")


class TeacherAvailabilityCreate(TeacherAvailabilityBase):
    pass


class TeacherAvailabilityResponse(TeacherAvailabilityBase):
    id: int
    teacher_id: int

    class Config:
        from_attributes = True


class TeacherAvailabilityBulkUpdate(BaseModel):
    """Bulk update availability — send the entire matrix."""
    availabilities: list[TeacherAvailabilityCreate]


# ─── Subject ────────────────────────────────────────────

class SubjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, examples=["Μαθηματικά"])
    short_name: str = Field(..., min_length=1, max_length=20, examples=["ΜΑΘ"])
    color: str = Field("#8B5CF6", pattern=r"^#[0-9A-Fa-f]{6}$")
    requires_special_room: bool = False
    special_room_type: str | None = None


class SubjectCreate(SubjectBase):
    pass


class SubjectResponse(SubjectBase):
    id: int

    class Config:
        from_attributes = True


# ─── Student ────────────────────────────────────────────

class StudentBase(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: str | None = None
    phone: str | None = None


class StudentCreate(StudentBase):
    pass


class StudentResponse(StudentBase):
    id: int

    class Config:
        from_attributes = True


# ─── School Class ───────────────────────────────────────

class SchoolClassBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["Α1"])
    short_name: str = Field(..., min_length=1, max_length=20, examples=["Α1"])
    grade_level: int | None = Field(None, ge=1, le=6)
    student_count: int = Field(0, ge=0)
    home_room_id: int | None = None


class SchoolClassCreate(SchoolClassBase):
    student_ids: list[int] = []


class SchoolClassUpdate(SchoolClassBase):
    student_ids: list[int] = []


class SchoolClassResponse(SchoolClassBase):
    id: int
    student_ids: list[int] = []

    class Config:
        from_attributes = True


# ─── Classroom ──────────────────────────────────────────

class ClassroomBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, examples=["Αίθουσα 1"])
    short_name: str = Field(..., min_length=1, max_length=20, examples=["Α1"])
    capacity: int = Field(30, ge=1, le=500)
    room_type: str = Field("regular", pattern=r"^(regular|lab|gym|computer_lab)$")
    building: str | None = None


class ClassroomCreate(ClassroomBase):
    pass


class ClassroomResponse(ClassroomBase):
    id: int

    class Config:
        from_attributes = True


# ─── Lesson (Card) ──────────────────────────────────────

class LessonBase(BaseModel):
    subject_id: int
    teacher_id: int
    class_id: int
    classroom_id: int | None = None
    periods_per_week: int = Field(1, ge=1, le=20)
    duration: int = Field(1, ge=1, le=4)
    is_locked: bool = False


class LessonCreate(LessonBase):
    pass


class LessonResponse(LessonBase):
    id: int
    subject_name: str | None = None
    teacher_name: str | None = None
    class_name: str | None = None
    classroom_name: str | None = None

    class Config:
        from_attributes = True


# ─── Constraint ─────────────────────────────────────────

class ConstraintBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    constraint_type: str = Field(..., pattern=r"^(hard|soft)$")
    category: str = Field(..., pattern=r"^(teacher|class|subject|room|general)$")
    rule: str  # JSON string
    weight: int = Field(50, ge=0, le=100)
    is_active: bool = True
    entity_id: int | None = None
    entity_type: str | None = None


class ConstraintCreate(ConstraintBase):
    pass


class ConstraintResponse(ConstraintBase):
    id: int

    class Config:
        from_attributes = True


# ─── Timetable Solution ────────────────────────────────

class TimetableSlotResponse(BaseModel):
    id: int
    lesson_id: int
    day_of_week: int
    period_id: int
    classroom_id: int
    is_locked: bool
    # Enriched fields
    subject_name: str | None = None
    subject_short: str | None = None
    subject_color: str | None = None
    teacher_name: str | None = None
    teacher_short: str | None = None
    class_name: str | None = None
    class_short: str | None = None
    classroom_name: str | None = None

    class Config:
        from_attributes = True


class TimetableSlotUpdate(BaseModel):
    """Payload for manually moving a slot via Drag & Drop."""
    day_of_week: int = Field(..., ge=0, le=6)
    period_id: int
    classroom_id: int | None = None
    is_locked: bool | None = None


class TimetableSolutionResponse(BaseModel):
    id: int
    name: str
    created_at: str | None = None
    status: str
    score: float | None = None
    slots: list[TimetableSlotResponse] = []

    class Config:
        from_attributes = True


class SolverRequest(BaseModel):
    """Request to start timetable generation."""
    name: str = Field("Νέο Πρόγραμμα", min_length=1, max_length=200)
    max_time_seconds: int = Field(120, ge=10, le=600)


class SolverStatusResponse(BaseModel):
    solution_id: int
    status: str
    message: str
    score: float | None = None


# ─── Settings ───────────────────────────────────────────

class SchoolSettingsBase(BaseModel):
    school_name: str = Field("Το Σχολείο μου", min_length=1, max_length=200)
    days_per_week: int = Field(5, ge=1, le=7)
    academic_year: str | None = None
    institution_type: str = Field("frontistirio", pattern=r"^(frontistirio|school)$")


class SchoolSettingsResponse(SchoolSettingsBase):
    id: int

    class Config:
        from_attributes = True
