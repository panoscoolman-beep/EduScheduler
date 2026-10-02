/**
 * Ctrl+Z / Ctrl+Y του Ωρολογίου: δρουν ΜΟΝΟ στο Ωρολόγιο, όχι σε πεδία
 * κειμένου ή με ανοιχτό παράθυρο, και όχι σε άλλη σελίδα (πριν, το Ctrl+Z
 * σε οποιοδήποτε input αναιρούσε σιωπηλά αλλαγή του προγράμματος).
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, timetableRoutes, slot } = require('./app_harness.js');

function key(app, target, k, extra = {}) {
    const ev = new app.w.KeyboardEvent('keydown', { key: k, ctrlKey: true, bubbles: true, cancelable: true, ...extra });
    target.dispatchEvent(ev);
    return ev;
}

async function openTimetable(app) {
    await go(app, 'timetable', '#tt-undo');
    await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled);   // history-summary φορτώθηκε
}

test('Ctrl+Z σε πεδίο άλλης σελίδας: κανονική αναίρεση κειμένου, καμία αναίρεση προγράμματος', async () => {
    const { routes, state } = timetableRoutes();
    const app = await start(routes);
    try {
        await openTimetable(app);
        await go(app, 'students', '[id^="dt-add-"]');
        app.doc.querySelector('[id^="dt-add-"]').click();
        await waitFor(app.w, () => app.doc.querySelector('#modal-body input'));
        const input = app.doc.querySelector('#modal-body input');
        const ev = key(app, input, 'z');
        await sleep(app.w, 60);
        assert.equal(ev.defaultPrevented, false, 'το native text-undo δεν μπλοκάρεται');
        assert.equal(state.undoCalls, 0);
        assert.equal(app.doc.querySelector('#content-area #tt-undo'), null, 'η σελίδα δεν αντικαταστάθηκε');

        // και χωρίς focus σε πεδίο, σε άλλη σελίδα: τίποτα
        app.doc.getElementById('modal-cancel').click();
        key(app, app.doc.body, 'z');
        key(app, app.doc.body, 'y');
        await sleep(app.w, 60);
        assert.equal(state.undoCalls, 0);
        assert.equal(state.redoCalls, 0);
    } finally { app.close(); }
});

test('στο Ωρολόγιο: Ctrl+Z / Ctrl+Y εξακολουθούν να δουλεύουν (εκτός πεδίων/παραθύρων)', async () => {
    const { routes, state } = timetableRoutes();
    const app = await start(routes);
    try {
        await openTimetable(app);
        const ev = key(app, app.doc.body, 'z');
        assert.equal(ev.defaultPrevented, true);
        await waitFor(app.w, () => state.undoCalls === 1);
        await waitFor(app.w, () => app.doc.getElementById('tt-redo') && !app.doc.getElementById('tt-redo').disabled);
        key(app, app.doc.body, 'y');
        await waitFor(app.w, () => state.redoCalls === 1);
        await waitFor(app.w, () => app.doc.getElementById('tt-undo') && !app.doc.getElementById('tt-undo').disabled);

        // Ctrl+Shift+Z = επανάληψη (όπως το Ctrl+Y), ΟΧΙ αναίρεση
        const ev2 = key(app, app.doc.body, 'Z', { shiftKey: true });
        assert.equal(ev2.defaultPrevented, true);
        await waitFor(app.w, () => state.redoCalls === 2);
        assert.equal(state.undoCalls, 1);
        await waitFor(app.w, () => app.doc.getElementById('tt-undo') && !app.doc.getElementById('tt-undo').disabled
            && app.doc.getElementById('palette-search'));

        // Μέσα στην αναζήτηση της Παλέτας: αναίρεση κειμένου, όχι προγράμματος
        const search = app.doc.getElementById('palette-search');
        assert.ok(search, 'η Παλέτα έχει αναζήτηση');
        const ev3 = key(app, search, 'z');
        await sleep(app.w, 60);
        assert.equal(ev3.defaultPrevented, false);
        assert.equal(state.undoCalls, 1);

        // Με ανοιχτό παράθυρο (✏️ μετονομασία): τίποτα πίσω από αυτό
        app.doc.getElementById('tt-rename').click();
        await waitFor(app.w, () => app.doc.getElementById('modal-overlay').classList.contains('active'));
        key(app, app.doc.body, 'z');
        key(app, app.doc.getElementById('f-solution-name'), 'z');
        await sleep(app.w, 60);
        assert.equal(state.undoCalls, 1);
    } finally { app.close(); }
});

test('«Γέμισε τα κενά» που τελειώνει ενώ είσαι σε άλλη σελίδα δεν την αντικαθιστά', async () => {
    const { routes, state } = timetableRoutes({
        'POST /api/solver/regenerate/*': () => ({ solution_id: 8 }),
    });
    state.slots.push(slot(3, { is_unplaced: true, day_of_week: null, period_id: null }));
    const app = await start(routes);
    let finish;
    app.G.TimetableInteractions.pollSolve = () => new Promise(r => { finish = r; });
    try {
        await openTimetable(app);
        app.doc.getElementById('tt-fill').click();
        await waitFor(app.w, () => app.doc.getElementById('fill-name'));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => typeof finish === 'function');
        await go(app, 'students', '[id^="dt-add-"]');
        state.solutions.unshift({ id: 8, name: 'Χειμερινό (συμπλήρωση)', status: 'optimal', created_at: '2026-10-01T10:00:00Z', archived: false, slots: [] });
        finish({ status: 'optimal', solution_id: 8, message: 'Ολοκληρώθηκε (optimal) — 3 μαθήματα τοποθετήθηκαν.' });
        await waitFor(app.w, () => app.toasts.some(t => /Ολοκληρώθηκε/.test(t.message)));
        await sleep(app.w, 60);
        assert.ok(app.doc.querySelector('#content-area [id^="dt-add-"]'), 'μένει η σελίδα Μαθητές');
        assert.equal(app.doc.querySelector('#content-area #tt-undo'), null);
        assert.equal(app.G.App._currentSolutionId, 8, 'το νέο πρόγραμμα ανοίγει στην επόμενη επίσκεψη');
        await go(app, 'timetable', '#tt-solution');
        assert.equal(app.doc.getElementById('tt-solution').value, '8');
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('Ctrl+Shift+Z → επανάληψη, Ctrl+Z → αναίρεση, Ctrl+Shift+Y όπως πριν· μέσα σε πεδίο → τίποτα', async () => {
    const { routes, state } = timetableRoutes();
    const app = await start(routes);
    const ready = () => waitFor(app.w, () => app.doc.getElementById('tt-undo') && !app.doc.getElementById('tt-undo').disabled
        && !app.doc.getElementById('tt-redo').disabled);
    try {
        await openTimetable(app);
        await ready();
        key(app, app.doc.body, 'Z', { shiftKey: true });
        await waitFor(app.w, () => state.redoCalls === 1);
        assert.equal(state.undoCalls, 0);
        await ready();
        key(app, app.doc.body, 'z');
        await waitFor(app.w, () => state.undoCalls === 1);
        assert.equal(state.redoCalls, 1);
        await ready();
        key(app, app.doc.body, 'Y', { shiftKey: true });
        await waitFor(app.w, () => state.redoCalls === 2);
        await ready();
        // Μέσα σε πεδίο κειμένου: ούτε αναίρεση ούτε επανάληψη, και η πληκτρολόγηση μένει ελεύθερη
        const search = app.doc.getElementById('palette-search');
        const evs = [key(app, search, 'Z', { shiftKey: true }), key(app, search, 'z'), key(app, search, 'y')];
        await sleep(app.w, 60);
        assert.deepEqual(evs.map(e => e.defaultPrevented), [false, false, false]);
        assert.equal(state.undoCalls, 1);
        assert.equal(state.redoCalls, 2);
    } finally { app.close(); }
});
