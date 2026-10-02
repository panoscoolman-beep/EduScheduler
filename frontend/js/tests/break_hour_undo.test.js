/**
 * Αναίρεση/Επανάληψη/«μέχρι εδώ» σε αλλαγή ώρας που έγινε «Διάλειμμα» (409
 * break_hour): επιβεβαίωση → ίδια κλήση με skip_break=true → μήνυμα με πλήθος.
 * Και η επιβεβαίωση «ώρα → Διάλειμμα» στις Ώρες, από τη λίστα programmes.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes, timetableRoutes } = require('./app_harness.js');

const overlayOpen = (app) => app.doc.getElementById('modal-overlay').classList.contains('active');
const toastTexts = (app) => [...app.doc.querySelectorAll('#toast-container .toast-message')].map(e => e.textContent);
const BREAK = { __status: 409, data: { detail: {
    code: 'break_hour', requires_force: true, entry_id: 5, period: '3η',
    message: 'Η αλλαγή αφορά την ώρα «<b>3η</b>», που είναι πλέον διάλειμμα.' } } };
const calls = (app, re) => app.calls.filter(c => c.method === 'POST' && re.test(c.path)).map(c => c.search);

function undoApp(undoHandler) {
    const { routes, state } = timetableRoutes({
        'POST /api/solver/solutions/*/undo': (req) => { state.undoCalls += 1; return undoHandler(req); },
    });
    return { routes, state };
}

test('↩ σε ώρα-διάλειμμα: επιβεβαίωση → ξανά με skip_break=true → μήνυμα με το πλήθος', async () => {
    const { routes } = undoApp(({ search }) => (/skip_break=true/.test(search)
        ? { message: 'Αναιρέθηκε: Φυσική Β2', skipped_break: 2 } : BREAK));
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-undo');
        await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled);
        app.doc.getElementById('tt-undo').click();
        await waitFor(app.w, () => /διάλειμμα/.test(app.doc.getElementById('modal-title').textContent));
        const body = app.doc.getElementById('modal-body');
        assert.match(body.textContent, /«<b>3η<\/b>», που είναι πλέον διάλειμμα/);
        assert.equal(body.querySelector('b'), null);
        assert.equal(app.doc.getElementById('modal-save').textContent, 'Παράλειψη και συνέχεια με τις παλαιότερες');
        assert.equal(app.doc.getElementById('modal-cancel').textContent, 'Άκυρο');
        assert.equal(toastTexts(app).length, 0, 'κανένα μήνυμα σφάλματος');
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => /Αναιρέθηκε/.test(t)));
        assert.ok(toastTexts(app).includes('Αναιρέθηκε: Φυσική Β2 (παραλείφθηκαν 2 αλλαγές σε ώρα που έγινε διάλειμμα)'),
            toastTexts(app).join(' | '));
        assert.deepEqual(calls(app, /\/undo$/), ['', '?skip_break=true']);
        await waitFor(app.w, () => app.doc.getElementById('tt-undo') && !overlayOpen(app));
        // Το «Ακύρωση» των άλλων παραθύρων μένει όπως ήταν
        app.doc.getElementById('tt-rename').click();
        await waitFor(app.w, () => overlayOpen(app));
        assert.equal(app.doc.getElementById('modal-cancel').textContent, 'Ακύρωση');
    } finally { app.close(); }
});

test('↩ σε ώρα-διάλειμμα + «Άκυρο» → καμία δεύτερη κλήση', async () => {
    const { routes, state } = undoApp(() => BREAK);
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-undo');
        await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled);
        app.doc.getElementById('tt-undo').click();
        await waitFor(app.w, () => overlayOpen(app));
        app.doc.getElementById('modal-cancel').click();
        await sleep(app.w, 60);
        assert.equal(state.undoCalls, 1);
        assert.deepEqual(calls(app, /\/undo$/), ['']);
        assert.equal(overlayOpen(app), false);
    } finally { app.close(); }
});

test('άλλο 409 στην αναίρεση: όπως πριν — μήνυμα σφάλματος, χωρίς επιβεβαίωση', async () => {
    const { routes, state } = undoApp(() => ({ __status: 409, data: { detail: {
        code: 'slot_taken', message: 'Η θέση Δευ 1η είναι πιασμένη' } } }));
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-undo');
        await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled);
        const summaries = () => app.calls.filter(c => /history-summary$/.test(c.path)).length;
        const before = summaries();
        app.doc.getElementById('tt-undo').click();
        await waitFor(app.w, () => toastTexts(app).includes('Η θέση Δευ 1η είναι πιασμένη'));
        await waitFor(app.w, () => summaries() > before);
        assert.equal(overlayOpen(app), false);
        assert.equal(state.undoCalls, 1);
    } finally { app.close(); }
});

test('🕘 «μέχρι εδώ» σε ώρα-διάλειμμα: επιβεβαίωση → skip_break=true → μήνυμα (ενικός)', async () => {
    const { routes } = timetableRoutes({
        'GET /api/solver/solutions/*/history': () => ({ items: [
            { id: 9, operation: 'move', operation_label: 'Μετακίνηση', undone: false, lesson: 'Φυσική',
              from: 'Δευ 1η', to: 'Τρι 3η', performed_at: '2026-10-02T15:49:03' },
        ] }),
        'POST /api/solver/solutions/*/history/undo-to/*': ({ search }) => (/skip_break=true/.test(search)
            ? { message: 'Αναιρέθηκαν 3 αλλαγές', skipped_break: 1 } : BREAK),
    });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-history');
        app.doc.getElementById('tt-history').click();
        await waitFor(app.w, () => app.doc.querySelector('.hist-undo-to[data-id="9"]'));
        app.doc.querySelector('.hist-undo-to[data-id="9"]').click();
        await waitFor(app.w, () => /διάλειμμα/.test(app.doc.getElementById('modal-title').textContent));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => /Αναιρέθηκαν/.test(t)));
        assert.ok(toastTexts(app).includes('Αναιρέθηκαν 3 αλλαγές (παραλείφθηκε 1 αλλαγή σε ώρα που έγινε διάλειμμα)'),
            toastTexts(app).join(' | '));
        assert.deepEqual(calls(app, /\/undo-to\/9$/), ['', '?skip_break=true']);
        await waitFor(app.w, () => app.doc.getElementById('tt-undo') && !overlayOpen(app));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('API: skip_break=true μόνο όταν ζητηθεί — τα σημερινά URL ίδια', async () => {
    const { routes } = timetableRoutes({
        'POST /api/solver/solutions/*/history/undo-to/*': () => ({ message: 'ok' }),
    });
    const app = await start(routes);
    try {
        const S = app.G.API.solver;
        await S.undo(7); await S.undo(7, true);
        await S.redo(7); await S.redo(7, true);
        await S.undoTo(7, 3); await S.undoTo(7, 3, true);
        const urls = app.calls.filter(c => c.method === 'POST').map(c => c.path + c.search);
        assert.deepEqual(urls, [
            '/api/solver/solutions/7/undo', '/api/solver/solutions/7/undo?skip_break=true',
            '/api/solver/solutions/7/redo', '/api/solver/solutions/7/redo?skip_break=true',
            '/api/solver/solutions/7/history/undo-to/3', '/api/solver/solutions/7/history/undo-to/3?skip_break=true',
        ]);
    } finally { app.close(); }
});

function periodsApp(programmes) {
    const periods = [{ id: 2, name: '2η', short_name: '2η', start_time: '17:00', end_time: '18:00', is_break: false, sort_order: 2 }];
    const puts = [];
    const routes = baseRoutes({
        'GET /api/periods/': () => periods,
        'PUT /api/periods/*': ({ search, body }) => {
            puts.push(search);
            if (body.is_break && !/force=true/.test(search)) {
                return { __status: 409, data: { detail: { code: 'period_in_use', requires_force: true,
                    slots: programmes.reduce((s, p) => s + p.slots, 0), solutions: programmes.length,
                    message: 'Η ώρα «2η» έχει τοποθετημένα μαθήματα.', programmes } } };
            }
            return { ...periods[0], ...body };
        },
    });
    return { routes, puts };
}

async function makeBreak(app) {
    await go(app, 'periods', '.dt-edit[data-id="2"]');
    app.doc.querySelector('.dt-edit[data-id="2"]').click();
    await waitFor(app.w, () => app.doc.getElementById('f-break'));
    app.doc.getElementById('f-break').value = 'true';
    app.doc.getElementById('modal-save').click();
    await waitFor(app.w, () => /διάλειμμα|συγκρούεται/.test(app.doc.getElementById('modal-title').textContent));
}

test('Ώρες → Διάλειμμα, ΜΟΝΟ αρχειοθετημένα: χωρίς «συγκρούεται»/«Παλέτα»· τίποτα δεν μετακινείται', async () => {
    const { routes, puts } = periodsApp([
        { solution_id: 3, solution_name: 'Περσινό <b>Α</b>', term_id: 1, term_name: 'Χειμ', archived: true, slots: 2 },
        { solution_id: 4, solution_name: 'Πολύ παλιό', term_id: 2, term_name: 'Θερινό', archived: true, slots: 1 },
    ]);
    const app = await start(routes);
    try {
        await makeBreak(app);
        const title = app.doc.getElementById('modal-title').textContent;
        const body = app.doc.getElementById('modal-body');
        assert.equal(title, '⚠️ Η ώρα γίνεται διάλειμμα');
        assert.doesNotMatch(title + body.textContent, /συγκρούεται|Παλέτα/);
        assert.equal(body.querySelector('li b b'), null);
        assert.match(body.textContent, /«Περσινό <b>Α<\/b>» \(σενάριο «Χειμ»\) · 📦 αρχειοθετημένο: 2 ώρες/);
        assert.match(body.textContent, /«Πολύ παλιό» \(σενάριο «Θερινό»\) · 📦 αρχειοθετημένο: 1 ώρα/);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => t.startsWith('Αποθηκεύτηκε')));
        const toast = toastTexts(app).find(t => t.startsWith('Αποθηκεύτηκε'));
        assert.match(toast, /δεν μετακινήθηκε καμία ώρα/);
        assert.match(toast, /αρχειοθετημένα προγράμματα έμειναν όπως ήταν/);
        assert.doesNotMatch(toast, /Παλέτα/);
        assert.deepEqual(puts, ['', '?force=true']);
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('Ώρες → Διάλειμμα, ενεργά + αρχειοθετημένα: λίστα, Παλέτα για τα ενεργά, «Αναίρεση» στο μήνυμα', async () => {
    const { routes, puts } = periodsApp([
        { solution_id: 7, solution_name: 'Χειμερινό', term_id: 1, term_name: 'Χειμ', archived: false, slots: 3 },
        { solution_id: 3, solution_name: 'Περσινό', term_id: 1, term_name: 'Χειμ', archived: true, slots: 2 },
    ]);
    const app = await start(routes);
    try {
        await makeBreak(app);
        const body = app.doc.getElementById('modal-body').textContent;
        assert.match(app.doc.getElementById('modal-title').textContent, /συγκρούεται/);
        assert.match(body, /«Χειμερινό» \(σενάριο «Χειμ»\): 3 ώρες/);
        assert.match(body, /«Περσινό» \(σενάριο «Χειμ»\) · 📦 αρχειοθετημένο: 2 ώρες/);
        assert.match(body, /Οι 3 ώρες των ενεργών προγραμμάτων θα πάνε στην Παλέτα/);
        assert.match(body, /αρχειοθετημένα προγράμματα δεν αλλάζουν/);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => t.startsWith('Αποθηκεύτηκε')));
        const toast = toastTexts(app).find(t => t.startsWith('Αποθηκεύτηκε'));
        assert.match(toast, /οι 3 ώρες των ενεργών προγραμμάτων πήγαν στην Παλέτα/);
        assert.match(toast, /«↩️ Αναίρεση»/);
        assert.deepEqual(puts, ['', '?force=true']);
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('το σημείωμα «παραλείφθηκαν…» δεν διπλασιάζεται όταν το γράφει ήδη ο server', async () => {
    const { routes } = undoApp(({ search }) => (/skip_break=true/.test(search)
        ? { message: 'Αναιρέθηκε: Φυσική (παραλείφθηκαν 2 αλλαγές σε ώρες-διαλείμματα)', skipped_break: 2 } : BREAK));
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-undo');
        await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled);
        app.doc.getElementById('tt-undo').click();
        await waitFor(app.w, () => overlayOpen(app));
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => /Αναιρέθηκε/.test(t)));
        assert.ok(toastTexts(app).includes('Αναιρέθηκε: Φυσική (παραλείφθηκαν 2 αλλαγές σε ώρες-διαλείμματα)'),
            toastTexts(app).join(' | '));
        await waitFor(app.w, () => app.doc.getElementById('tt-undo') && !overlayOpen(app));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

// ── Round 7: «Επαναφορά όλων», ανανέωση μετά από skip_break, 400 με skipped_break ──

const solutionGets = (app) => app.calls.filter(c => c.method === 'GET' && /\/api\/solver\/solutions\/7$/.test(c.path)).length;

test('«↩️ Επαναφορά όλων» σε ώρα-διάλειμμα: ίδια επιβεβαίωση → skip_break=true → ίδιο μήνυμα', async () => {
    const { routes } = timetableRoutes({
        'POST /api/solver/solutions/*/unplace-bulk': () => ({ message: 'Στην Παλέτα 2 ώρες', first_entry_id: 11 }),
        'POST /api/solver/solutions/*/history/undo-to/*': ({ search }) => (/skip_break=true/.test(search)
            ? { message: 'Αναιρέθηκαν 2 αλλαγές', skipped_break: 1 } : BREAK),
    });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-empty');
        app.doc.getElementById('tt-empty').click();
        await waitFor(app.w, () => app.doc.getElementById('bu-target')?.options.length);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => app.doc.getElementById('modal-title').textContent === '✅ Έγινε');
        assert.equal(app.doc.getElementById('modal-save').textContent, '↩️ Επαναφορά όλων');
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => /διάλειμμα/.test(app.doc.getElementById('modal-title').textContent));
        assert.equal(app.doc.getElementById('modal-save').textContent, 'Παράλειψη και συνέχεια με τις παλαιότερες');
        assert.equal(app.doc.getElementById('modal-cancel').textContent, 'Άκυρο');
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).some(t => /Αναιρέθηκαν/.test(t)));
        assert.ok(toastTexts(app).includes('Αναιρέθηκαν 2 αλλαγές (παραλείφθηκε 1 αλλαγή σε ώρα που έγινε διάλειμμα)'),
            toastTexts(app).join(' | '));
        assert.deepEqual(calls(app, /\/undo-to\/11$/), ['', '?skip_break=true']);
        await waitFor(app.w, () => app.doc.getElementById('tt-undo') && !overlayOpen(app));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('skip_break που τελειώνει σε 400 με skipped_break: ενημέρωση με το N + ανανέωση πλέγματος/κουμπιών', async () => {
    const nothing = (what) => ({ __status: 400, data: { detail: `Δεν υπάρχει αλλαγή προς ${what}`, skipped_break: 3 } });
    const { routes } = timetableRoutes({
        'POST /api/solver/solutions/*/undo': ({ search }) => (/skip_break=true/.test(search) ? nothing('αναίρεση') : BREAK),
        'POST /api/solver/solutions/*/redo': ({ search }) => (/skip_break=true/.test(search) ? nothing('επανάληψη') : BREAK),
    });
    const app = await start(routes);
    const confirmSkip = async (saveText) => {
        await waitFor(app.w, () => /διάλειμμα/.test(app.doc.getElementById('modal-title').textContent) && overlayOpen(app));
        assert.equal(app.doc.getElementById('modal-save').textContent, saveText);
        app.doc.getElementById('modal-save').click();
    };
    try {
        await go(app, 'timetable', '#tt-undo');
        await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled && !app.doc.getElementById('tt-redo').disabled);
        const before = solutionGets(app);
        app.doc.getElementById('tt-undo').click();
        await confirmSkip('Παράλειψη και συνέχεια με τις παλαιότερες');
        await waitFor(app.w, () => toastTexts(app).some(t => t.startsWith('Παραλείφθηκαν 3')));
        const toast = [...app.doc.querySelectorAll('#toast-container .toast')].find(t => /Παραλείφθηκαν 3/.test(t.textContent));
        assert.equal(toast.querySelector('.toast-message').textContent,
            'Παραλείφθηκαν 3 αλλαγές σε ώρα που έγινε διάλειμμα — δεν υπάρχει άλλη αλλαγή προς αναίρεση.');
        assert.ok(toast.classList.contains('warning'));
        assert.ok(!toastTexts(app).includes('Δεν υπάρχει αλλαγή προς αναίρεση'), 'όχι σκέτο σφάλμα');
        await waitFor(app.w, () => solutionGets(app) > before);   // ξαναζωγραφίστηκε (οι παραλείψεις γράφτηκαν)
        await waitFor(app.w, () => app.doc.getElementById('tt-redo') && !app.doc.getElementById('tt-redo').disabled);

        app.doc.getElementById('tt-redo').click();
        await confirmSkip('Παράλειψη και συνέχεια με τις επόμενες');   // η επανάληψη πάει μπροστά
        await waitFor(app.w, () => toastTexts(app).includes(
            'Παραλείφθηκαν 3 αλλαγές σε ώρα που έγινε διάλειμμα — δεν υπάρχει άλλη αλλαγή προς επανάληψη.'));
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('skip_break που τελειώνει σε άλλο σφάλμα: μήνυμα σφάλματος ΚΑΙ ανανέωση', async () => {
    const { routes } = timetableRoutes({
        'POST /api/solver/solutions/*/history/undo-to/*': ({ search }) => (/skip_break=true/.test(search)
            ? { __status: 500, data: { detail: 'Σφάλμα <b>βάσης</b>' } } : BREAK),
        'GET /api/solver/solutions/*/history': () => ({ items: [
            { id: 9, operation: 'move', operation_label: 'Μετακίνηση', undone: false, lesson: 'Φυσική',
              from: 'Δευ 1η', to: 'Τρι 3η', performed_at: '2026-10-02T15:49:03' }] }),
    });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-history');
        app.doc.getElementById('tt-history').click();
        await waitFor(app.w, () => app.doc.querySelector('.hist-undo-to[data-id="9"]'));
        app.doc.querySelector('.hist-undo-to[data-id="9"]').click();
        await waitFor(app.w, () => /διάλειμμα/.test(app.doc.getElementById('modal-title').textContent));
        const before = solutionGets(app);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).includes('Σφάλμα <b>βάσης</b>'));
        await waitFor(app.w, () => solutionGets(app) > before);
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('χωρίς skip_break τα σφάλματα μένουν όπως πριν («μέχρι εδώ», «Επαναφορά όλων»)', async () => {
    const { routes } = timetableRoutes({
        'POST /api/solver/solutions/*/unplace-bulk': () => ({ message: 'Στην Παλέτα 2 ώρες', first_entry_id: 11 }),
        'POST /api/solver/solutions/*/history/undo-to/*': () => ({ __status: 409, data: { detail: 'Η θέση είναι πιασμένη' } }),
        'GET /api/solver/solutions/*/history': () => ({ items: [
            { id: 9, operation: 'move', operation_label: 'Μετακίνηση', undone: false, lesson: 'Φυσική',
              from: 'Δευ 1η', to: 'Τρι 3η', performed_at: '2026-10-02T15:49:03' }] }),
    });
    const app = await start(routes);
    try {
        // «μέχρι εδώ»: μήνυμα, το Ιστορικό μένει ανοιχτό, καμία νέα σχεδίαση
        await go(app, 'timetable', '#tt-history');
        app.doc.getElementById('tt-history').click();
        await waitFor(app.w, () => app.doc.querySelector('.hist-undo-to[data-id="9"]'));
        let before = solutionGets(app);
        app.doc.querySelector('.hist-undo-to[data-id="9"]').click();
        await waitFor(app.w, () => toastTexts(app).length === 1);
        await sleep(app.w, 40);
        assert.deepEqual(toastTexts(app), ['Η θέση είναι πιασμένη']);
        assert.equal(app.doc.getElementById('modal-title').textContent, '🕘 Ιστορικό αλλαγών');
        assert.equal(solutionGets(app), before);
        app.doc.getElementById('modal-close').click();

        // «Επαναφορά όλων»: μήνυμα, το παράθυρο μένει (το κουμπί ξαναενεργό)
        app.doc.getElementById('tt-empty').click();
        await waitFor(app.w, () => app.doc.getElementById('bu-target')?.options.length);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => app.doc.getElementById('modal-title').textContent === '✅ Έγινε');
        before = solutionGets(app);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => toastTexts(app).length === 2);
        await waitFor(app.w, () => !app.doc.getElementById('modal-save').disabled);
        assert.equal(toastTexts(app)[1], 'Η θέση είναι πιασμένη');
        assert.equal(app.doc.getElementById('modal-title').textContent, '✅ Έγινε');
        assert.equal(solutionGets(app), before);
    } finally { app.close(); }
});

test('το κείμενο «Παραλείφθηκαν… — δεν υπάρχει άλλη αλλαγή»: ενικός/πληθυντικός, χωρίς διπλό του server', async () => {
    const { routes } = timetableRoutes();
    const app = await start(routes);
    try {
        const V = app.G.TimetableView;
        assert.equal(V._skippedNothingLeftText(1, 'undo', 'Δεν υπάρχει αλλαγή προς αναίρεση'),
            'Παραλείφθηκε 1 αλλαγή σε ώρα που έγινε διάλειμμα — δεν υπάρχει άλλη αλλαγή προς αναίρεση.');
        assert.equal(V._skippedNothingLeftText(2, 'redo', ''),
            'Παραλείφθηκαν 2 αλλαγές σε ώρα που έγινε διάλειμμα — δεν υπάρχει άλλη αλλαγή προς επανάληψη.');
        // Ο server το λέει ήδη → το δικό του κείμενο (escaped), όχι και το δικό μας
        assert.equal(V._skippedNothingLeftText(2, 'undo', 'Παραλείφθηκαν 2 αλλαγές <b>x</b>'),
            'Παραλείφθηκαν 2 αλλαγές &lt;b&gt;x&lt;/b&gt;');
    } finally { app.close(); }
});
