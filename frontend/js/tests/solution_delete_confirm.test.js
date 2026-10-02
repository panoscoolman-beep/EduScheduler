/**
 * Δημιουργία → Ιστορικό Λύσεων: το 🗑️ ΔΕΝ σβήνει πρόγραμμα με ένα κλικ —
 * πρώτα επιβεβαίωση που λέει ποιο, ότι είναι οριστικό, και προτείνει 📦.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes } = require('./app_harness.js');

function setup() {
    const sols = [
        { id: 7, name: 'Χειμερινό <b>live</b>', status: 'optimal', score: 10, created_at: '2026-09-20T10:00:00Z', archived: false },
        { id: 6, name: 'Δοκιμή', status: 'error', score: null, created_at: '2026-09-19T10:00:00Z', archived: false },
    ];
    const routes = baseRoutes({
        'GET /api/solver/solutions': () => sols,
        'DELETE /api/solver/solutions/*': ({ path: p }) => {
            const id = +p.split('/').pop();
            sols.splice(sols.findIndex(s => s.id === id), 1);
            return { __status: 204 };
        },
    });
    return { routes, sols };
}

const deletes = (app) => app.calls.filter(c => c.method === 'DELETE').map(c => c.path);
const overlayOpen = (app) => app.doc.getElementById('modal-overlay').classList.contains('active');

test('🗑️: κανένα DELETE με ένα κλικ — παράθυρο που ονομάζει το πρόγραμμα', async () => {
    const { routes } = setup();
    const app = await start(routes);
    try {
        await go(app, 'generate', '.del-sol[data-id="7"]');
        app.doc.querySelector('.del-sol[data-id="7"]').click();
        await sleep(app.w, 30);
        assert.deepEqual(deletes(app), []);
        assert.ok(overlayOpen(app));
        const body = app.doc.getElementById('modal-body');
        assert.match(body.textContent, /Χειμερινό <b>live<\/b>/);     // το όνομα, ως κείμενο
        assert.equal(body.querySelector('b b'), null, 'escaped, όχι HTML');
        assert.match(body.textContent, /οριστικά/);
        assert.match(body.textContent, /Δεν αναιρείται/);
        assert.match(body.textContent, /📦 Αρχειοθέτηση/);
        const save = app.doc.getElementById('modal-save');
        assert.match(save.textContent, /Οριστική διαγραφή/);
        assert.ok(save.classList.contains('btn-danger'));

        // Ακύρωση → τίποτα δεν σβήνεται
        app.doc.getElementById('modal-cancel').click();
        await sleep(app.w, 20);
        assert.deepEqual(deletes(app), []);
    } finally { app.close(); }
});

test('🗑️ + «Οριστική διαγραφή» → ένα DELETE του σωστού προγράμματος, η λίστα ανανεώνεται', async () => {
    const { routes } = setup();
    const app = await start(routes);
    try {
        await go(app, 'generate', '.del-sol[data-id="6"]');
        app.doc.querySelector('.del-sol[data-id="6"]').click();
        await waitFor(app.w, () => overlayOpen(app));
        assert.match(app.doc.getElementById('modal-body').textContent, /Δοκιμή/);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => !overlayOpen(app));
        assert.deepEqual(deletes(app), ['/api/solver/solutions/6']);
        await waitFor(app.w, () => !app.doc.querySelector('.del-sol[data-id="6"]'));
        assert.ok(app.doc.querySelector('.del-sol[data-id="7"]'), 'το άλλο πρόγραμμα μένει');
        assert.ok(app.toasts.some(t => /διαγράφηκε/.test(t.message)));
    } finally { app.close(); }
});
