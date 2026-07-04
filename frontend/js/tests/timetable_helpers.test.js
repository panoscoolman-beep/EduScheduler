/**
 * Unit tests for frontend/js/views/timetable_helpers.js — run with the Node
 * built-in test runner: `node --test frontend/js/tests/`.
 *
 * This is the EduScheduler frontend's first JS test harness; it gives the
 * timetable refactor a regression net for its pure data logic before the
 * larger DOM/modal extraction.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');

const H = require('../views/timetable_helpers.js');

test('uniqueValues: distinct truthy values, first-seen order', () => {
    const slots = [
        { class_name: 'A' }, { class_name: 'B' }, { class_name: 'A' },
        { class_name: null }, { class_name: '' },
    ];
    assert.deepEqual(H.uniqueValues(slots, 'class_name'), ['A', 'B']);
});

test('uniqueValues: empty / null input', () => {
    assert.deepEqual(H.uniqueValues([], 'class_name'), []);
    assert.deepEqual(H.uniqueValues(null, 'class_name'), []);
});

test('buildStudentLabelMaps: maps + Greek-collated sorted names', () => {
    const students = [
        { id: 1, last_name: 'Παπά', first_name: 'Νίκος', class_ids: [10, 11] },
        { id: 2, last_name: 'Αλ', first_name: 'Μαρία', class_ids: [] },
    ];
    const { classIdsByLabel, idByLabel, sortedNames } = H.buildStudentLabelMaps(students);
    assert.deepEqual([...classIdsByLabel.get('Παπά Νίκος')], [10, 11]);
    assert.equal(idByLabel.get('Αλ Μαρία'), 2);
    assert.deepEqual(sortedNames, ['Αλ Μαρία', 'Παπά Νίκος']);
});

test('buildStudentLabelMaps: empty input', () => {
    const r = H.buildStudentLabelMaps(null);
    assert.equal(r.sortedNames.length, 0);
    assert.equal(r.classIdsByLabel.size, 0);
});

test('teacherIdByName: only slots carrying both name and id', () => {
    const slots = [
        { teacher_name: 'Α', teacher_id: 5 },
        { teacher_name: 'Β' },               // no id → skipped
        { teacher_id: 9 },                    // no name → skipped
    ];
    const m = H.teacherIdByName(slots);
    assert.equal(m.get('Α'), 5);
    assert.equal(m.has('Β'), false);
    assert.equal(m.size, 1);
});

test('resolveExportParams: teacher / student / none', () => {
    const tById = new Map([['Α', 5]]);
    const sById = new Map([['Παπά Νίκος', 2]]);
    assert.equal(H.resolveExportParams('teacher', 'all', 1, tById, sById), null);
    assert.equal(H.resolveExportParams('teacher', 'Α', 7, tById, sById),
                 'solution_id=7&teacher_id=5');
    assert.equal(H.resolveExportParams('student', 'Παπά Νίκος', 7, tById, sById),
                 'solution_id=7&student_id=2');
    assert.equal(H.resolveExportParams('class', 'Α', 7, tById, sById), null);
    assert.equal(H.resolveExportParams('teacher', 'Unknown', 7, tById, sById), null);
});

test('countLockedSlots: locked and not in the parking lot', () => {
    const slots = [
        { is_locked: true, is_unplaced: false },
        { is_locked: true, is_unplaced: true },   // parking lot → excluded
        { is_locked: false, is_unplaced: false },
    ];
    assert.equal(H.countLockedSlots(slots), 1);
    assert.equal(H.countLockedSlots([]), 0);
});

test('esc: escapes &, <, > and coerces null/number', () => {
    assert.equal(H.esc('a<b>&c'), 'a&lt;b&gt;&amp;c');
    assert.equal(H.esc(null), '');
    assert.equal(H.esc(undefined), '');
    assert.equal(H.esc(5), '5');
});

test('buildCompareResultHtml: empty metrics -> empty-state line', () => {
    assert.match(H.buildCompareResultHtml({ metrics: [] }), /Δεν επιστράφηκαν metrics/);
    assert.match(H.buildCompareResultHtml({}), /Δεν επιστράφηκαν metrics/);
});

test('buildCompareResultHtml: metrics table with starred + highlighted winner', () => {
    const result = {
        metrics: [
            { name: 'Sol A', solution_id: 1, score: 100, placed_count: 50, unplaced_count: 0 },
            { name: 'Sol B', solution_id: 2, score: 120, placed_count: 48, unplaced_count: 2 },
        ],
        winners: { score: 1, placed_count: 1 },
    };
    const html = H.buildCompareResultHtml(result);
    assert.match(html, /Σκορ \(penalty\)/);   // metric label rendered
    assert.match(html, /Sol A/);               // header cell
    assert.match(html, /⭐/);                   // winner starred
    assert.match(html, /D1FAE5/);              // winner cell highlighted
});

test('buildSubstituteResultHtml: empty affected slots names the day', () => {
    const html = H.buildSubstituteResultHtml({ affected_slots: [] }, 'Τρίτη');
    assert.match(html, /δεν έχει προγραμματισμένα/);
    assert.match(html, /Τρίτη/);
});

test('buildSubstituteResultHtml: affected slot with candidates + stats', () => {
    const data = {
        affected_slots: [{
            subject_name: 'Άλγεβρα', class_name: 'Β2', period_name: '1η', classroom_name: 'Α1',
            candidates: [{ name: 'Νίκος', score: 9, reasons: ['διαθέσιμος', 'ίδιο μάθημα'] }],
            reschedule_options: [{ day_of_week: 1, period_name: '3η' }],
        }],
        stats: { affected_count: 1, with_candidates: 1 },
    };
    const html = H.buildSubstituteResultHtml(data, 'Δευτέρα');
    assert.match(html, /Άλγεβρα/);
    assert.match(html, /Νίκος/);
    assert.match(html, /score 9/);
    assert.match(html, /Σύνολο μαθημάτων/);
});

test('buildSubstituteResultHtml: slot with no candidates shows fallback', () => {
    const data = {
        affected_slots: [{
            subject_name: 'X', class_name: 'Y', period_name: 'Z', classroom_name: 'W',
            candidates: [], reschedule_options: [],
        }],
        stats: { affected_count: 1, with_candidates: 0 },
    };
    const html = H.buildSubstituteResultHtml(data, 'Δευτέρα');
    assert.match(html, /Κανείς διαθέσιμος/);
    assert.match(html, /Καμία ελεύθερη ώρα/);
});

test('hexToRgba: parses #RRGGBB to rgba() with alpha (default 1)', () => {
    assert.equal(H.hexToRgba('#FF8800', 0.15), 'rgba(255, 136, 0, 0.15)');
    assert.equal(H.hexToRgba('#000000'), 'rgba(0, 0, 0, 1)');
});

test('buildParkingLotHtml: cards with subject + reason, pluralised header', () => {
    const html = H.buildParkingLotHtml([
        { id: 7, subject_name: 'Άλγεβρα', class_name: 'Β2', teacher_name: 'Νίκος',
          subject_color: '#3366CC', unplaced_reason: 'no room' },
        { id: 8, subject_name: 'Έκθεση', class_name: 'Α1' },
    ]);
    assert.match(html, /Parking Lot — 2/);
    assert.match(html, /ώρες δεν τοποθετήθηκαν/);   // plural
    assert.match(html, /Άλγεβρα/);
    assert.match(html, /data-slot-id="7"/);
    assert.match(html, /no room/);
});

test('buildParkingLotHtml: single slot uses the singular header', () => {
    const html = H.buildParkingLotHtml([{ id: 1, subject_name: 'X', class_name: 'Y' }]);
    assert.match(html, /Parking Lot — 1/);
    assert.match(html, /ώρα δεν τοποθετήθηκε/);     // singular
});

// ---------------------------------------------------------------------------
// Νέοι builders (2026-07): ελεύθερες αίθουσες, diff λύσεων, αναφορά ποιότητας
// ---------------------------------------------------------------------------

const FR_PERIODS = [
    { id: 11, start_time: '16:00', end_time: '16:50', is_break: false },
    { id: 12, start_time: '17:00', end_time: '17:50', is_break: false },
    { id: 13, start_time: '17:50', end_time: '18:00', is_break: true },
];

test('buildFreeRoomsHtml: free rooms per cell, occupied excluded, breaks skipped', () => {
    const slots = [
        { day_of_week: 0, period_id: 11, classroom_name: 'Αίθουσα 1', is_unplaced: false },
        { day_of_week: 0, period_id: 11, classroom_name: 'Αίθουσα 2', is_unplaced: false },
        { day_of_week: 1, period_id: 12, classroom_name: 'Αίθουσα 1', is_unplaced: false },
        { day_of_week: null, period_id: null, classroom_name: 'Αίθουσα 2', is_unplaced: true },
    ];
    const rooms = [{ name: 'Αίθουσα 1' }, { name: 'Αίθουσα 2' }, { name: 'Εργαστήριο' }];
    const html = H.buildFreeRoomsHtml(slots, FR_PERIODS, 5, rooms);
    // Δευτέρα 16:00: μόνο το Εργαστήριο ελεύθερο (1/3).
    assert.match(html, /1\/3/);
    assert.match(html, /Εργαστήριο/);
    // Το διάλειμμα (is_break) δεν εμφανίζεται ως γραμμή.
    assert.ok(!html.includes('17:50–18:00'));
    // Κελί χωρίς κανένα μάθημα: όλα ελεύθερα (3/3).
    assert.match(html, /3\/3/);
});

test('buildFreeRoomsHtml: escapes room names', () => {
    const html = H.buildFreeRoomsHtml([], FR_PERIODS, 5, [{ name: '<b>Κακό</b>' }]);
    assert.ok(!html.includes('<b>Κακό</b>'));
    assert.match(html, /&lt;b&gt;Κακό&lt;\/b&gt;/);
});

test('buildDiffResultHtml: moved/added/removed sections + load table with delta', () => {
    const html = H.buildDiffResultHtml({
        base: { id: 1, name: 'Πριν' }, other: { id: 2, name: 'Μετά' },
        unchanged_count: 4,
        moved: [{ lesson: 'Άλγεβρα (Β1)', teacher: 'Νίκος',
                  from: { day_name: 'Τρίτη', period_name: '2η', room: 'Α1' },
                  to: { day_name: 'Πέμπτη', period_name: '3η', room: '' } }],
        added: [], removed: [],
        teacher_load: [
            { teacher: 'Νίκος', base_hours: 3, other_hours: 4, delta: 1 },
            { teacher: 'Μαρία', base_hours: 2, other_hours: 2, delta: 0 },
        ],
    });
    assert.match(html, /Μετακινήθηκαν \(1\)/);
    assert.match(html, /Άλγεβρα \(Β1\)/);
    assert.match(html, /Τρίτη 2η/);
    assert.match(html, /4 ώρες έμειναν ως είχαν/);
    assert.match(html, /\+1/);           // delta του Νίκου
    assert.ok(!html.match(/Μαρία/));     // αμετάβλητος φόρτος δεν εμφανίζεται
});

test('buildDiffResultHtml: no differences → clean message', () => {
    const html = H.buildDiffResultHtml({
        base: { id: 1, name: 'A' }, other: { id: 2, name: 'B' },
        unchanged_count: 9, moved: [], added: [], removed: [], teacher_load: [],
    });
    assert.match(html, /Καμία διαφορά/);
});

test('buildViolationsHtml: badges, named gaps and late slots', () => {
    const html = H.buildViolationsHtml({
        solution: { id: 1, name: 'Λ', score: 12 },
        teacher_gaps: [{ teacher: 'Νίκος', day: 0, day_name: 'Δευτέρα', gap_periods: ['2η'] }],
        late_slots: [{ day: 1, day_name: 'Τρίτη', period_name: '7η', time: '20:00–20:50',
                       subject: 'Φυσική', class_name: 'Γ1', teacher: 'Μαρία' }],
        workload: [{ teacher: 'Νίκος', hours: 12 }],
        summary: { gap_total: 1, late_total: 1, workload_stddev: 1.5 },
    });
    assert.match(html, /Κενά καθηγητών: 1/);
    assert.match(html, /Νίκος<\/b> — Δευτέρα/);
    assert.match(html, /Φυσική/);
    assert.match(html, /σ φόρτου: 1.5/);
});

test('buildViolationsHtml: clean solution message', () => {
    const html = H.buildViolationsHtml({
        solution: { id: 1, name: 'Λ', score: 0 },
        teacher_gaps: [], late_slots: [],
        workload: [{ teacher: 'Νίκος', hours: 5 }],
        summary: { gap_total: 0, late_total: 0, workload_stddev: 0 },
    });
    assert.match(html, /καθαρή λύση/);
});

// ---------------------------------------------------------------------------
// buildFeasibilityHtml — «γιατί δεν βγαίνει;» (2026-07)
// ---------------------------------------------------------------------------

test('buildFeasibilityHtml: infeasible shows errors, warnings, suggestions', () => {
    const html = H.buildFeasibilityHtml({
        feasible: false,
        errors: ['Δεν επαρκούν τα slots: χρειάζονται 40 αλλά υπάρχουν 30'],
        warnings: ['Καθηγητής Νικολάου: φόρτος 18/20 — οριακά'],
        suggestions: ['Πρόσθεσε αίθουσα ή λιγόστεψε ώρες.'],
        stats: { total_periods_needed: 40, total_slots_available: 30, load_factor: 1.33,
                 total_lessons: 12, total_teachers: 4, total_classes: 3 },
    });
    assert.match(html, /Δεν βγαίνει/);
    assert.match(html, /Σίγουρα προβλήματα \(1\)/);
    assert.match(html, /Πιθανά προβλήματα \(1\)/);
    assert.match(html, /Τι να κάνεις/);
    assert.match(html, /Πρόσθεσε αίθουσα/);
    assert.match(html, /40 \/ 30/);
});

test('buildFeasibilityHtml: feasible with no warnings shows green all-clear', () => {
    const html = H.buildFeasibilityHtml({
        feasible: true, errors: [], warnings: [], suggestions: [],
        stats: { total_periods_needed: 20, total_slots_available: 60, load_factor: 0.33 },
    });
    assert.match(html, /✅ Εφικτό/);
    assert.match(html, /Όλα τα checks πέρασαν/);
    assert.ok(!/Τι να κάνεις/.test(html));
});

test('buildFeasibilityHtml: escapes error text', () => {
    const html = H.buildFeasibilityHtml({
        feasible: false, errors: ['<script>x</script>'], warnings: [], suggestions: [], stats: {},
    });
    assert.ok(!html.includes('<script>x'));
    assert.match(html, /&lt;script&gt;/);
});
