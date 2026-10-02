/**
 * Μηνύματα του server (res.message / result.message / fatal_error) στα toasts
 * εμφανίζονται ως ΚΕΙΜΕΝΟ — χωρίς διπλό escape σε όσα ήταν ήδη escaped.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes, timetableRoutes } = require('./app_harness.js');

const toastTexts = (app) => [...app.doc.querySelectorAll('#toast-container .toast-message')].map(e => e.textContent);
const noTags = (app) => app.doc.querySelector('#toast-container .toast-message b, #toast-container .toast-message i');

test('📦 Αρχειοθέτηση καθηγητή: το μήνυμα επιτυχίας του server ως κείμενο', async () => {
    const routes = baseRoutes({
        'GET /api/teachers/': () => [{ id: 21, name: 'Νικολάου', short_name: 'ΝΙΚ', email: '', color: '#3B82F6' }],
        'POST /api/teachers/*/archive': () => ({ message: 'Ο «<b>Νικολάου</b>» αρχειοθετήθηκε & κρύφτηκε' }),
    });
    const app = await start(routes);
    try {
        await go(app, 'teachers', '.dt-custom[data-action="archive"][data-id="21"]');
        app.doc.querySelector('.dt-custom[data-action="archive"][data-id="21"]').click();
        await waitFor(app.w, () => app.doc.getElementById('modal-overlay').classList.contains('active'));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => /αρχειοθετήθηκε/.test(t)));
        assert.ok(toastTexts(app).includes('Ο «<b>Νικολάου</b>» αρχειοθετήθηκε & κρύφτηκε'), toastTexts(app).join(' | '));
        assert.equal(noTags(app), null);
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('Ρυθμίσεις → templates: fatal_error και ετικέτα template ως κείμενο', async () => {
    let fatal = '<b>Λείπει</b> το template & δεν φορτώθηκε';
    const routes = baseRoutes({
        'GET /api/settings/templates': () => [],
        'POST /api/settings/templates/*/preview': () => (fatal
            ? { fatal_error: fatal }
            : { will_create: { subjects: 1, classes: 1, classrooms: 1, constraints: 1 },
                will_skip: { subjects: 0, classes: 0, classrooms: 0, constraints: 0 } }),
        'POST /api/settings/templates/*/apply': () => ({ total_created: 4 }),
    });
    const app = await start(routes);
    app.w.confirm = () => true;
    try {
        await app.G.SettingsView._previewAndApply('k', 'Φροντιστήριο <i>Α</i>');
        assert.ok(toastTexts(app).includes('<b>Λείπει</b> το template & δεν φορτώθηκε'), toastTexts(app).join(' | '));
        fatal = '';
        await app.G.SettingsView._previewAndApply('k', 'Φροντιστήριο <i>Α</i>');
        assert.ok(toastTexts(app).includes('✅ Δημιουργήθηκαν 4 εγγραφές από το Φροντιστήριο <i>Α</i>'), toastTexts(app).join(' | '));
        assert.equal(noTags(app), null);
    } finally { app.close(); }
});

test('Ωρολόγιο: μηνύματα αρχειοθέτησης και «🅿️ Άδειασμα» ως κείμενο', async () => {
    const { routes, state } = timetableRoutes({
        'POST /api/solver/solutions/*/archive': () => {
            state.solutions[0].archived = true;
            return { message: 'Το «<i>Χειμερινό</i>» αρχειοθετήθηκε' };
        },
        'POST /api/solver/solutions/*/unplace-bulk': () => ({ message: '<b>0</b> ώρες & τίποτα να αδειάσει', first_entry_id: null }),
    });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-empty');
        app.doc.getElementById('tt-empty').click();
        await waitFor(app.w, () => app.doc.getElementById('bu-target')?.options.length);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => /τίποτα να αδειάσει/.test(t)));
        assert.ok(toastTexts(app).includes('<b>0</b> ώρες & τίποτα να αδειάσει'), toastTexts(app).join(' | '));

        await waitFor(app.w, () => app.doc.getElementById('tt-archive'));
        app.doc.getElementById('tt-archive').click();
        await waitFor(app.w, () => /Αρχειοθέτηση/.test(app.doc.getElementById('modal-title').textContent));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => /αρχειοθετήθηκε/.test(t)));
        assert.ok(toastTexts(app).includes('Το «<i>Χειμερινό</i>» αρχειοθετήθηκε'), toastTexts(app).join(' | '));
        assert.equal(noTags(app), null);
        await sleep(app.w, 40);
    } finally { app.close(); }
});
