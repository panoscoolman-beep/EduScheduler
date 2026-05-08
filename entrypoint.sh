#!/bin/sh
# Run pending Alembic migrations before launching uvicorn so a fresh
# container always boots against an up-to-date schema.
#
# Failure mode if we skipped this: a new migration would ship with the
# code, the container would start, and the recovery hook (or any other
# code that touched a new column / new CHECK value) would 500. The user
# would see "Failed to fetch" or similar.
#
# `alembic upgrade head` is idempotent — re-running on an already-
# upgraded DB is a no-op.

set -e

echo "[entrypoint] Running alembic upgrade head..."
alembic upgrade head

echo "[entrypoint] Starting uvicorn..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
