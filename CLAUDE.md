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

Postgres 16. Τα SQLAlchemy models (`backend/models/`) περιγράφουν το schema,
αλλά η βάση αλλάζει **μόνο μέσω Alembic** (`alembic/versions/`). Το
`entrypoint.sh` τρέχει `alembic upgrade head` πριν ξεκινήσει το uvicorn, οπότε
κάθε deploy εφαρμόζει αυτόματα όσες revisions λείπουν. Το
`Base.metadata.create_all` **έχει αφαιρεθεί** — έκρυβε migrations που έλειπαν
(βλ. `d7e8f9a0b1c2_slot_history_and_is_locked.py` και το docstring του
`lifespan` στο `backend/main.py`). Head στις 2026-09-10:
`e1f2a3b4c5d6_solution_archived_at.py`.

**Αλλαγή schema = νέα Alembic revision**, ποτέ χειροκίνητο `ALTER TABLE` στο prod:

1. Άλλαξε το model στο `backend/models/`.
2. Νέο αρχείο στο `alembic/versions/` με `down_revision` = το τρέχον head
   (έλεγχος: `docker exec edscheduler-backend alembic heads`).
3. Pattern **additive + idempotent** με raw SQL: `ADD COLUMN IF NOT EXISTS`
   στο `upgrade()`, `DROP COLUMN IF EXISTS` στο `downgrade()`. Πρότυπο:
   `c3d4e5f6a7b8_student_grade.py`.
4. Push σε `master` → CI → το entrypoint κάνει `alembic upgrade head`.

### Tables

| Table | Σκοπός |
|---|---|
| `students` | Μαθητές (id, first_name, last_name, email, phone, grade, track, max_days_per_week). `grade` VARCHAR(60) = τάξη, `track` VARCHAR(120) = κατεύθυνση (ΓΕΛ) ή τομέας (ΕΠΑΛ). Ελεύθερο κείμενο στη βάση· ο κατάλογος επιλογών ζει στο `backend/services/grade_catalog.py` και σερβίρεται από το `GET /api/students/grade-options` |
| `teachers` | Καθηγητές (id, name, short_name, email, phone, max_periods_per_*, color) |
| `classes` | Τμήματα (όχι ακαδημαϊκές περίοδοι — μάθημα + ομάδα μαθητών) |
| `subjects` | Μαθήματα/κωδικοί (Άλγεβρα, Έκθεση κτλ) |
| `classrooms` | Αίθουσες με capacity & type |
| `lessons` | Διδακτικές ενότητες (συσχετίζει class με teacher με subject) |
| `periods` | Διδακτικές ώρες της ημέρας (1η Ώρα 08:00–09:00, 2η Ώρα…): name, short_name, start_time, end_time, is_break, sort_order. **Όχι** ακαδημαϊκές περίοδοι (αυτές στο EDS είναι τα `terms`/σενάρια) |
| `constraints` | Hard/soft constraints με βαρύτητες |
| `student_class_enrollments` | M:N — ποιοι μαθητές σε ποιο τμήμα |
| `student_availability` | Πότε ένας μαθητής **δεν** μπορεί |
| `teacher_availability` | Πότε ένας καθηγητής **δεν** μπορεί |
| `timetable_slots` | Το παραγόμενο πρόγραμμα — ποια ώρα/μέρα/αίθουσα τι μάθημα |
| `timetable_solutions` | Solver runs — multiple "what-if" λύσεις. `archived_at` = αρχειοθετημένο πρόγραμμα: μένει ακέραιο αλλά βγαίνει από τη λίστα, από τον parking-lot sync και από τον έλεγχο «🔍 Τι επηρεάζει;» (POST /solver/solutions/{id}/archive\|unarchive) |
| `school_settings` | Global ρυθμίσεις (έναρξη/λήξη ημέρας, διάρκεια διδακτικής ώρας...) |
| `terms` | Σενάρια ωραρίου — scope για lessons/availability/solutions (term_id NOT NULL παντού), προαιρετικά start/end dates για ICS |

> ⚠️ **Η διαγραφή γραμμής στο `periods` είναι καταστροφική.** Τα FK προς
> `periods` είναι `ON DELETE CASCADE`, οπότε σβήνονται ΟΡΙΣΤΙΚΑ όλες οι
> τοποθετήσεις (`timetable_slots`) και οι δηλώσεις διαθεσιμότητας
> καθηγητών/μαθητών σε εκείνη την ώρα, σε **ΟΛΑ** τα προγράμματα (solutions)
> και σενάρια — ο πίνακας `periods` είναι κοινός για όλα. Το
> `DELETE /api/periods/{id}` επιστρέφει **409** (`period_in_use`,
> `requires_force`) όταν η ώρα χρησιμοποιείται, και προχωρά μόνο με
> `?force=true` (το frontend ζητά πρώτα επιβεβαίωση). Πριν από τέτοια
> διαγραφή έλεγξε ότι υπάρχει πρόσφατο backup στο `~/backups/edscheduler`.

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

`.github/workflows/deploy.yml`, self-hosted runner στον ίδιο Debian server.
Ο runner τρέχει ως systemd unit
`actions.runner.panoscoolman-beep-EduScheduler.debian-edscheduler.service`
με auto-restart (`Restart=on-failure`, drop-in `override.conf`). Το παλιό
πρόβλημα «failed από 17 Μαρτίου 2026» έχει λυθεί.

Σε push σε `master` τα βήματα τρέχουν με αυτή τη σειρά, και κάθε αποτυχία
σταματά το deploy:

1. **pytest** μέσα στο image `eduscheduler-backend-citest` (CI-only tag, ώστε
   ένα κόκκινο run να μην αγγίζει ποτέ το production image).
2. **Frontend JS tests:** `npm ci` και μετά `node --test frontend/js/tests/*.test.js`
   (Node built-in runner + jsdom).
3. **Deploy:** rsync στο `/home/coolman/EduScheduler` (χωρίς `.git`,
   `.github`, `.env`) και `docker compose up -d --build`.
4. **Healthcheck:** `curl http://localhost:8082/api/healthz`, έως 3 προσπάθειες.

Τα ίδια gates τοπικά, πριν από push:

```bash
docker build -t eduscheduler-backend-citest . && docker run --rm -v "$PWD":/work:ro -v /dev/null:/work/.env -w /work -e PYTHONPATH=/work eduscheduler-backend-citest python -m pytest tests/ -q -p no:cacheprovider
npm ci && node --test frontend/js/tests/*.test.js
```

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

**Cache-buster frontend (`?v=N`).** Όλα τα CSS/JS στο `frontend/index.html`
φορτώνονται με `?v=N` (π.χ. `js/api.js?v=55`). Σε **κάθε** αλλαγή JS/CSS
ανέβασε το `N` σε όλες τις εμφανίσεις μαζί, αλλιώς οι browsers σερβίρουν την
παλιά cached έκδοση:

```bash
grep -o '?v=[0-9]*' frontend/index.html | sort | uniq -c   # τρέχουσα τιμή, πρέπει να είναι μία
sed -i 's/?v=55"/?v=56"/g' frontend/index.html
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
