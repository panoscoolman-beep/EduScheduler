/**
 * Modal: διπλό κλικ στο «Αποθήκευση» δεν τρέχει την ενέργεια δύο φορές
 * (π.χ. διπλή «Μετατόπιση ωρών» = όλες οι ώρες εκτός προγράμματος).
 * Full-app jsdom (πραγματικό index.html + scripts, ψεύτικο backend).
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes } = require('./app_harness.js');

/** Backend με ρυθμιζόμενη καθυστέρηση/απάντηση για το shift-times. */
function shiftApp(respond) {
    const posts = [];
    let W = null;
    const routes = baseRoutes({
        'POST /api/terms/*/shift-times': ({ body }) => {
            posts.push(body);
            return respond(posts.length, (ms, v) => new Promise(r => W.setTimeout(() => r(v), ms)));
        },
    });
    return { routes, posts, bind: (w) => { W = w; } };
}

const OK = { availability_moved: 1, slots_moved: 1, availability_dropped: 0, slots_unplaced: 0 };

async function openShift(app) {
    await go(app, 'terms', 'button[data-act="shift"]');
    app.doc.querySelector('button[data-act="shift"]').click();
    await waitFor(app.w, () => app.doc.getElementById('shift-offset'));
    return app.doc.getElementById('modal-save');
}

test('διπλό κλικ στη «Μετατόπιση ωρών» όσο τρέχει το αίτημα → ΕΝΑ POST', async () => {
    const be = shiftApp((n, later) => later(150, OK));
    const app = await start(be.routes);
    be.bind(app.w);
    try {
        const save = await openShift(app);
        save.click();
        assert.equal(save.disabled, true, 'απενεργό όσο τρέχει');
        save.click();                       // αμέσως
        await sleep(app.w, 60);
        save.click();                       // και λίγο μετά
        await waitFor(app.w, () => !app.doc.getElementById('modal-overlay').classList.contains('active'));
        await sleep(app.w, 30);
        assert.equal(be.posts.length, 1);
    } finally { app.close(); }
});

test('σφάλμα → το κουμπί ξαναενεργοποιείται και η νέα προσπάθεια περνά', async () => {
    const be = shiftApp((n, later) => (n === 1
        ? later(30, { __status: 503, data: { detail: 'Service Unavailable' } })
        : later(30, OK)));
    const app = await start(be.routes);
    be.bind(app.w);
    try {
        const save = await openShift(app);
        save.click();
        await waitFor(app.w, () => app.toasts.some(t => t.type === 'error'));
        await waitFor(app.w, () => save.disabled === false);
        assert.ok(app.doc.getElementById('modal-overlay').classList.contains('active'), 'μένει ανοιχτό');
        save.click();
        await waitFor(app.w, () => !app.doc.getElementById('modal-overlay').classList.contains('active'));
        assert.equal(be.posts.length, 2);
    } finally { app.close(); }
});

test('έλεγχος φόρμας που αποτυγχάνει (μετατόπιση 0) δεν «κολλάει» το κουμπί', async () => {
    const be = shiftApp((n, later) => later(10, OK));
    const app = await start(be.routes);
    be.bind(app.w);
    try {
        const save = await openShift(app);
        app.doc.getElementById('shift-offset').value = '0';
        save.click();
        await waitFor(app.w, () => save.disabled === false);
        assert.equal(be.posts.length, 0);
        app.doc.getElementById('shift-offset').value = '6';
        save.click();
        await waitFor(app.w, () => be.posts.length === 1);
    } finally { app.close(); }
});

test('παράθυρο επιβεβαίωσης «force» που ανοίγει μέσα από το save έχει ενεργό κουμπί', async () => {
    const teacher = { id: 21, name: 'Νικολάου', short_name: 'ΝΙΚ', email: '', phone: '', color: '#3B82F6' };
    const puts = [];
    const routes = baseRoutes({
        'GET /api/teachers/': () => [teacher],
        'PUT /api/teachers/*': ({ body }) => {
            puts.push(body);
            return puts.length === 1
                ? { __status: 409, data: { detail: { requires_force: true, message: 'Συγκρούεται με 2 ώρες' } } }
                : { ...teacher, ...body };
        },
        'DELETE /api/teachers/*': ({ search }) => (/force=true/.test(search)
            ? { __status: 204 }
            : { __status: 409, data: { detail: { requires_force: true, message: 'Θα σβηστούν 3 ώρες' } } }),
    });
    const app = await start(routes);
    try {
        await go(app, 'teachers', '.dt-edit[data-id="21"]');
        app.doc.querySelector('.dt-edit[data-id="21"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-name'));
        const save = app.doc.getElementById('modal-save');
        save.click();
        await waitFor(app.w, () => /συγκρούεται/.test(app.doc.getElementById('modal-title').textContent));
        await sleep(app.w, 20);
        assert.equal(save.disabled, false, 'το follow-up δεν μένει απενεργό');
        save.click();
        await waitFor(app.w, () => puts.length === 2);
        await waitFor(app.w, () => !app.doc.getElementById('modal-overlay').classList.contains('active'));

        // Ίδιο για τη διαγραφή με force
        await waitFor(app.w, () => app.doc.querySelector('.dt-delete[data-id="21"]'));
        app.doc.querySelector('.dt-delete[data-id="21"]').click();
        await waitFor(app.w, () => app.doc.getElementById('modal-overlay').classList.contains('active'));
        save.click();
        await waitFor(app.w, () => /Καταστροφική/.test(app.doc.getElementById('modal-title').textContent));
        await sleep(app.w, 20);
        assert.equal(save.disabled, false);
        save.click();
        await waitFor(app.w, () => app.calls.some(c => c.method === 'DELETE' && /force=true/.test(c.search)));
        await waitFor(app.w, () => !app.doc.getElementById('modal-overlay').classList.contains('active'));
        await sleep(app.w, 30);     // αφήσε το reload του πίνακα να τελειώσει
    } finally { app.close(); }
});

test('διπλό κλικ σε «Νέο μάθημα-κάρτα» → ΜΙΑ κάρτα', async () => {
    let W = null;
    const creates = [];
    const routes = baseRoutes({
        'POST /api/lessons/': ({ body }) => {
            creates.push(body);
            return new Promise(r => W.setTimeout(() => r({ id: 900 + creates.length, ...body }), 120));
        },
        'GET /api/subjects/': () => [{ id: 1, name: 'Φυσική', short_name: 'ΦΥΣ' }],
        'GET /api/teachers/': () => [{ id: 21, name: 'Νικολάου', short_name: 'ΝΙΚ' }],
        'GET /api/classes/': () => [{ id: 11, name: 'Β2', short_name: 'Β2', student_ids: [] }],
        'GET /api/lessons/distribution-suggestions': () => ({ options: [] }),
    });
    const app = await start(routes);
    W = app.w;
    try {
        await go(app, 'lessons', '[id^="dt-add-"]');
        app.doc.querySelector('[id^="dt-add-"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-subject'));
        app.doc.getElementById('f-subject').value = '1';
        app.doc.getElementById('f-teacher').value = '21';
        app.doc.getElementById('f-class').value = '11';
        app.doc.getElementById('f-ppw').value = '2';
        const save = app.doc.getElementById('modal-save');
        save.click();
        await sleep(app.w, 40);
        save.click();
        await waitFor(app.w, () => !app.doc.getElementById('modal-overlay').classList.contains('active'));
        await sleep(app.w, 30);
        assert.equal(creates.length, 1);
    } finally { app.close(); }
});
