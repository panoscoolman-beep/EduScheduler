/**
 * Ωράριο λειτουργίας στο πλέγμα: TimetableHelpers.visiblePeriods + render
 * του TimetableGrid (jsdom) — άδειες ώρες εκτός ωραρίου κρύβονται, ώρες με
 * μάθημα φαίνονται με σήμανση ⏰.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');

const H = require('../views/timetable_helpers.js');

const PERIODS = [
    { id: 1, short_name: '1η', start_time: '08:00', end_time: '09:00', is_break: false },
    { id: 2, short_name: '2η', start_time: '09:00', end_time: '10:00', is_break: false },
    { id: 9, short_name: 'Δ', start_time: '13:50', end_time: '14:00', is_break: true },
    { id: 7, short_name: '7η', start_time: '14:00', end_time: '15:00', is_break: false },
    { id: 8, short_name: '14η', start_time: '21:00', end_time: '22:00', is_break: false },
];
const W = { from: '14:00', to: '22:00' };
const SLOT = { id: 5, period_id: 2, day_of_week: 5, is_unplaced: false, lesson_id: 1,
               subject_name: 'Άλγεβρα', class_name: 'Β2', teacher_name: 'Καθ', classroom_name: 'Α1' };

test('visiblePeriods: κρύβει άδειες ώρες εκτός ωραρίου, κρατά όσες έχουν μάθημα', () => {
    const teaching = PERIODS.filter(p => !p.is_break);
    const res = H.visiblePeriods(teaching, W, [SLOT, { ...SLOT, id: 6, period_id: 1, is_unplaced: true }]);
    assert.deepEqual(res.periods.map(p => p.id), [2, 7, 8]);   // η 1η: μόνο ώρα Παλέτας → κρυφή
    assert.deepEqual([...res.outside], [2]);
    assert.deepEqual(H.visiblePeriods(teaching, null, []).periods.map(p => p.id), [1, 2, 7, 8]);
    assert.deepEqual(H.visiblePeriods(teaching, { from: '', to: '' }, []).periods.length, 4);
});

test('TimetableGrid.render: γραμμές μόνο εντός ωραρίου + σήμανση ⏰ για ώρα με μάθημα', () => {
    const dom = new JSDOM('<!DOCTYPE html><body><div id="grid"></div></body>');
    global.window = dom.window;
    global.document = dom.window.document;
    global.TimetableHelpers = H;
    const Grid = require('../components/timetable-grid.js');
    Grid.operatingWindow = W;
    Grid.render('grid', [SLOT], PERIODS, 6, 'class', 'all', 1);
    const labels = [...document.querySelectorAll('td.period-cell')].map(td => td.textContent.replace(/\s+/g, ' ').trim());
    assert.equal(labels.length, 3);
    assert.match(labels[0], /^2η ⏰ 09:00-10:00$/);
    assert.match(labels[1], /^7η 14:00-15:00$/);
    const outside = document.querySelector('td.period-cell.period-outside');
    assert.match(outside.getAttribute('title'), /Εκτός ωραρίου/);

    Grid.operatingWindow = null;                                // χωρίς ωράριο: όλες
    Grid.render('grid', [SLOT], PERIODS, 6, 'class', 'all', 1);
    assert.equal(document.querySelectorAll('td.period-cell').length, 4);
    assert.equal(document.querySelectorAll('.period-outside').length, 0);
});
