/**
 * «Μετατόπιση ωρών»: πρώτα dry_run (καμία αλλαγή) με τα πλήθη στην επιβεβαίωση
 * — «Ν ώρες θα πάνε στην Παλέτα, Μ κωλύματα χάνονται οριστικά» — και μετά η
 * πραγματική μετατόπιση με τις ίδιες παραμέτρους. Full-app jsdom, ψεύτικο backend.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, waitFor, baseRoutes } = require('./app_harness.js');

const overlayOpen = (app) => app.doc.getElementById('modal-overlay').classList.contains('active');

test('Μετατόπιση ωρών: dry_run → πλήθη στην επιβεβαίωση → «🕐 Μετατόπιση» με τις ίδιες παραμέτρους', async () => {
    const posts = [];
    const counts = { availability_moved: 4, availability_dropped: 2, slots_moved: 10, slots_unplaced: 3 };
    const routes = baseRoutes({
        'POST /api/terms/*/shift-times': ({ body, search }) => {
            posts.push({ body, search });
            return /dry_run=true/.test(search) ? { status: 'ok', dry_run: true, ...counts } : { status: 'ok', ...counts };
        },
    });
    const app = await start(routes);
    try {
        await go(app, 'terms', 'button[data-act="shift"]');
        app.doc.querySelector('button[data-act="shift"]').click();
        await waitFor(app.w, () => app.doc.getElementById('shift-offset'));
        app.doc.getElementById('shift-offset').value = '-2';
        app.doc.getElementById('shift-sols').checked = true;
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => /θα πάνε στην Παλέτα/.test(app.doc.getElementById('modal-body').textContent));
        // Μόνο dry_run μέχρι εδώ — τίποτα δεν μετατοπίστηκε
        assert.deepEqual(posts, [{ body: { offset: -2, shift_solutions: true }, search: '?dry_run=true' }]);
        const body = app.doc.getElementById('modal-body').textContent;
        assert.match(body, /3 ώρες θα πάνε στην Παλέτα, 2 κωλύματα χάνονται οριστικά/);
        assert.match(body, /Χειμ κατά -2 ώρες/);
        const save = app.doc.getElementById('modal-save');
        assert.equal(save.textContent, '🕐 Μετατόπιση');
        assert.equal(save.disabled, false);
        save.click();
        await waitFor(app.w, () => posts.length === 2);
        assert.deepEqual(posts[1], { body: { offset: -2, shift_solutions: true }, search: '' });
        await waitFor(app.w, () => !overlayOpen(app));
        assert.ok(app.toasts.some(t => t.type === 'success' && /Μετατοπίστηκαν: 4 διαθεσιμότητες, 10 ώρες προγράμματος/.test(t.message)),
            app.toasts.map(t => t.message).join(' | '));
    } finally { app.close(); }
});
