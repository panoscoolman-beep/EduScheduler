"""
EduScheduler Backend — FastAPI Application Entry Point

Serves the REST API and static frontend files.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import engine, Base
from backend.routers import (
    teachers,
    subjects,
    classrooms,
    classes,
    periods,
    lessons,
    constraints,
    solver,
    students,
    settings as settings_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup."""
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="EduScheduler API",
    description="Αυτόματο Ωρολόγιο Πρόγραμμα για Σχολεία & Φροντιστήρια",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
app.include_router(teachers.router, prefix="/api/teachers", tags=["Καθηγητές"])
app.include_router(subjects.router, prefix="/api/subjects", tags=["Μαθήματα"])
app.include_router(classrooms.router, prefix="/api/classrooms", tags=["Αίθουσες"])
app.include_router(classes.router, prefix="/api/classes", tags=["Τάξεις"])
app.include_router(periods.router, prefix="/api/periods", tags=["Ώρες"])
app.include_router(lessons.router, prefix="/api/lessons", tags=["Μαθήματα-Κάρτες"])
app.include_router(students.router, prefix="/api/students", tags=["Μαθητές"])
app.include_router(constraints.router, prefix="/api/constraints", tags=["Περιορισμοί"])
app.include_router(solver.router, prefix="/api/solver", tags=["Solver"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["Ρυθμίσεις"])

# Serve frontend static files
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
