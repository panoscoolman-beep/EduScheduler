FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Alembic migrations (so `alembic upgrade head` works inside the container)
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/

# Entrypoint runs `alembic upgrade head` before launching uvicorn so a
# rebuilt container always picks up new migrations automatically. The
# previous CMD-only setup left freshly-shipped migrations un-applied.
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

EXPOSE 8000

CMD ["./entrypoint.sh"]
