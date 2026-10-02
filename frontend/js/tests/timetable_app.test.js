/**
 * Ωρολόγιο / «Σήμερα» σε full-app jsdom: ποιο πρόγραμμα ανοίγει, επαναφορά
 * αρχειοθετημένου, συνώνυμοι μαθητές, Παλέτα στην προβολή «Μαθητή», φίλτρα
 * Παλέτας μετά από αλλαγή σεναρίου, escaping ονομάτων.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, timetableRoutes, slot } = require('./app_harness.js');

const change = (app, el, value) => { el.value = value; el.dispatchEvent(new app.w.Event('change')); };

test('«Σήμερα» και Ωρολόγιο: ανοίγουν το κανονικό πρόγραμμα, όχι αποτυχημένη/τρέχουσα εκτέλεση', async () => {
    const { routes, state } = timetableRoutes();
    state.solutions.unshift({ id: 9, name: 'Δοκιμή που απέτυχε', status: 'error', created_at: '2026-10-01T18:00:00Z', archived: false, slots: [] });
    state.slots = [0, 1, 2, 3, 4, 5].map(d => slot(10 + d, { day_of_week: d, period_id: 1 }));
    const app = await start(routes, { hash: '#today' });
    try {
        await waitFor(app.w, () => app.doc.querySelector('.today-source'));
        assert.match(app.doc.querySelector('.today-source').textContent, /Χειμερινό/);
        assert.ok(!app.calls.some(c => c.path === '/api/solver/solutions/9'));

        await go(app, 'timetable', '#tt-solution');
        assert.equal(app.doc.getElementById('tt-solution').value, '7');
        assert.ok(app.doc.querySelectorAll('#timetable-grid-view .lesson-card').length > 0);

        // Ρητή επιλογή της αποτυχημένης από τη λίστα → ανοίγει (όπως πριν)
        change(app, app.doc.getElementById('tt-solution'), '9');
        await waitFor(app.w, () => app.doc.getElementById('tt-solution')?.value === '9');
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('αρχειοθετημένο πρόγραμμα: επιλογή από «📦 Αρχειοθετημένα» → ανοίγει με ♻️ και επαναφέρεται', async () => {
    const unarch = [];
    const { routes, state } = timetableRoutes({
        'POST /api/solver/solutions/*/unarchive': ({ path: p }) => {
            unarch.push(p);
            state.solutions.find(s => s.id === 3).archived = false;
            return { message: 'Επανήλθε' };
        },
    });
    state.solutions.push({ id: 3, name: 'Περσινό', status: 'optimal', created_at: '2025-09-20T10:00:00Z', archived: true, slots: [] });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-solution');
        assert.equal(app.doc.getElementById('tt-solution').value, '7', 'χωρίς επιλογή: το ενεργό');
        change(app, app.doc.getElementById('tt-solution'), '3');
        await waitFor(app.w, () => app.doc.getElementById('tt-solution')?.value === '3');
        assert.match(app.doc.querySelector('.card-title').textContent, /Περσινό/);
        assert.equal(app.doc.getElementById('tt-archive').textContent.trim(), '♻️');
        app.doc.getElementById('tt-archive').click();
        await waitFor(app.w, () => unarch.length === 1);
        assert.deepEqual(unarch, ['/api/solver/solutions/3/unarchive']);
        await waitFor(app.w, () => app.doc.getElementById('tt-archive')?.textContent.trim() === '📦');
        assert.equal(app.doc.getElementById('tt-solution').value, '3', 'μένει ανοιχτό μετά την επαναφορά');
    } finally { app.close(); }
});

test('συνώνυμοι μαθητές: δύο επιλογές, σωστό πλέγμα και σωστή εκτύπωση/ICS για τον καθένα', async () => {
    const { routes, state } = timetableRoutes({
        'GET /api/students/': () => [
            { id: 41, first_name: 'Γιώργος', last_name: 'Παπαδόπουλος', grade: 'Α΄ Λυκείου', class_ids: [11] },
            { id: 87, first_name: 'Γιώργος', last_name: 'Παπαδόπουλος', grade: 'Γ΄ Λυκείου', class_ids: [12] },
        ],
        'GET /api/lessons/rosters': () => ({ rosters: { 101: [41], 102: [87] } }),
    });
    state.slots = [
        slot(1, { lesson_id: 101, class_name: 'Α1', class_short: 'Α1' }),
        slot(2, { lesson_id: 102, day_of_week: 2, period_id: 2, class_name: 'Γ1', class_short: 'Γ1' }),
    ];
    const app = await start(routes);
    const opened = [];
    app.w.open = (u) => { opened.push(u); return null; };
    try {
        await go(app, 'timetable', '#tt-view-type');
        change(app, app.doc.getElementById('tt-view-type'), 'student');
        const f = app.doc.getElementById('tt-filter');
        const labels = [...f.options].map(o => o.textContent);
        assert.deepEqual(labels.slice(1).sort(), ['Παπαδόπουλος Γιώργος (Α΄ Λυκείου)', 'Παπαδόπουλος Γιώργος (Γ΄ Λυκείου)']);
        const cards = () => [...app.doc.querySelectorAll('#timetable-grid-view .lesson-card .teacher-name')].map(e => e.textContent.trim());
        change(app, f, 'Παπαδόπουλος Γιώργος (Α΄ Λυκείου)');
        assert.deepEqual(cards(), ['Α1']);
        app.doc.getElementById('tt-ics').click();
        change(app, f, 'Παπαδόπουλος Γιώργος (Γ΄ Λυκείου)');
        assert.deepEqual(cards(), ['Γ1']);
        app.doc.getElementById('tt-print').click();
        assert.deepEqual(opened, [
            '/api/exports/ics?solution_id=7&student_id=41',
            '/api/exports/print?solution_id=7&student_id=87',
        ]);
    } finally { app.close(); }
});

test('προβολή «Μαθητή»: δύο συρσίματα από την Παλέτα τοποθετούν ΔΥΟ διαφορετικές ώρες', async () => {
    const puts = [];
    const { routes, state } = timetableRoutes({
        'GET /api/lessons/rosters': () => ({ rosters: { 101: [1] } }),
        'GET /api/lessons/': () => [
            { id: 101, subject_name: 'Φυσική', class_name: 'Β2', teacher_name: 'Νικολάου', periods_per_week: 1 },
            { id: 105, subject_name: 'Χημεία', class_name: 'Γ1', teacher_name: 'Παππάς', periods_per_week: 2 },
        ],
        'PUT /api/solver/solutions/*/slots/*': ({ path: p, body }) => {
            const id = +p.split('/').pop();
            puts.push(`${id}→d${body.day_of_week}/p${body.period_id}`);
            return { slot: { id, classroom_id: 1, classroom_name: 'Αίθ 1' } };
        },
        'GET /api/solver/solutions/*/slots/*/placement-map': () => ({ cells: [] }),
    });
    const chem = { lesson_id: 105, subject_name: 'Χημεία', subject_short: 'ΧΗΜ', class_name: 'Γ1', class_short: 'Γ1', class_id: 12,
        teacher_name: 'Παππάς', teacher_short: 'ΠΑΠ', teacher_id: 22, is_unplaced: true, day_of_week: null, period_id: null,
        classroom_id: null, classroom_name: null, students: [] };
    state.slots = [slot(1, { lesson_id: 101 }), slot(5, chem), slot(6, { ...chem })];
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-view-type');
        change(app, app.doc.getElementById('tt-view-type'), 'student');
        change(app, app.doc.getElementById('tt-filter'), 'Παπαδόπουλος Νίκος');
        const pcard = () => [...app.doc.querySelectorAll('.lesson-palette .palette-card')].find(c => c.dataset.lessonId === '105');
        const drop = async (day, period) => {
            const id = pcard().dataset.slotId;
            const dt = { _d: {}, setData(k, v) { this._d[k] = String(v); }, getData(k) { return this._d[k]; }, effectAllowed: '', dropEffect: '' };
            app.G.TimetableGrid.handleDragStart({ dataTransfer: dt, target: pcard() }, +id);
            const cell = app.doc.querySelector(`#timetable-grid-view td.droppable-cell[data-day="${day}"][data-period="${period}"]`);
            await app.G.TimetableGrid.handleDrop({ preventDefault() {}, dataTransfer: dt, target: cell }, 7);
            await sleep(app.w, 10);
        };
        await drop(2, 1);
        assert.match(pcard().querySelector('.palette-badge').textContent, /×1/);
        assert.equal(pcard().dataset.slotId, '6');
        await drop(3, 2);
        assert.deepEqual(puts, ['5→d2/p1', '6→d3/p2']);
        assert.equal(state.slots.find(s => s.id === 5).is_unplaced, false);
        assert.equal(state.slots.find(s => s.id === 6).is_unplaced, false);
    } finally { app.close(); }
});

test('Παλέτα: φίλτρο καθηγητή που δεν υπάρχει στο νέο σενάριο καθαρίζει (όχι «άδεια» Παλέτα)', async () => {
    let term = 1;
    const unplaced = (id, extra) => slot(id, { is_unplaced: true, day_of_week: null, period_id: null, ...extra });
    const { routes, state } = timetableRoutes({
        'GET /api/terms/': () => [{ id: 1, name: 'Χειμ', is_active: term === 1 }, { id: 2, name: 'Θερινό', is_active: term === 2 }],
        'POST /api/terms/*/activate': ({ path: p }) => { term = +p.split('/')[3]; return { id: term, is_active: true }; },
        'GET /api/solver/solutions': () => state.solutions.filter(s => (term === 1 ? s.id === 7 : s.id === 8)),
    });
    state.solutions.push({ id: 8, name: 'Θερινό πρόγρ.', status: 'optimal', created_at: '2026-06-20T10:00:00Z', archived: false,
        slots: [unplaced(31, { solution_id: 8, lesson_id: 301, teacher_name: 'Ζαχαρίου' })] });
    state.slots = [unplaced(1, { lesson_id: 101 }), unplaced(2, { lesson_id: 102, teacher_name: 'Παππάς' })];
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#palette-f-teacher');
        const visible = () => [...app.doc.querySelectorAll('.lesson-palette .palette-card')].filter(c => c.style.display !== 'none').length;
        change(app, app.doc.getElementById('palette-f-teacher'), 'Νικολάου');
        assert.equal(visible(), 1);
        // Ίδιο σενάριο, re-render (π.χ. drop): το φίλτρο ΜΕΝΕΙ
        app.G.TimetableView.refreshPalette();
        assert.equal(app.doc.getElementById('palette-f-teacher').value, 'Νικολάου');
        assert.equal(visible(), 1);

        change(app, app.doc.getElementById('term-selector'), '2');
        await waitFor(app.w, () => /Θερινό πρόγρ/.test(app.doc.querySelector('.card-title')?.textContent || '')
            && app.doc.getElementById('palette-f-teacher'));
        assert.equal(app.doc.getElementById('palette-f-teacher').value, '');
        assert.equal(visible(), 1);
        assert.equal(app.doc.querySelector('.lesson-palette .palette-empty-msg').style.display, 'none');
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('ονόματα με HTML/εισαγωγικά: escaped στο πλέγμα, ακέραια στις φόρμες', async () => {
    const payload = '<img src=x data-pwn=1>Ιγνάτης';
    const teachers = [{ id: 21, name: 'Γιάννης "Τζον" Π.', short_name: 'Γ"Π', email: 'a"b@x.gr', phone: '', color: '#000000' }];
    const puts = [];
    const { routes, state } = timetableRoutes({
        'GET /api/teachers/': () => teachers,
        'PUT /api/teachers/*': ({ body }) => { puts.push(body); return { ...teachers[0], ...body }; },
    });
    state.slots = [slot(1, { students: [payload], subject_short: '<b>ΦΥΣ</b>' })];
    state.solutions[0].name = 'Χειμ <i>2026</i>';
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-view-type');
        assert.equal(app.doc.querySelector('.card-title i'), null);
        assert.match(app.doc.querySelector('.card-title').textContent, /Χειμ <i>2026<\/i>/);
        for (const vt of ['class', 'teacher']) {
            change(app, app.doc.getElementById('tt-view-type'), vt);
            assert.equal(app.doc.querySelector('#timetable-grid-view img'), null, vt);
            assert.equal(app.doc.querySelector('#timetable-grid-view .subject-name b'), null, vt);
            assert.match(app.doc.querySelector('#timetable-grid-view .subject-name').textContent, /<b>ΦΥΣ<\/b>/);
        }
        assert.match(app.doc.querySelector('#timetable-grid-view .teacher-name').textContent, /<img src=x data-pwn=1>Ιγνάτης/);

        await go(app, 'teachers', '.dt-edit[data-id="21"]');
        app.doc.querySelector('.dt-edit[data-id="21"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-name'));
        assert.equal(app.doc.getElementById('f-name').value, 'Γιάννης "Τζον" Π.');
        assert.equal(app.doc.getElementById('f-short_name').value, 'Γ"Π');
        assert.equal(app.doc.getElementById('f-email').value, 'a"b@x.gr');
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => puts.length === 1);
        assert.equal(puts[0].name, 'Γιάννης "Τζον" Π.');
        assert.equal(puts[0].short_name, 'Γ"Π');
        await sleep(app.w, 30);
    } finally { app.close(); }
});
