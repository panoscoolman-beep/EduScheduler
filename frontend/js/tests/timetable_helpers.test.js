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
