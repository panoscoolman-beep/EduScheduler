/**
 * Ώρες του server σε ώρα Ελλάδας (G2-15 / G3-14). Ο server κρατά UTC: τα
 * προγράμματα έρχονται με ρητό +00:00, δημοσιεύσεις/ιστορικό ως ISO χωρίς
 * ζώνη. Πριν, οι δεύτερες εμφανίζονταν 2–3 ώρες νωρίτερα. Οι έλεγχοι δεν
 * εξαρτώνται από τη ζώνη ώρας του μηχανήματος που τρέχει τα tests.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes, timetableRoutes } = require('./app_harness.js');

const SUMMER = /2\/10\/2026,\s6:49:03\sμ\.μ\./;      // 15:49:03 UTC → 18:49:03 EEST
const WINTER = /15\/1\/2026,\s12:05:00\sμ\.μ\./;     // 10:05:00 UTC → 12:05:00 EET

test('Δημιουργία: ημερομηνίες προγραμμάτων σε ώρα Ελλάδας, χωρίς «Invalid Date»', async () => {
    const sols = [
        { id: 7, name: 'Χειμερινό', status: 'optimal', score: 1, created_at: '2026-10-02T15:49:03.123456+00:00' },
        { id: 6, name: 'Παλιό', status: 'feasible', score: 2, created_at: '2026-01-15T10:05:00' },
        { id: 5, name: 'Χωρίς ημερομηνία', status: 'error', score: null, created_at: null },
        { id: 4, name: 'Χαλασμένη', status: 'error', score: null, created_at: 'garbage' },
    ];
    const app = await start(baseRoutes({ 'GET /api/solver/solutions': () => sols }));
    try {
        await go(app, 'generate', '.del-sol[data-id="4"]');
        const cell = (id) => app.doc.querySelector(`.del-sol[data-id="${id}"]`).closest('tr').cells[3].textContent.trim();
        assert.match(cell(7), SUMMER);        // ήδη με +00:00: όχι διπλή μετατόπιση
        assert.match(cell(6), WINTER);        // χωρίς ζώνη = UTC
        assert.equal(cell(5), '—');
        assert.equal(cell(4), '—');
        const opts = [...app.doc.querySelectorAll('#gen-warmstart option')].map(o => o.textContent);
        assert.ok(opts.some(t => /^Χειμερινό \(/.test(t) && SUMMER.test(t)), opts.join(' | '));
        assert.ok(opts.some(t => /^Παλιό \(/.test(t) && WINTER.test(t)), opts.join(' | '));
        assert.doesNotMatch(app.doc.getElementById('content-area').textContent, /Invalid Date/);
    } finally { app.close(); }
});

test('Πίνακας Ελέγχου: «Τελευταίο Πρόγραμμα» σε ώρα Ελλάδας· άκυρη ημερομηνία = κενό', async () => {
    let created = '2026-10-02T15:49:03+00:00';
    const routes = baseRoutes({
        'GET /api/solver/solutions': () => [{ id: 7, name: 'Χειμερινό', status: 'optimal', created_at: created }],
    });
    const app = await start(routes);
    try {
        await waitFor(app.w, () => app.doc.getElementById('view-latest'));
        assert.match(app.doc.getElementById('content-area').textContent, SUMMER);
        created = 'garbage';
        await go(app, 'dashboard', '#view-latest');
        assert.doesNotMatch(app.doc.getElementById('content-area').textContent, /Invalid Date/);
    } finally { app.close(); }
});

test('Ωρολόγιο: 🕘 Ιστορικό και 📢 Δημοσίευση δείχνουν ώρα Ελλάδας (ο server στέλνει UTC χωρίς ζώνη)', async () => {
    const { routes } = timetableRoutes({
        'GET /api/solver/solutions/*/history': () => ({ items: [
            { id: 2, operation: 'move', operation_label: 'Μετακίνηση', undone: false, lesson: 'Φυσική · Β2',
              from: 'Δευ 1η', to: 'Τρι 2η', performed_at: '2026-10-02T15:49:03.123456' },
        ] }),
        'GET /api/publications/preview/*': () => ({
            first: false, affected: 1, unplaced: 0,
            teachers: [{ teacher_id: 21, teacher: 'Νικολάου', email: 'n@x.gr', changed: true, hours: 2, message: 'm',
                         changes: { moved: [{}], added: [], removed: [] } }],
            previous: { id: 3, solution_name: 'Χειμερινό', published_at: '2026-01-15T10:05:00' },
        }),
    });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-history');
        app.doc.getElementById('tt-history').click();
        await waitFor(app.w, () => app.doc.querySelector('#modal-body .hist-undo-to'));
        const body = app.doc.getElementById('modal-body').textContent;
        assert.match(body, /10-02 18:49/);
        assert.doesNotMatch(body, /15:49/);
        app.doc.getElementById('modal-close').click();

        app.doc.getElementById('tt-publish').click();
        await waitFor(app.w, () => app.doc.querySelector('#modal-body .pub-mail'));
        assert.match(app.doc.getElementById('modal-body').textContent, /«Χειμερινό», 2026-01-15 12:05/);
        await sleep(app.w, 20);
    } finally { app.close(); }
});
