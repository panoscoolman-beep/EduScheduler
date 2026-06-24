"""
EduScheduler Backend — FastAPI Application Entry Point

Serves the REST API and static frontend files.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.auth import BearerTokenMiddleware
from backend.config import settings
from backend.database import engine, Base
from backend.routers import (
    terms,
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
    exports,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Recover any solver run that was in flight when the previous
    container died.

    Schema is owned entirely by Alembic now — `entrypoint.sh` runs
    `alembic upgrade head` before uvicorn starts, so `create_all` was
    removed (it silently masked missing migrations for slot_history and
    is_locked; see migration d7e8f9a0b1c2).

    Why the recovery hook: a `docker compose up -d --build` mid-solve
    kills the worker while the TimetableSolution row sits at
    status='generating'. This flips every stuck 'generating' row to
    'error' on boot so the UI shows a clear explanation, not a phantom job.
    """
    _recover_stuck_runs()
    yield


def _recover_stuck_runs() -> None:
    import json
    import logging
    from datetime import datetime, timezone
    from sqlalchemy.orm import Session as _Session
    from backend.models import TimetableSolution

    logger = logging.getLogger(__name__)
    session = _Session(bind=engine)
    try:
        stuck = (
            session.query(TimetableSolution)
            .filter(TimetableSolution.status == "generating")
            .all()
        )
        if not stuck:
            return
        for sol in stuck:
            sol.status = "error"
            existing = {}
            if sol.metadata_json:
                try:
                    existing = json.loads(sol.metadata_json)
                except (TypeError, ValueError):
                    existing = {}
            existing["recovered_at"] = datetime.now(timezone.utc).isoformat()
            existing["recovery_reason"] = (
                "Ο solver διακόπηκε από restart του container. Δοκίμασε ξανά."
            )
            sol.metadata_json = json.dumps(existing, default=str)
        session.commit()
        logger.warning(
            "Recovered %d stuck 'generating' solver runs to 'error' status",
            len(stuck),
        )
    finally:
        session.close()


# Hide interactive docs in production — they live under "/" (not "/api/*")
# so they bypass the bearer middleware and would expose the full API schema.
_is_prod = settings.app_env == "production"
app = FastAPI(
    title="EduScheduler API",
    description="Αυτόματο Ωρολόγιο Πρόγραμμα για Σχολεία & Φροντιστήρια",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bearer auth — guards /api/* except same-origin browser calls and the
# public paths in auth._PUBLIC_API_PATHS (fail-closed if token unset).
app.add_middleware(BearerTokenMiddleware)


@app.get("/api/healthz", tags=["Health"])
def healthz():
    """Public liveness + DB check — used by the CI health check and the
    docker healthcheck. Listed in auth._PUBLIC_API_PATHS, so it never
    requires a token."""
    from sqlalchemy import text as sa_text

    from backend.database import SessionLocal

    try:
        with SessionLocal() as session:
            session.execute(sa_text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "degraded", "db": "unreachable"}, status_code=503)
    return {"status": "ok"}


# API Routes
app.include_router(terms.router, prefix="/api/terms", tags=["Σενάρια"])
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
app.include_router(exports.router, prefix="/api/exports", tags=["Εξαγωγές"])

# Serve frontend static files
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
