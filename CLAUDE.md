# EduScheduler — Master Documentation

> **🎯 Resuming work?** Read
> [`/home/coolman/korifi-crm-v2/SESSION_STATE.md`](../korifi-crm-v2/SESSION_STATE.md)
> first — has the live state from the last session across both repos.
> Updated 2026-05-08.

Αυτόματο ωρολόγιο πρόγραμμα για σχολεία & φροντιστήρια. Χρησιμοποιεί Google
OR-Tools CP-SAT solver για να βγάλει βέλτιστα προγράμματα με δεκάδες
περιορισμούς (διαθεσιμότητα καθηγητών, μαθητών, αιθουσών, σύγκρουση αδειών,
hard/soft constraints με βαρύτητα).

## Stack

- **Backend:** Python 3.12 + FastAPI (`backend/main.py`)
- **Solver:** Google OR-Tools CP-SAT (`backend/solver/`)
- **Database:** PostgreSQL 16 alpine
- **Frontend:** Vanilla HTML/CSS/JS (`frontend/`) — served από FastAPI ως static files
- **Deployment:** Docker Compose (2 services: backend + db)
- **CI/CD:** GitHub Actions self-hosted runner στον ίδιο Debian server

## Architecture

```
                       ┌──────────────────────────────┐
                       │ Browser (frontend/index.html)│
                       │  - timetable grid view       │
                       │  - drag & drop slots          │
                       │  - student/teacher CRUD       │
                       │  - constraint editor          │
                       └────────────┬─────────────────┘
                                    │ HTTP (same origin via static)
                                    ▼
                       ┌──────────────────────────────┐
                       │ FastAPI (port 8000 → 8082)  │
                       │  ├─ /api/students            │
                       │  ├─ /api/teachers            │
                       │  ├─ /api/classes             │
                       │  ├─ /api/classrooms          │
                       │  ├─ /api/lessons             │
                       │  ├─ /api/subjects            │
                       │  ├─ /api/periods             │
                       │  ├─ /api/constraints         │
                       │  ├─ /api/solver/generate     │
                       │  ├─ /api/solver/solutions    │
                       │  ├─ /api/terms  (σενάρια)    │
                       │  ├─ /api/exports (ics/print/ │
                       │  │               xlsx)       │
                       │  ├─ /api/integration (CRM      │
                       │  │        student import)      │
                       │  ├─ /api/settings            │
                       │  └─ /api/healthz (public)    │
                       └────────────┬─────────────────┘
                                    │ SQLAlchemy
                                    ▼
                       ┌──────────────────────────────┐
                       │ Postgres 16 (db)             │
                       │  edscheduler database        │
                       └──────────────────────────────┘
```

## Docker services (`docker-compose.yml`)

| Service | Container name | Image | Ports | Notes |
|---|---|---|---|---|
| `backend` | `edscheduler-backend` | Custom (Dockerfile) | 8082 → 8000 | Static frontend mounted ως volume |
| `db` | `edscheduler-db` | `postgres:16-alpine` | (internal only) | Healthcheck με `pg_isready` |

**Network:** `edscheduler-net` (bridge) — isolated από άλλα projects.
**Volume:** `postgres_data` (named volume).

## Database

Postgres 16 με auto-create-tables στο startup (`Base.metadata.create_all`),
δηλαδή το schema ορίζεται ΟΛΟ από τα SQLAlchemy models (`backend/models/`).
**Δεν υπάρχουν versioned migrations** — αν αλλάξει το schema, χρειάζεται
manual ALTER TABLE.

### Tables

| Table | Σκοπός |
|---|---|
| `students` | Μαθητές (id, first_name, last_name, email, phone, max_days_per_week) |
| `teachers` | Καθηγητές (id, name, short_name, email, phone, max_periods_per_*, color) |
| `classes` | Τμήματα (όχι ακαδημαϊκές περίοδοι — μάθημα + ομάδα μαθητών) |
| `subjects` | Μαθήματα/κωδικοί (Άλγεβρα, Έκθεση κτλ) |
| `classrooms` | Αίθουσες με capacity & type |
| `lessons` | Διδακτικές ενότητες (συσχετίζει class με teacher με subject) |
| `periods` | Ακαδημαϊκές περίοδοι (Σεπτ-Ιούν) |
| `constraints` | Hard/soft constraints με βαρύτητες |
| `student_class_enrollments` | M:N — ποιοι μαθητές σε ποιο τμήμα |
| `student_availability` | Πότε ένας μαθητής **δεν** μπορεί |
| `teacher_availability` | Πότε ένας καθηγητής **δεν** μπορεί |
| `timetable_slots` | Το παραγόμενο πρόγραμμα — ποια ώρα/μέρα/αίθουσα τι μάθημα |
| `timetable_solutions` | Solver runs — multiple "what-if" λύσεις |
| `school_settings` | Global ρυθμίσεις (έναρξη/λήξη ημέρας, διάρκεια διδακτικής ώρας...) |
| `terms` | Σενάρια ωραρίου — scope για lessons/availability/solutions (term_id NOT NULL παντού), προαιρετικά start/end dates για ICS |

## Solver (`backend/solver/engine.py`)

Χτίζει CP-SAT model από το DB:

- **Variables:** για κάθε `lesson × time_slot × classroom`
- **Hard constraints:**
  - H1: Καθηγητής δεν διδάσκει σε δύο μέρη ταυτόχρονα
  - H2: Αίθουσα δεν χρησιμοποιείται για δύο μαθήματα ταυτόχρονα
  - H3: Τμήμα δεν έχει δύο μαθήματα ταυτόχρονα
  - H4: Ένα μάθημα τοποθετείται ακριβώς N φορές
  - H5: Καθηγητής δεν δουλεύει σε hours που έχει unavailable
  - H6: Μαθητής δεν παρακολουθεί σε hours που έχει unavailable
  - **H7: Δύο τμήματα με κοινό μαθητή δεν πέφτουν ταυτόχρονα** (αυτό είναι το
    "killer feature" του φροντιστηριακού mode)
- **Soft constraints:** spread, balance, preference με βαρύτητες

Output: `timetable_slots` rows + `timetable_solutions` row με metadata
(quality score, runtime, constraints violated).

## CI/CD

`.github/workflows/deploy.yml` (self-hosted runner — ο ίδιος που έχει το
korifi-crm). Σε push σε `master`: rsync → docker compose up -d --build.

⚠️ **Σημαντικό**: ο runner είναι **failed από 17 Μαρτίου 2026** (ίδιο όπως
το korifi-crm — μοιράζονται το ίδιο service). Δες
`korifi-crm-v2/CLAUDE.md` για instructions επανεκκίνησης.

## Common operations

```bash
# Status
docker ps --filter name=edscheduler

# Logs
docker logs -f edscheduler-backend

# DB shell
docker exec -it edscheduler-db psql -U edscheduler -d edscheduler

# Manual rebuild (μετά από code changes)
cd /home/coolman/EduScheduler
docker compose up -d --build

# Generate timetable (από API — θέλει bearer token από το .env)
curl -X POST http://localhost:8082/api/solver/generate \
  -H "Authorization: Bearer $EDSCHEDULER_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_time_seconds": 30}'

# Swagger UI: ΔΕΝ εκτίθεται σε production (404) — μόνο τοπικά με dev run
```

## Known issues

1. ~~No versioned migrations~~ ✅ **Resolved (2026-05-06)** — Alembic
   εισήχθη στο commit `fa8d556` ("chore: introduce Alembic for versioned
   schema migrations").
2. ~~No authentication~~ ✅ **Resolved (2026-06-13):** fail-closed Bearer
   auth σε όλα τα /api/* (`BearerTokenMiddleware`, `EDSCHEDULER_API_TOKEN`)·
   δημόσιο μόνο το `/api/healthz`. ⚠️ Γνωστό όριο: το same-origin exemption
   βασίζεται σε client-settable headers (Sec-Fetch-Site/Origin) — non-browser
   caller μπορεί να τα πλαστογραφήσει· η ουσιαστική περίμετρος είναι το
   firewall/Tailscale (APP-PORT-GUARD).
3. ~~Self-hosted runner manual~~ ✅ **Resolved:** τρέχει μέσω systemd
   (`actions.runner.panoscoolman-beep-EduScheduler.debian-edscheduler.service`)
   με auto-restart, self-updated (v2.335+).
4. **Frontend είναι vanilla JS** — λιγότερο maintainable από framework. Για
   τώρα δουλεύει — refactor σε React/Svelte θα ήταν επόμενη εργασία.

## Integration με Korifi CRM

**Βήμα 1 LIVE (2026-07-04):** εισαγωγή μαθητών από CRM με preview→commit
(`backend/services/crm_importer.py`, `/api/integration/crm/students/*`,
κουμπί «⬇️ Εισαγωγή από CRM» στην καρτέλα Μαθητές). One-way pull· CRM master.
Env στο EDS `.env`: `KORIFI_API_BASE` (default `http://korifi-crm-v2-api-1:8000`)
+ `KORIFI_API_TOKEN` (ίδιος με CRM). Πλήρες plan και progress:
- `/home/coolman/korifi-crm-v2/docs/INTEGRATION.md`
- `αλλαγες.md` ενότητα 6

**Source-of-truth strategy:**
- **Korifi CRM** = master για στοιχεία επικοινωνίας, οικονομικά, βαθμούς, παρουσίες
- **EduScheduler** = master για όλο το scheduling (classes, lessons, timetable, classrooms, subjects, availability)
- Τα δύο συστήματα διατηρούνται ανεξάρτητα — η ενοποίηση γίνεται μέσω REST API.

## See also

- `αλλαγες.md` — Greek changelog (ιστορικό αλλαγών)
- `README.md` — high-level user guide
- `/home/coolman/korifi-crm-v2/CLAUDE.md` — partner system documentation
- `/home/coolman/korifi-crm-v2/docs/INTEGRATION.md` — integration master plan
