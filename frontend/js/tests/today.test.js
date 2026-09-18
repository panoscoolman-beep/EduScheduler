/**
 * 📱 «Σήμερα»: ομαδοποίηση Τώρα/Ακολουθεί/Αργότερα, φίλτρα, HTML.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const T = require('../views/today_helpers.js');

const P = [
    { id: 1, start_time: '9:00', end_time: '10:00' },     // χωρίς μηδενικό — σωστή σύγκριση
    { id: 2, start_time: '16:00', end_time: '17:00' },
    { id: 3, start_time: '17:00', end_time: '18:00' },
    { id: 4, start_time: '18:00', end_time: '19:00' },
];
const S = [
    { day_of_week: 1, period_id: 2, subject_name: 'ΦΥΣΙΚΗ', class_name: 'Β2', teacher_name: 'Τ1', classroom_name: 'Αίθ 2' },
    { day_of_week: 1, period_id: 2, subject_name: 'ΧΗΜΕΙΑ', class_name: 'Γ1', teacher_name: 'Τ2', classroom_name: 'Αίθ 1' },
    { day_of_week: 1, period_id: 3, subject_name: 'ΒΙΟΛΟΓΙΑ', class_name: 'Α1', teacher_name: 'Τ1', classroom_name: 'Αίθ 1' },
    { day_of_week: 1, period_id: 4, subject_name: '<b>X', class_name: 'Α2', teacher_name: 'Τ2', classroom_name: 'Αίθ 3' },
    { day_of_week: 1, period_id: 1, subject_name: 'ΠΡΩΙ', class_name: 'Α', teacher_name: 'Τ3', classroom_name: 'Αίθ 1' },
    { day_of_week: 1, period_id: 3, is_unplaced: true, subject_name: 'Παλέτα', teacher_name: 'Τ9' },
    { day_of_week: 2, period_id: 2, subject_name: 'ΑΛΛΗ ΜΕΡΑ', teacher_name: 'Τ1', classroom_name: 'Αίθ 1' },
];

test('edsDay: Κυριακή=6, Δευτέρα=0', () => {
    assert.equal(T.edsDay(new Date(2026, 8, 20)), 6);   // Κυριακή 20/9/2026
    assert.equal(T.edsDay(new Date(2026, 8, 21)), 0);   // Δευτέρα
    assert.equal(T.nowHHMM(new Date(2026, 8, 21, 7, 5)), '07:05');
});

test('buildDay: τώρα / ακολουθεί / αργότερα / ολοκληρωμένες', () => {
    const d = T.buildDay(S, P, 1, '16:30');
    assert.equal(d.done, 1);                                           // 9:00 < 16:00 παρ' ότι «9» > «1»
    assert.deepEqual(d.current.items.map(s => s.classroom_name), ['Αίθ 1', 'Αίθ 2']);  // ανά αίθουσα
    assert.equal(d.next.period.id, 3);
    assert.equal(d.next.items.length, 1);                               // όχι η Παλέτα
    assert.deepEqual(d.later.map(g => g.period.id), [4]);
});

test('buildDay: στο όριο της ώρας και μετά το τέλος της μέρας', () => {
    assert.equal(T.buildDay(S, P, 1, '17:00').current.period.id, 3);   // [start, end)
    const late = T.buildDay(S, P, 1, '20:00');
    assert.equal(late.current, null);
    assert.equal(late.next, null);
    assert.equal(late.done, 4);
    assert.ok(T.buildHtml(late).includes('τελείωσαν'));
});

test('buildDay: άλλη μέρα (now=null) → όλα στη σειρά, φίλτρα καθηγητή/αίθουσας', () => {
    const d = T.buildDay(S, P, 1, null);
    assert.deepEqual(d.later.map(g => g.period.id), [1, 2, 3, 4]);
    assert.equal(d.current, null);
    const t1 = T.buildDay(S, P, 1, null, 't:Τ1');
    assert.deepEqual(t1.later.map(g => g.items[0].subject_name), ['ΦΥΣΙΚΗ', 'ΒΙΟΛΟΓΙΑ']);
    const room = T.buildDay(S, P, 1, null, 'r:Αίθ 3');
    assert.equal(room.later.length, 1);
    assert.ok(T.buildDay(S, P, 4, null).empty);
});

test('filterOptions: μοναδικά, ταξινομημένα, χωρίς Παλέτα', () => {
    const o = T.filterOptions(S);
    assert.deepEqual(o.teachers, ['Τ1', 'Τ2', 'Τ3']);
    assert.deepEqual(o.rooms, ['Αίθ 1', 'Αίθ 2', 'Αίθ 3']);
});

test('buildHtml: ετικέτες και escaping', () => {
    const html = T.buildHtml(T.buildDay(S, P, 1, '16:30'));
    assert.ok(html.includes('🟢 Τώρα · 16:00–17:00') && html.includes('⏭ Ακολουθεί · 17:00–18:00'));
    assert.ok(html.includes('&lt;b&gt;X') && !html.includes('<b>X'));
    assert.ok(html.includes('1 ώρες έχουν ήδη ολοκληρωθεί'));
    assert.ok(T.buildHtml(T.buildDay(S, P, 4, null)).includes('Κανένα μάθημα'));
});

// --- smoke: ολόκληρη η σελίδα σε jsdom με ψεύτικο API ---------------------------
const { JSDOM } = require('jsdom');

test('TodayView.render: φορτώνει, φιλτράρει, αλλάζει μέρα, χωρίς localStorage', async () => {
    const dom = new JSDOM('<!DOCTYPE html><body><div id="c"></div></body>');
    global.window = dom.window;
    global.document = dom.window.document;
    global.TodayHelpers = T;
    global.TimetableHelpers = require('../views/timetable_helpers.js');
    global.App = { _currentSolutionId: null };
    const calls = [];
    global.API = {
        solver: {
            listSolutions: async () => [{ id: 5, archived: true }, { id: 7, archived: false }],
            getSolution: async (id) => { calls.push(id); return { id, name: 'ΧΕΙΜΕΡΙΝΟ', slots: S }; },
        },
        periods: { list: async () => P },
    };
    const TodayView = require('../views/today.js');
    const c = document.getElementById('c');
    try {
        await TodayView.render(c);
        assert.deepEqual(calls, [7]);                              // όχι το αρχειοθετημένο
        assert.ok(c.querySelector('#today-title').textContent.includes('Σήμερα'));
        assert.ok(c.textContent.includes('Πρόγραμμα: ΧΕΙΜΕΡΙΝΟ'));
        const sel = c.querySelector('#today-filter');
        assert.equal(sel.querySelectorAll('option').length, 1 + 3 + 3);
        // Πήγαινε σε Τρίτη ώστε να υπάρχουν σίγουρα μαθήματα, με φίλτρο αίθουσας.
        const toTuesday = (1 - T.edsDay(new Date()) + 7) % 7 || 7;
        for (let i = 0; i < toTuesday; i++) c.querySelector('#today-next').click();
        sel.value = 'r:Αίθ 3';
        sel.dispatchEvent(new dom.window.Event('change'));
        const list = c.querySelector('#today-list').textContent;
        assert.ok(list.includes('Αίθ 3') && !list.includes('ΦΥΣΙΚΗ'));
        assert.ok(c.querySelector('#today-title').textContent.includes('Τρίτη'));
    } finally {
        clearInterval(TodayView._timer);
    }
});
