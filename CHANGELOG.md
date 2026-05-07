# Changelog

Όλες οι σημαντικές αλλαγές του EduScheduler. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
