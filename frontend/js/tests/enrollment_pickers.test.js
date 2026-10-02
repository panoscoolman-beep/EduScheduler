/**
 * Εγγραφές μαθητών: αν ο επιλογέας ΔΕΝ φορτώθηκε, η αποθήκευση δεν αγγίζει
 * τις εγγραφές (πριν: το τμήμα άδειαζε ή έπαιρνε μαθητές άλλου τμήματος).
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes } = require('./app_harness.js');

function setup() {
    const flags = { failStudents: false, failClasses: false };
    const writes = { puts: [], posts: [], enrollAdd: [], enrollDel: [] };
    const classes = [
        { id: 11, name: 'Β2 Λυκείου', short_name: 'Β2', grade_level: 2, student_ids: [1, 2, 3, 4], home_room_id: null },
        { id: 12, name: 'Γ1 Λυκείου', short_name: 'Γ1', grade_level: 3, student_ids: [9], home_room_id: null },
    ];
    const students = [1, 2, 3, 4, 9].map(id => ({ id, first_name: 'Μ' + id, last_name: 'Ε' + id, class_ids: id === 9 ? [12] : [11] }));
    const fail = { __status: 503, data: { detail: 'Service Unavailable' } };
    const routes = baseRoutes({
        'GET /api/classes/': () => (flags.failClasses ? fail : classes),
        'GET /api/students/': () => (flags.failStudents ? fail : students),
        'PUT /api/classes/*': ({ body, path: p }) => { writes.puts.push({ path: p, body }); return { ...classes[0], ...body }; },
        'POST /api/classes/': ({ body }) => { writes.posts.push(body); return { id: 99, ...body }; },
        'POST /api/classes/*/students/*': ({ path: p }) => { writes.enrollAdd.push(p); return classes[0]; },
        'DELETE /api/classes/*/students/*': ({ path: p }) => { writes.enrollDel.push(p); return classes[0]; },
    });
    return { routes, flags, writes };
}

const overlayOpen = (app) => app.doc.getElementById('modal-overlay').classList.contains('active');

async function openClassForm(app, id) {
    app.doc.querySelector(id ? `.dt-edit[data-id="${id}"]` : '[id^="dt-add-"]').click();
    await waitFor(app.w, () => {
        const el = app.doc.getElementById('f-students-picker');
        return el && !el.querySelector('.loading-spinner');
    });
}

test('φόρμα τμήματος: αποτυχία φόρτωσης μαθητών → το PUT ΔΕΝ στέλνει student_ids', async () => {
    const { routes, flags, writes } = setup();
    const app = await start(routes);
    try {
        await go(app, 'classes', '.dt-edit[data-id="11"]');
        flags.failStudents = true;
        await openClassForm(app, 11);
        assert.match(app.doc.getElementById('f-students-picker').textContent, /Σφάλμα φόρτωσης μαθητών/);
        flags.failStudents = false;
        app.doc.getElementById('f-name').value = 'Β2 Λυκείου (διορθ.)';
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => writes.puts.length === 1);
        const body = writes.puts[0].body;
        assert.equal(body.name, 'Β2 Λυκείου (διορθ.)');
        assert.equal('student_ids' in body, false, 'οι εγγραφές μένουν ως έχουν');
        await waitFor(app.w, () => !overlayOpen(app));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('φόρμα τμήματος: η επιλογή προηγούμενης φόρμας ΔΕΝ περνά σε άλλο τμήμα', async () => {
    const { routes, flags, writes } = setup();
    const app = await start(routes);
    try {
        await go(app, 'classes', '.dt-edit[data-id="12"]');
        await openClassForm(app, 12);                      // Γ1 φορτώνει κανονικά ([9])
        app.doc.getElementById('modal-cancel').click();
        flags.failStudents = true;
        await openClassForm(app, 11);                      // Β2 με σφάλμα
        flags.failStudents = false;
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => writes.puts.length === 1);
        assert.equal(writes.puts[0].path, '/api/classes/11');
        assert.equal('student_ids' in writes.puts[0].body, false);
        await waitFor(app.w, () => !overlayOpen(app));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('φόρμα τμήματος: κανονική ροή — οι αλλαγές μαθητών αποθηκεύονται όπως πριν', async () => {
    const { routes, writes } = setup();
    const app = await start(routes);
    try {
        await go(app, 'classes', '.dt-edit[data-id="11"]');
        await openClassForm(app, 11);
        const cb = app.doc.querySelector('#f-students-picker .sp-check[data-id="4"]');
        cb.checked = false;
        cb.dispatchEvent(new app.w.Event('change', { bubbles: true }));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => writes.puts.length === 1);
        assert.deepEqual(writes.puts[0].body.student_ids, [1, 2, 3]);
        await waitFor(app.w, () => !overlayOpen(app));

        // Νέο τμήμα: ξεκινά χωρίς επιλογές (όχι με του προηγούμενου)
        await waitFor(app.w, () => app.doc.querySelector('[id^="dt-add-"]'));
        await openClassForm(app, null);
        assert.equal(app.doc.querySelectorAll('#f-students-picker .sp-check:checked').length, 0);
        app.doc.getElementById('f-name').value = 'Α1';
        app.doc.getElementById('f-short_name').value = 'Α1';
        const cb9 = app.doc.querySelector('#f-students-picker .sp-check[data-id="9"]');
        cb9.checked = true;
        cb9.dispatchEvent(new app.w.Event('change', { bubbles: true }));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => writes.posts.length === 1);
        assert.deepEqual(writes.posts[0].student_ids, [9]);
        await waitFor(app.w, () => !overlayOpen(app));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('Μαθητές → 🏫: αποτυχία φόρτωσης τμημάτων → καμία εγγραφή/διαγραφή', async () => {
    const { routes, flags, writes } = setup();
    const app = await start(routes);
    try {
        // Πρώτα μια φόρμα τμήματος (αφήνει επιλογή ΜΑΘΗΤΩΝ στον κοινό επιλογέα)
        await go(app, 'classes', '.dt-edit[data-id="12"]');
        await openClassForm(app, 12);
        app.doc.getElementById('modal-cancel').click();

        await go(app, 'students', '.dt-custom[data-action="classes"][data-id="1"]');
        flags.failClasses = true;
        app.doc.querySelector('.dt-custom[data-action="classes"][data-id="1"]').click();
        await waitFor(app.w, () => /Σφάλμα φόρτωσης τμημάτων/.test(app.doc.getElementById('f-classes-picker')?.textContent || ''));
        flags.failClasses = false;
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => app.toasts.some(t => t.type === 'error' && /δεν έχουν φορτωθεί/.test(t.message)));
        await sleep(app.w, 30);
        assert.deepEqual(writes.enrollAdd, []);
        assert.deepEqual(writes.enrollDel, []);
    } finally { app.close(); }
});

test('Μαθητές → 🏫: κανονική ροή — μόνο οι διαφορές γράφονται', async () => {
    const { routes, writes } = setup();
    const app = await start(routes);
    try {
        await go(app, 'students', '.dt-custom[data-action="classes"][data-id="1"]');
        app.doc.querySelector('.dt-custom[data-action="classes"][data-id="1"]').click();
        await waitFor(app.w, () => app.doc.querySelector('#f-classes-picker .sp-check[data-id="12"]'));
        const add = app.doc.querySelector('#f-classes-picker .sp-check[data-id="12"]');
        add.checked = true;
        add.dispatchEvent(new app.w.Event('change', { bubbles: true }));
        const rem = app.doc.querySelector('#f-classes-picker .sp-check[data-id="11"]');
        rem.checked = false;
        rem.dispatchEvent(new app.w.Event('change', { bubbles: true }));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => !overlayOpen(app));
        assert.deepEqual(writes.enrollAdd, ['/api/classes/12/students/1']);
        assert.deepEqual(writes.enrollDel, ['/api/classes/11/students/1']);
        await sleep(app.w, 30);
    } finally { app.close(); }
});
