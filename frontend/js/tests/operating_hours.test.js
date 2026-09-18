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

test('roomIdForFilter: μόνο στην προβολή μίας αίθουσας', () => {
    const slots = [{ classroom_id: 3, classroom_name: 'Αίθ 3' }, { classroom_id: 4, classroom_name: 'Αίθ 4' }];
    assert.equal(H.roomIdForFilter(slots, 'room', 'Αίθ 4'), 4);
    assert.equal(H.roomIdForFilter(slots, 'room', 'all'), null);
    assert.equal(H.roomIdForFilter(slots, 'teacher', 'Αίθ 4'), null);
    assert.equal(H.roomIdForFilter(slots, 'room', 'Άγνωστη'), null);
});

test('προβολή αίθουσας: το drop στέλνει ρητά αυτή την αίθουσα', async () => {
    const dom = new JSDOM('<!DOCTYPE html><body><div id="grid"></div></body>');
    global.window = dom.window;
    global.document = dom.window.document;
    global.TimetableHelpers = H;
    const sent = [];
    const toasts = [];
    global.API = { solver: { updateSlot: async (sid, slotId, body) => {
        sent.push(body);
        return { slot: { classroom_id: 4, classroom_name: 'Αίθ 4' } };
    } } };
    global.Toast = { success: (m) => toasts.push(m), error: (m) => toasts.push('ERR ' + m) };
    const Grid = require('../components/timetable-grid.js');
    Grid.operatingWindow = null;
    Grid._notifyHistoryChanged = () => {};
    Grid._notifyParkingLotChanged = () => {};
    const slots = [
        { ...SLOT, id: 5, classroom_id: 4, classroom_name: 'Αίθ 4', period_id: 7, day_of_week: 0 },
        { ...SLOT, id: 6, classroom_id: 3, classroom_name: 'Αίθ 3', period_id: 7, day_of_week: 1 },
    ];
    Grid.render('grid', slots, PERIODS, 6, 'room', 'Αίθ 4', 1);
    const cells = document.querySelectorAll('td.droppable-cell');
    assert.ok([...cells].every(td => td.dataset.room === '4'));

    // Κάρτα της Αίθ 3 (από άλλο σημείο) αφήνεται σε κελί της προβολής «Αίθ 4».
    const card = document.createElement('div');
    card.className = 'lesson-card';
    card.dataset.slotId = '6';
    card.dataset.json = JSON.stringify(slots[1]);
    document.body.appendChild(card);
    const target = [...cells].find(td => td.dataset.day === '2' && td.dataset.period === '7');
    await Grid.handleDrop({ preventDefault() {}, target,
        dataTransfer: { getData: () => '6' } }, 1);
    assert.deepEqual(sent, [{ day_of_week: 2, period_id: 7, classroom_id: 4 }]);
    assert.match(toasts[0], /μπήκε στην αίθουσα «Αίθ 4»/);

    // Χωρίς φίλτρο αίθουσας: ΚΑΝΕΝΑ classroom_id (ο server διαλέγει όπως πριν).
    Grid.render('grid', slots, PERIODS, 6, 'class', 'all', 1);
    assert.ok([...document.querySelectorAll('td.droppable-cell')].every(td => td.dataset.room === undefined));
});

test('Σάββατο με δικό του ωράριο: πρωινά κελιά καθημερινών «κλειστά», του Σαββάτου ανοιχτά', () => {
    const dom = new JSDOM('<!DOCTYPE html><body><div id="grid"></div></body>');
    global.window = dom.window;
    global.document = dom.window.document;
    global.TimetableHelpers = H;
    const Grid = require('../components/timetable-grid.js');
    const win = { from: '14:00', to: '22:00', saturday: { from: '08:00', to: '22:00' } };
    assert.equal(H.isCellOpen(PERIODS[0], 0, win), false);     // Δευτέρα 08:00
    assert.equal(H.isCellOpen(PERIODS[0], 5, win), true);      // Σάββατο 08:00
    assert.equal(H.isCellOpen(PERIODS[3], 2, win), true);      // Τετάρτη 14:00

    Grid.operatingWindow = win;
    const satSlot = { ...SLOT, id: 5, day_of_week: 5, period_id: 2 };
    Grid.render('grid', [satSlot], PERIODS, 6, 'class', 'all', 1);
    const rows = [...document.querySelectorAll('tbody tr, table tr')].filter(tr => tr.querySelector('td.period-cell'));
    assert.equal(rows.length, 4);                               // όλες οι ώρες (το Σάββατο τις ανοίγει)
    const firstRow = rows[0];                                   // 1η ώρα 08:00
    assert.equal(firstRow.querySelectorAll('td.closed-cell').length, 5);        // Δευ–Παρ κλειστά
    assert.equal(firstRow.querySelectorAll('td.droppable-cell').length, 1);     // Σάββατο ανοιχτό
    assert.equal(document.querySelectorAll('.period-outside').length, 0);       // κανένα ⏰
    assert.equal(document.querySelectorAll('td.closed-cell .lesson-card').length, 0);

    // Μάθημα σε «κλειστό» κελί καθημερινής: το κελί μένει κανονικό (δεν χάνεται)
    const weekdayMorning = { ...SLOT, id: 9, day_of_week: 1, period_id: 1 };
    Grid.render('grid', [satSlot, weekdayMorning], PERIODS, 6, 'class', 'all', 1);
    const cell = document.querySelector('td.droppable-cell[data-day="1"][data-period="1"]');
    assert.ok(cell && cell.querySelector('[data-slot-id="9"]'));
});
