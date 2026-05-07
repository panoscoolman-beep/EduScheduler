# Changelog

Όλες οι σημαντικές αλλαγές του EduScheduler. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### 2026-05-08 — UX + UI improvements + 99 unit tests

Major UX session που πρόσθεσε 7 user-facing βελτιώσεις και έχτισε
ολοκληρωμένο test suite από το μηδέν.

**UI features**

- **Constraints CRUD UI** (`8d7c5a3`) — smart typed form αντί για raw
  JSON. RULE_TYPES catalogue στο constraints.js, dynamic params per
  rule type, friendly summary στο table view.
- **🔒 Lock & Regenerate** (`1f9429c`) — toggle σε κάθε slot card +
  button που τρέχει solver με τα locked ως hard constraints. Νέο
  endpoint `POST /api/solver/regenerate/{id}` + locked_assignments
  param στον TimetableSolver.
- **Lesson form live validation** (`19a44ba`) — hint area κάτω από τη
  φόρμα ελέγχει distribution validity (positive ints, sum==ppw, max
  block ≤ teaching periods/day) + subject↔classroom room-type
  compatibility. Errors block save, warnings ενημερώνουν.
- **CSV bulk import για lessons** (`12885dd`) — paste/upload CSV →
  preview table με per-row ✅/⛔ → commit transactional. Subject/
  teacher/class/classroom resolution by name OR short_name.
- **3 starter templates** (`8025d55`) — Φροντιστήριο Λυκείου /
  Γυμνάσιο / Πανελλήνιες με subjects + classes + αίθουσες +
  constraints. Idempotent apply (matches by name OR short_name) +
  preview→confirm flow στο Settings tab.
- **📊 Compare solutions side-by-side** (`ad76648`) — modal με
  checkboxes για επιλογή λύσεων, table με 8 metrics (score, placed,
  gaps, workload σ, days/class, late periods) και ⭐ στο winner.
- **Chip-based distribution selector** (`7031140`) — UI-friendly
  τρόπος επιλογής distribution. "6×1ωρα", "3×2ωρα", "2×3ωρα" κλπ ως
  clickable chips αντί για manual CSV typing.

**Bug fixes**

- **Σάββατο slots invisible** (`31a07ae`) — frontend hardcoded `5`
  ημέρες στο grid render, αόρατα τα slots με `day_of_week=5`. Fix:
  διαβάζει `settings.days_per_week`. Ο user έβλεπε 4 ώρες αντί για 5.
- **422 σε constraints route** (μέσα στο `8d7c5a3`) —
  `/distribution-suggestions` δηλωμένο μετά από `/{lesson_id}` έκανε
  τη FastAPI να προσπαθεί να parse-άρει "distribution-suggestions" ως
  int. Fix: route declared πριν από `/{lesson_id}`.
- **Distribution comma-collision στο CSV import** (μέσα στο `12885dd`)
  — distribution "2,2,1" συγκρούεται με τον CSV separator. Custom
  parser που absorbs trailing extras στη distribution column.
- **Idempotency by name OR short_name** (`8025d55`) — αρχικά μόνο
  short_name έλεγχα στα templates. Bug fix: collision αν user έχει
  classroom με ίδιο name αλλά διαφορετικό short_name. Fix: union of
  both keys.

**Operations**

- **API authentication** (`64e07d7`, `62e373c`) — Bearer middleware
  με Sec-Fetch-Site bypass για browser SPA. Korifi-side adds
  Authorization σε όλα τα cross-service calls.
  ⚠️ **Disabled in production per user preference** —
  `EDSCHEDULER_API_TOKEN` not set, middleware fails open with log
  warning. Ενεργοποιείται με env var σε ΚΑΙ τα 2 .env.
- **Runner systemd migration** (`4b2e74c`) — από manual `./run.sh`
  σε systemd-managed service με `Restart=on-failure` +
  `RestartSec=10`. `tools/migrate_runner_to_systemd.sh` automation.
- **Real-time sync** (Korifi side) — auto_sync_after_update +
  auto_unsync_after_delete στο students/teachers routers, ώστε
  edits/deletes να pushed στο EduScheduler χωρίς manual sync click.

**Tests** — από 0 σε **99 unit tests passing**:

| Suite | Tests | Coverage |
|---|---|---|
| `test_auth_middleware.py` | 14 | Bearer auth + Sec-Fetch-Site bypass |
| `test_lesson_importer.py` | 23 | CSV parsing, lookups, transaction |
| `test_template_loader.py` | 14 | Discovery, preview, apply, idempotency |
| `test_solution_metrics.py` | 17 | Each comparison metric + winners |
| `test_solver_constraints.py` | 10 | E2E for Phase-3a constraints |
| `test_distribution_helper.py` | 17 | Splits + label rendering |
| `test_timetable_view_days.py` | 4 | Σάββατο visibility regression |

Pytest infra in EduScheduler with conftest.py + minimal_app fixture.
Korifi side: 6 tests in `tests/integrations/test_eds_auth_headers.py`.
Pytest must be installed in `korifi-crm-v2-api-1` for those:
`docker exec korifi-crm-v2-api-1 pip install pytest`.

**Known operational quirks**

- Tests **not** copied into the production Docker image — they live
  in the repo but `Dockerfile` only `COPY backend/ frontend/`. To run
  in CI/dev: `docker cp tests <container>:/app/`.
- Cache-buster strategy: every UI commit bumps `?v=N` in
  `frontend/index.html`. Currently `v=11`. The user must hard-refresh
  (`Ctrl+Shift+R`) to fetch the new index.html.
- Regenerate route depends on `is_locked=TRUE` slots in source
  solution — returns 400 with friendly message if none.

### 2026-05-07 — Solver overhaul (silent-drop fixes + parking lot + 4 new constraints)

**Phase 1 — Silent-drop bugs (commit `1ff8383`)**

- `_validate_data` πλέον ανιχνεύει lessons που ο solver θα παρέλειπε
  σιωπηλά: εκείνα που έχουν `classroom_id` σε διαγραμμένη αίθουσα ή
  `subject.requires_special_room` χωρίς ταυτιζόμενο classroom, ή block
  μεγαλύτερο από τη μέρα. Επιστρέφει φιλικό μήνυμα με τα labels
  (subject, class) και τον λόγο.
- `cp_model.UNKNOWN` πλέον mappάρεται σε νέο status `"timeout"` με
  actionable οδηγίες αντί για το παλιό γενικό `"error"`. Επίσης το
  `infeasible` παίρνει χρηστική περιγραφή.

**Phase 2 — Parking lot (commits `67fa5a6`, `36d9e8d`)**

- Νέα Alembic migration `a1b2c3d4e5f6_parking_lot_unplaced_slots`:
  - `timetable_slots.day_of_week / period_id / classroom_id` γίνονται
    NULLable
  - νέο `is_unplaced BOOLEAN NOT NULL DEFAULT FALSE`
  - νέο `unplaced_reason VARCHAR(500)`
  - new check constraint `ck_slot_placement_consistent` που εξασφαλίζει
    την invariant: είτε όλα τα 3 placement cols είναι NULL με
    `is_unplaced=TRUE`, είτε όλα set με `is_unplaced=FALSE`
- Νέο πεδίο `mode` στο `SolverRequest`: `"strict"` (default,
  AddExactlyOne — INFEASIBLE αν δεν χωράνε όλα) ή `"permissive"`
  (κάθε block παίρνει `placed` BoolVar με ποινή 100k για unplaced —
  ο solver προσπαθεί να βάλει όλα, αλλά αφήνει στο parking ό,τι δεν
  χωράει).
- `SolverResult.unplaced` και `SolverStatusResponse.placed_count`/
  `unplaced_count` εκθέτουν τα stats.
- `update_solution_slot` flips `is_unplaced=FALSE` όταν ένα parking
  slot σύρεται στο grid (απαιτεί `classroom_id` για συνέπεια του
  check constraint).
- Frontend:
  - generate.js: select `Strict / Permissive` με επεξήγηση + stats
    panel που δείχνει placed vs parking-lot count
  - timetable.js: νέο parking-lot panel κάτω από το grid με draggable
    cards που χρησιμοποιούν το υπάρχον drag/drop pipeline
  - timetable-grid.js: φιλτράρει `is_unplaced=true` rows από το grid
    (single source of truth — το parking lot είναι το panel)
- Dockerfile: COPY `alembic/` + `alembic.ini` ώστε `alembic upgrade
  head` να τρέχει inside container.

**Phase 3a — Constraint correctness + 4 new soft types (commit `b8b0802`)**

Bug fix: τα προηγούμενα `_soft_min_teacher_gaps` και
`_soft_min_class_gaps` είχαν broken logic — πρόσθεταν penalty terms
που **πάντα** ίσχυαν, ανεξάρτητα από το αν υπήρχε πραγματικό gap. Στη
θέση τους clean block-counting approach μέσω 2 helpers:

- `_build_busy_indicators(days, owner_lessons_map)` — για κάθε
  (owner, day, period) BoolVar που είναι 1 iff κάποιο lesson του owner
  τρέχει εκεί. Reusable για teacher / class / κλπ.
- `_count_blocks_per_day(busy, owner, day, n_periods, label)` — μετράει
  πόσα ξεχωριστά consecutive runs έχει ο owner. Penalty =
  `max(0, blocks - 1) × weight`.

4 νέα soft constraints (μέσω του υπάρχοντος JSON-rule pattern):

| `rule_type` | Τι κάνει |
|---|---|
| `no_late_day` | Penalty για διδασκαλία μετά από `max_period_index` (scope: class / teacher / all) |
| `teacher_preferred_days` | Penalty όταν ο καθηγητής διδάσκει εκτός των `days[]` whitelist |
| `consecutive_blocks_preference` | Bonus για 2 διαδοχικά blocks αντί για 2 σκόρπια 1ωρα (όταν δεν υπάρχει explicit distribution) |
| `class_compactness` | Penalty για κάθε ημέρα παραπάνω από το γεωμετρικά αναγκαίο `ceil(total/n_periods)` |

### 2026-05-06 — Alembic migrations introduced

- commit `fa8d556`: εισαγωγή Alembic για versioned schema migrations.
  Πριν, schema οριζόταν αποκλειστικά από SQLAlchemy models — οποιαδήποτε
  αλλαγή απαιτούσε manual ALTER ή drop+recreate.
- baseline migration `377b9423f40e_baseline_schema_2026_05_06`.

### 2026-05-06 — Path C: Korifi ↔ EduScheduler integration

Δες `/home/coolman/korifi-crm-v2/docs/INTEGRATION.md` για την πλήρη
ιστορία (Phases 0–5). Από EduScheduler πλευρά:

- backend joined the external `korifi-integration` Docker network ώστε
  το korifi-api/web/mcp/telegram-bot να μπορούν να καλέσουν
  `http://edscheduler-backend:8000`.
- read-only timetable endpoints για το korifi UI (PDF, email, daily
  schedule).
- entity_crosswalk integration: korifi student/teacher IDs αντιστοιχούν
  σε edscheduler IDs μέσω central crosswalk table στο korifi DB.
