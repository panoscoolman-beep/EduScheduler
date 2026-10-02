/**
 * (1) «🧩 Γέμισε τα κενά» / «🔒 Lock & Regenerate»: το μήνυμα του server (με ⚠️
 *     προειδοποιήσεις) φαίνεται, ως κείμενο, με τις γραμμές του.
 * (2) Περιορισμοί: «Σκληρός» μόνο για «Όχι μάθημα μετά από…» και «Προτιμώμενες
 *     ημέρες»· οι υπάρχουσες γραμμές μένουν ως έχουν, με σημείωση στη λίστα.
 * (3) max_consecutive: σημείωση «δεν εφαρμόζεται από τον solver».
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes, timetableRoutes, slot } = require('./app_harness.js');

const toastEls = (app) => [...app.doc.querySelectorAll('#toast-container .toast')];
const overlayOpen = (app) => app.doc.getElementById('modal-overlay').classList.contains('active');

async function runFillGaps(app, result) {
    app.G.TimetableInteractions.pollSolve = async () => result;
    app.doc.getElementById('tt-fill').click();
    await waitFor(app.w, () => app.doc.getElementById('fill-name'));
    app.doc.getElementById('modal-save').click();
}

test('Γέμισε τα κενά: το μήνυμα του server με τις ⚠️ γραμμές του, ως κείμενο· αλλιώς το σταθερό', async () => {
    const { routes, state } = timetableRoutes({ 'POST /api/solver/regenerate/*': () => ({ solution_id: 8 }) });
    state.slots.push(slot(3, { is_unplaced: true, day_of_week: null, period_id: null }));
    state.solutions.unshift({ id: 8, name: 'Χειμερινό (συμπλήρωση)', status: 'optimal', created_at: '2026-10-01T10:00:00Z',
                              archived: false, slots: state.slots });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-fill');
        await runFillGaps(app, { status: 'optimal', solution_id: 8,
            message: 'Ολοκληρώθηκε (optimal) — 3 μαθήματα τοποθετήθηκαν.\n⚠️ Κλειδωμένη ώρα: <b>Νίκος</b> Δευ 1η σε 2 κάρτες\n⚠️ «Max/Εβδ.»: 1 ώρα στην Παλέτα' });
        await waitFor(app.w, () => toastEls(app).some(t => /Ολοκληρώθηκε/.test(t.textContent)));
        const t = toastEls(app).find(x => /Ολοκληρώθηκε/.test(x.textContent));
        const msg = t.querySelector('.toast-message');
        assert.ok(t.classList.contains('warning'), 'με ⚠️ → κίτρινο, μένει περισσότερο');
        assert.equal(msg.querySelectorAll('br').length, 2, 'μία γραμμή ανά προειδοποίηση');
        assert.equal(msg.querySelector('b'), null);
        assert.match(msg.textContent, /Κλειδωμένη ώρα: <b>Νίκος<\/b> Δευ 1η σε 2 κάρτες/);
        assert.match(msg.textContent, /«Max\/Εβδ\.»: 1 ώρα στην Παλέτα/);

        // Χωρίς μήνυμα → το σημερινό σταθερό κείμενο (πράσινο)
        await waitFor(app.w, () => app.doc.getElementById('tt-fill') && !overlayOpen(app));
        await runFillGaps(app, { status: 'optimal', solution_id: 8 });
        await waitFor(app.w, () => toastEls(app).some(x => /Έτοιμο το «/.test(x.textContent)));
        const fb = toastEls(app).find(x => /Έτοιμο το «/.test(x.textContent));
        assert.ok(fb.classList.contains('success'));
        assert.match(fb.textContent, /σύγκρινέ το με το αρχικό/);
        await sleep(app.w, 40);
    } finally { app.close(); }
});

test('Lock & Regenerate: ίδια εμφάνιση του μηνύματος (γραμμές, ⚠️ κίτρινο)', async () => {
    const { routes, state } = timetableRoutes({ 'POST /api/solver/regenerate/*': () => ({ solution_id: 8 }) });
    state.slots[0].is_locked = true;
    state.solutions.unshift({ id: 8, name: 'Χειμερινό v2', status: 'optimal', created_at: '2026-10-01T10:00:00Z',
                              archived: false, slots: state.slots });
    const app = await start(routes);
    app.G.TimetableInteractions.pollSolve = async () => ({ status: 'optimal', solution_id: 8,
        message: 'Ολοκληρώθηκε (optimal) — 2 μαθήματα τοποθετήθηκαν.\n⚠️ Ο κανόνας «Κενά» εφαρμόζεται ως Μαλακός' });
    try {
        await go(app, 'timetable', '#tt-regen');
        app.doc.getElementById('tt-regen').click();
        await waitFor(app.w, () => app.doc.getElementById('regen-name'));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastEls(app).some(t => /Ολοκληρώθηκε/.test(t.textContent)));
        const t = toastEls(app).find(x => /Ολοκληρώθηκε/.test(x.textContent));
        assert.ok(t.classList.contains('warning'));
        assert.equal(t.querySelectorAll('.toast-message br').length, 1);
        await sleep(app.w, 40);
    } finally { app.close(); }
});

function constraintsApp(extra = {}) {
    const C = (id, name, type, rule) => ({ id, name, constraint_type: type, category: 'general',
                                            rule: JSON.stringify(rule), weight: 50, is_active: true });
    const rows = [
        C(1, 'Κενά (σκληρός)', 'hard', { type: 'min_teacher_gaps' }),
        C(2, 'Κενά (μαλακός)', 'soft', { type: 'min_teacher_gaps' }),
        C(3, 'Όχι αργά', 'hard', { type: 'no_late_day', max_period_index: 5, scope: 'all' }),
        C(4, 'Χωρίς σύγκρουση καθηγητή', 'hard', { type: 'no_teacher_clash' }),
        C(5, 'Συνεχόμενα (μαλακός)', 'soft', { type: 'max_consecutive', max: 3 }),
        C(6, 'Συνεχόμενα (σκληρός)', 'hard', { type: 'max_consecutive', max: 3 }),
    ];
    const writes = [];
    const routes = baseRoutes(Object.assign({
        'GET /api/constraints/': () => rows,
        'GET /api/teachers/': () => [{ id: 21, name: 'Νικολάου', short_name: 'ΝΙΚ' }],
        'POST /api/constraints/': ({ body }) => { writes.push(['POST', body]); return { id: 99, ...body }; },
        'PUT /api/constraints/*': ({ body, path: p }) => { writes.push(['PUT ' + p, body]); return body; },
    }, extra));
    return { routes, rows, writes };
}

test('Περιορισμοί (λίστα): σημειώσεις «εφαρμόζεται ως μαλακός» / «δεν εφαρμόζεται από τον solver»', async () => {
    const { routes } = constraintsApp();
    const app = await start(routes);
    try {
        await go(app, 'constraints', 'tr[data-id="6"]');
        const row = (id) => app.doc.querySelector(`tr[data-id="${id}"]`).textContent;
        assert.match(row(1), /⚠️ εφαρμόζεται ως μαλακός/);
        for (const id of [2, 3, 4, 5, 6]) assert.doesNotMatch(row(id), /εφαρμόζεται ως μαλακός/, `row ${id}`);
        for (const id of [5, 6]) assert.match(row(id), /⚠️ δεν εφαρμόζεται από τον solver/, `row ${id}`);
        for (const id of [1, 2, 3, 4]) assert.doesNotMatch(row(id), /δεν εφαρμόζεται/, `row ${id}`);
        // Καμία γραμμή δεν κρύφτηκε ή άλλαξε τύπο
        assert.equal(app.doc.querySelectorAll('#constraints-table tbody tr').length, 6);
        assert.equal(app.doc.querySelectorAll('#constraints-table .constraint-badge.hard').length, 4);
    } finally { app.close(); }
});

test('Περιορισμοί (φόρμα): «Σκληρός» μόνο για «Όχι μάθημα μετά…» / «Προτιμώμενες ημέρες»', async () => {
    const { routes, writes } = constraintsApp();
    const app = await start(routes);
    try {
        await go(app, 'constraints', '[id^="dt-add-"]');
        app.doc.querySelector('[id^="dt-add-"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-rule-params')?.innerHTML);
        const typeSel = app.doc.getElementById('f-type');
        const hardOpt = typeSel.querySelector('option[value="hard"]');
        const ruleSel = app.doc.getElementById('f-rule-type');
        const setRule = (v) => { ruleSel.value = v; ruleSel.dispatchEvent(new app.w.Event('change')); };
        assert.ok(![...ruleSel.options].some(o => o.value === 'max_consecutive'), 'δεν προσφέρεται');
        assert.equal(ruleSel.value, 'min_teacher_gaps');
        assert.equal(hardOpt.disabled, true);
        assert.equal(typeSel.value, 'soft');
        assert.match(app.doc.getElementById('f-type-hint').textContent, /μόνο για/);

        setRule('no_late_day');
        assert.equal(hardOpt.disabled, false);
        typeSel.value = 'hard';
        typeSel.dispatchEvent(new app.w.Event('change'));
        setRule('subject_distribution');                   // άλλο είδος → πίσω σε Μαλακός
        assert.equal(hardOpt.disabled, true);
        assert.equal(typeSel.value, 'soft');
        setRule('teacher_preferred_days');
        assert.equal(hardOpt.disabled, false);
        typeSel.value = 'hard';
        app.doc.getElementById('f-name').value = 'Μόνο Δευτέρα';
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => writes.length === 1);
        assert.equal(writes[0][1].constraint_type, 'hard');
        assert.equal(JSON.parse(writes[0][1].rule).type, 'teacher_preferred_days');
        await waitFor(app.w, () => !overlayOpen(app));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('Περιορισμοί (φόρμα): επεξεργασία υπάρχουσας σκληρής γραμμής άλλου είδους → στέλνει ό,τι πριν', async () => {
    const { routes, writes } = constraintsApp();
    const app = await start(routes);
    try {
        await go(app, 'constraints', '.dt-edit[data-id="1"]');
        // Κανόνας-προτίμηση αποθηκευμένος ως «Σκληρός»
        app.doc.querySelector('.dt-edit[data-id="1"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-rule-params')?.innerHTML);
        const typeSel = app.doc.getElementById('f-type');
        assert.equal(typeSel.value, 'hard');
        assert.equal(typeSel.querySelector('option[value="hard"]').disabled, false);
        assert.match(app.doc.getElementById('f-type-hint').textContent, /εφαρμόζεται ως μαλακός/);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => writes.length === 1);
        assert.equal(writes[0][0], 'PUT /api/constraints/1');
        assert.equal(writes[0][1].constraint_type, 'hard');
        assert.equal(JSON.parse(writes[0][1].rule).type, 'min_teacher_gaps');
        await waitFor(app.w, () => !overlayOpen(app));

        // Ενσωματωμένος κανόνας (φαίνεται ως «Custom»): μένει σκληρός
        await waitFor(app.w, () => app.doc.querySelector('.dt-edit[data-id="4"]'));
        app.doc.querySelector('.dt-edit[data-id="4"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-param-__raw_json__'));
        assert.equal(app.doc.getElementById('f-type').value, 'hard');
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => writes.length === 2);
        assert.equal(writes[1][1].constraint_type, 'hard');
        assert.equal(JSON.parse(writes[1][1].rule).type, 'no_teacher_clash');
        await waitFor(app.w, () => !overlayOpen(app));

        // Γραμμή max_consecutive με παραμέτρους: ο κανόνας δεν χάνεται σε μια απλή αποθήκευση
        await waitFor(app.w, () => app.doc.querySelector('.dt-edit[data-id="5"]'));
        app.doc.querySelector('.dt-edit[data-id="5"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-param-__raw_json__'));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => writes.length === 3);
        assert.deepEqual(JSON.parse(writes[2][1].rule), { type: 'max_consecutive', max: 3 });
        assert.equal(writes[2][1].constraint_type, 'soft');
        await waitFor(app.w, () => !overlayOpen(app));
        await sleep(app.w, 20);
    } finally { app.close(); }
});
