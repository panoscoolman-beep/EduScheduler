/**
 * Escaping, 2ος γύρος: email/τηλέφωνο μαθητών, τύπος αίθουσας, παράμετροι
 * περιορισμών, και μηνύματα σφάλματος του server στα toasts — ως ΚΕΙΜΕΝΟ.
 * Τα toasts που χτίζονται ήδη με escaped κομμάτια δεν γίνονται διπλο-escaped.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes, timetableRoutes } = require('./app_harness.js');

const toastTexts = (app) => [...app.doc.querySelectorAll('#toast-container .toast-message')].map(e => e.textContent);

test('Μαθητές: email/τηλέφωνο ως κείμενο· Αίθουσες: άγνωστος τύπος ως κείμενο', async () => {
    const routes = baseRoutes({
        'GET /api/students/': () => [{ id: 1, first_name: 'Νίκος', last_name: 'Π', email: '<b>x</b>@a.gr',
                                        phone: '69<i>1</i>', class_ids: [] }],
        'GET /api/classrooms/': () => [{ id: 1, name: 'Αίθ 1', short_name: 'Α1', capacity: 20,
                                          room_type: '<b>lab2</b>', building: null }],
    });
    const app = await start(routes);
    try {
        await go(app, 'students', 'tr[data-id="1"]');
        const row = app.doc.querySelector('tr[data-id="1"]');
        assert.equal(row.querySelector('b, i'), null);
        assert.match(row.textContent, /<b>x<\/b>@a\.gr/);
        assert.match(row.textContent, /69<i>1<\/i>/);

        await go(app, 'classrooms', 'tr[data-id="1"]');
        const room = app.doc.querySelector('tr[data-id="1"]');
        assert.equal(room.querySelector('b'), null);
        assert.match(room.textContent, /<b>lab2<\/b>/);
    } finally { app.close(); }
});

test('Περιορισμοί: ονόματα/τιμές παραμέτρων ως κείμενο, σε λίστα και φόρμα', async () => {
    const constraints = [
        { id: 1, name: 'Κ1', constraint_type: 'soft', rule: JSON.stringify({ type: '<b>άγνωστο</b>' }),
          category: 'general', weight: 50, is_active: true },
        { id: 2, name: 'Κ2', constraint_type: 'soft', rule: '{χαλασμένο <i>json',
          category: 'general', weight: 50, is_active: true },
        { id: 3, name: 'Κ3', constraint_type: 'soft', rule: JSON.stringify({ type: 'teacher_preferred_days', teacher_id: 21, days: [0] }),
          category: 'teacher', weight: 50, is_active: true },
        { id: 4, name: 'Κ4', constraint_type: 'soft', rule: JSON.stringify({ type: 'no_late_day', max_period_index: 5, scope: 'class', id: 11 }),
          category: 'general', weight: 50, is_active: true },
    ];
    const routes = baseRoutes({
        'GET /api/constraints/': () => constraints,
        'GET /api/teachers/': () => [{ id: 21, name: 'Γ <b>Π</b>', short_name: 'ΓΠ' }],
        'GET /api/classes/': () => [{ id: 11, name: 'Β2 <i>x</i>', short_name: 'Β2', student_ids: [] }],
    });
    const app = await start(routes);
    try {
        await go(app, 'constraints', '.dt-edit[data-id="4"]');
        const table = app.doc.querySelector('#constraints-table');
        assert.equal(table.querySelector('code b, code i'), null);
        assert.match(table.querySelector('tr[data-id="1"]').textContent, /<b>άγνωστο<\/b>/);
        assert.match(table.querySelector('tr[data-id="2"]').textContent, /\{χαλασμένο <i>json/);

        app.doc.querySelector('.dt-edit[data-id="3"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-param-teacher_id'));
        const tOpt = app.doc.querySelector('#f-param-teacher_id option[value="21"]');
        assert.equal(tOpt.textContent, 'Γ <b>Π</b>');
        assert.equal(tOpt.selected, true);
        app.doc.getElementById('modal-cancel').click();

        app.doc.querySelector('.dt-edit[data-id="4"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-param-id'));
        assert.equal(app.doc.getElementById('f-param-max_period_index').value, '5');
        const cOpt = app.doc.querySelector('#f-param-id option[data-kind="class"][value="11"]');
        assert.equal(cOpt.textContent, 'Β2 <i>x</i>');
        assert.equal(cOpt.selected, true);
        assert.equal(app.doc.querySelector('#f-param-id option[data-kind="teacher"]').textContent, 'Γ <b>Π</b>');
    } finally { app.close(); }
});

test('toasts: μήνυμα σφάλματος του server ως κείμενο· όχι διπλό escape όπου ήταν ήδη', async () => {
    const teacher = { id: 21, name: 'A & B <x>', short_name: 'AB', email: '', phone: '', color: '#3B82F6' };
    const routes = baseRoutes({
        'GET /api/teachers/': () => [teacher],
        'PUT /api/teachers/*': () => ({ __status: 400, data: { detail: '<b>Β2</b> & Γ1 υπάρχει ήδη' } }),
        'DELETE /api/teachers/*': ({ search }) => (/force=true/.test(search)
            ? { __status: 204 }
            : { __status: 409, data: { detail: { requires_force: true, message: 'Θα σβηστούν <u>3</u> ώρες' } } }),
    });
    const app = await start(routes);
    try {
        await go(app, 'teachers', '.dt-edit[data-id="21"]');
        app.doc.querySelector('.dt-edit[data-id="21"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-name'));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => t.includes('υπάρχει ήδη')));
        assert.ok(toastTexts(app).includes('<b>Β2</b> & Γ1 υπάρχει ήδη'), toastTexts(app).join(' | '));
        assert.equal(app.doc.querySelector('#toast-container .toast-message b'), null);
        app.doc.getElementById('modal-cancel').click();

        // Το «Διαγράφηκε «…»» χτίζεται ήδη με escaped όνομα — ΕΝΑ escape, όχι δύο.
        app.doc.querySelector('.dt-delete[data-id="21"]').click();
        await waitFor(app.w, () => app.doc.getElementById('modal-overlay').classList.contains('active'));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => /Καταστροφική/.test(app.doc.getElementById('modal-title').textContent));
        assert.match(app.doc.getElementById('modal-body').textContent, /Θα σβηστούν <u>3<\/u> ώρες/);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => t.startsWith('Διαγράφηκε')));
        assert.ok(toastTexts(app).includes('Διαγράφηκε «A & B <x>»'), toastTexts(app).join(' | '));
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('Ωρολόγιο: σφάλματα αρχειοθέτησης/τοποθέτησης ως κείμενο (και τα ήδη-escaped μένουν σωστά)', async () => {
    const { routes } = timetableRoutes({
        'POST /api/solver/solutions/*/archive': () => ({ __status: 409, data: { detail: 'A & B <i>σε χρήση</i>' } }),
    });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-archive');
        app.doc.getElementById('tt-archive').click();
        await waitFor(app.w, () => app.doc.getElementById('modal-overlay').classList.contains('active'));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => t.startsWith('Δεν έγινε')));
        assert.ok(toastTexts(app).includes('Δεν έγινε: A & B <i>σε χρήση</i>'), toastTexts(app).join(' | '));

        app.G.TimetableGrid.reportConflict('Αποτυχία: ', { message: '<i>Νικολάου</i> διδάσκει ήδη' });
        assert.ok(toastTexts(app).includes('Αποτυχία: <i>Νικολάου</i> διδάσκει ήδη'), toastTexts(app).join(' | '));
        assert.equal(app.doc.querySelector('#toast-container .toast-message i'), null);
    } finally { app.close(); }
});
