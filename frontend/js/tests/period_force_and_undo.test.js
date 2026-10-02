/**
 * (1) Ώρα με τοποθετημένα μαθήματα → «Διάλειμμα»: ο server απαντά 409 και η
 *     επιβεβαίωση ξαναστέλνει με ?force=true (πριν, το API το αγνοούσε και η
 *     επιβεβαίωση έπεφτε ξανά στο 409).
 * (2) Αναίρεση/Επανάληψη που απαντά 409: τα κουμπιά ↩/↪ φρεσκάρονται, γιατί
 *     ο server μπορεί να σημάνει την εγγραφή ως «παραλείφθηκε».
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes, timetableRoutes } = require('./app_harness.js');

const overlayOpen = (app) => app.doc.getElementById('modal-overlay').classList.contains('active');
const toastTexts = (app) => [...app.doc.querySelectorAll('#toast-container .toast-message')].map(e => e.textContent);

test('Ώρες: «Διάλειμμα» σε ώρα με μαθήματα → 409 → επιβεβαίωση → PUT ?force=true', async () => {
    const periods = [
        { id: 1, name: '1η', short_name: '1η', start_time: '16:00', end_time: '17:00', is_break: false, sort_order: 1 },
        { id: 2, name: '2η', short_name: '2η', start_time: '17:00', end_time: '18:00', is_break: false, sort_order: 2 },
    ];
    const puts = [];
    const routes = baseRoutes({
        'GET /api/periods/': () => periods,
        'PUT /api/periods/*': ({ path: p, search, body }) => {
            puts.push({ path: p, search, body });
            if (body.is_break && !/force=true/.test(search)) {
                return { __status: 409, data: { detail: {
                    code: 'period_in_use', requires_force: true, slots: 3, solutions: 1,
                    message: 'Η ώρα «2η» έχει 3 τοποθετημένα μαθήματα σε 1 πρόγραμμα(τα).' } } };
            }
            return { ...periods.find(x => x.id === +p.split('/').pop()), ...body };
        },
    });
    const app = await start(routes);
    try {
        // Κανονική αλλαγή: ίδιο URL με πριν, χωρίς force
        await go(app, 'periods', '.dt-edit[data-id="1"]');
        app.doc.querySelector('.dt-edit[data-id="1"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-name'));
        app.doc.getElementById('f-name').value = '1η Ώρα';
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => !overlayOpen(app));
        assert.deepEqual(puts.map(x => x.path + x.search), ['/api/periods/1']);

        // Σε διάλειμμα → 409 → «Ναι, αποθήκευση» → ?force=true
        await waitFor(app.w, () => app.doc.querySelector('.dt-edit[data-id="2"]'));
        app.doc.querySelector('.dt-edit[data-id="2"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-break'));
        app.doc.getElementById('f-break').value = 'true';
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => /συγκρούεται/.test(app.doc.getElementById('modal-title').textContent));
        assert.match(app.doc.getElementById('modal-body').textContent, /3 τοποθετημένα μαθήματα/);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => !overlayOpen(app));
        assert.deepEqual(puts.slice(1).map(x => x.path + x.search),
            ['/api/periods/2', '/api/periods/2?force=true']);
        assert.equal(puts[2].body.is_break, true);
        assert.ok(app.toasts.some(t => /Παλέτα/.test(t.message)), 'μήνυμα επιτυχίας');
        await sleep(app.w, 30);

        // Το ίδιο το API: force μόνο όταν ζητηθεί
        await app.G.API.periods.update(1, periods[0]);
        await app.G.API.periods.update(1, periods[0], true);
        assert.deepEqual(puts.slice(-2).map(x => x.path + x.search), ['/api/periods/1', '/api/periods/1?force=true']);
    } finally { app.close(); }
});

test('Αναίρεση που αποτυγχάνει (409): μήνυμα ως κείμενο + φρεσκάρισμα κουμπιών ↩/↪', async () => {
    const { routes, state } = timetableRoutes({
        'POST /api/solver/solutions/*/undo': () => {
            state.undoCalls += 1;
            state.can_undo = 0;          // ο server σημείωσε την εγγραφή «παραλείφθηκε»
            return { __status: 409, data: { detail: 'Η θέση <b>Δευ 1η</b> είναι πιασμένη' } };
        },
    });
    state.can_undo = 1;
    state.can_redo = 0;
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-undo');
        const undo = () => app.doc.getElementById('tt-undo');
        await waitFor(app.w, () => !undo().disabled);
        const summaries = () => app.calls.filter(c => /history-summary$/.test(c.path)).length;
        const before = summaries();
        undo().click();
        await waitFor(app.w, () => toastTexts(app).some(t => /πιασμένη/.test(t)));
        assert.ok(toastTexts(app).includes('Η θέση <b>Δευ 1η</b> είναι πιασμένη'));
        assert.equal(app.doc.querySelector('#toast-container .toast-message b'), null);
        await waitFor(app.w, () => undo().disabled === true);
        assert.ok(summaries() > before, 'ξαναδιαβάστηκε το history-summary');
        assert.equal(undo().title, 'Καμία αλλαγή για αναίρεση');
        assert.equal(state.undoCalls, 1);
    } finally { app.close(); }
});

test('Αναίρεση που πετυχαίνει: το μήνυμα του server ως κείμενο', async () => {
    const { routes, state } = timetableRoutes({
        'POST /api/solver/solutions/*/undo': () => { state.undoCalls += 1; return { message: 'Αναιρέθηκε: <i>Φυσική</i> & Β2' }; },
    });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-undo');
        await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled);
        app.doc.getElementById('tt-undo').click();
        await waitFor(app.w, () => toastTexts(app).some(t => /Αναιρέθηκε/.test(t)));
        assert.ok(toastTexts(app).includes('Αναιρέθηκε: <i>Φυσική</i> & Β2'), toastTexts(app).join(' | '));
        await waitFor(app.w, () => app.doc.getElementById('tt-undo'));
        await sleep(app.w, 30);
    } finally { app.close(); }
});
