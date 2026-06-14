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
