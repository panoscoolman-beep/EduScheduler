/**
 * Γύρος «Εφαρμογή και εμπειρία χρήσης» (EF-*): Κωλύματα που δεν φαίνονται στο
 * πλέγμα, προστασία φόρμας στα κελιά, παράθυρο που δεν ξανανοίγει μόνο του,
 * φίλτρο Ωρολογίου μετά από re-render, αργό φόρτωμα που δεν γράφει σε άλλη
 * σελίδα, κάρτα από την Παλέτα, «Σήμερα» με ανοιχτές ομάδες, ένδειξη solver,
 * μήνυμα δικτύου, πληκτρολόγιο στις κάρτες, Ρυθμίσεις με 7 ημέρες, λεζάντα εκτύπωσης.
 * Full-app jsdom (πραγματικό index.html + scripts, ψεύτικο backend).
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes, timetableRoutes, slot } = require('./app_harness.js');

const T = require('../views/today_helpers.js');

const change = (app, el, value) => { el.value = value; el.dispatchEvent(new app.w.Event('change')); };
const overlayOpen = (app) => app.doc.getElementById('modal-overlay').classList.contains('active');

// ─── Κωλύματα ────────────────────────────────────────────────────────────

const TEACHER = { id: 21, name: 'Νικολάου', short_name: 'ΝΙΚ', email: '', phone: '', color: '#3B82F6' };

/** Backend με 5 ημέρες, 2 διδακτικές ώρες + 1 διάλειμμα, και κωλύματα εκτός πλέγματος. */
function availabilityApp(over = {}) {
    const puts = [];
    const rows = [
        { id: 1, day_of_week: 0, period_id: 1, status: 'unavailable' },   // φαίνεται
        { id: 2, day_of_week: 5, period_id: 1, status: 'unavailable' },   // Σάββατο: δεν φαίνεται (5 ημέρες)
        { id: 3, day_of_week: 1, period_id: 9, status: 'unavailable' },   // ώρα-διάλειμμα: δεν φαίνεται
        { id: 4, day_of_week: 2, period_id: 99, status: 'unavailable' },  // ώρα που δεν υπάρχει πια
    ];
    const routes = baseRoutes(Object.assign({
        'GET /api/teachers/': () => [TEACHER],
        'GET /api/periods/': () => [
            { id: 1, name: '1η', short_name: '1η', start_time: '16:00', end_time: '17:00', is_break: false, sort_order: 1 },
            { id: 9, name: 'Δ', short_name: 'Δ', start_time: '17:00', end_time: '17:10', is_break: true, sort_order: 2 },
            { id: 2, name: '2η', short_name: '2η', start_time: '17:10', end_time: '18:10', is_break: false, sort_order: 3 },
        ],
        'GET /api/teachers/*/availability': () => rows,
        'PUT /api/teachers/*/availability': ({ body }) => { puts.push(body); return []; },
    }, over));
    return { routes, puts };
}

async function openAvailability(app) {
    await go(app, 'teachers', '.dt-custom[data-action="availability"][data-id="21"]');
    app.doc.querySelector('.dt-custom[data-action="availability"][data-id="21"]').click();
    await waitFor(app.w, () => app.doc.getElementById('avail-table'));
}

test('Κωλύματα: όσα δεν φαίνονται στο πλέγμα ξαναστέλνονται ως έχουν στην αποθήκευση', async () => {
    const be = availabilityApp();
    const app = await start(be.routes);
    try {
        await openAvailability(app);
        assert.equal(app.doc.querySelectorAll('#avail-table tbody tr').length, 2, 'μόνο διδακτικές ώρες');
        assert.equal(app.doc.querySelectorAll('#avail-table thead th').length, 1 + 5, 'μόνο 5 ημέρες');
        assert.match(app.doc.getElementById('avail-hidden-note').textContent,
            /Διατηρούνται 2 κωλύματα σε ημέρες\/ώρες που δεν εμφανίζονται/);
        // Ένα νέο κώλυμα στο πλέγμα, και αποθήκευση.
        app.doc.querySelector('.avail-cell[data-day="1"][data-period="2"]').click();
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => be.puts.length === 1);
        const sent = be.puts[0].availabilities.map(a => `${a.day_of_week}/${a.period_id}/${a.status}`).sort();
        assert.deepEqual(sent, ['0/1/unavailable', '1/2/unavailable', '1/9/unavailable', '5/1/unavailable']);
        await waitFor(app.w, () => !overlayOpen(app));
    } finally { app.close(); }
});

test('Κωλύματα: μετά από κλικ σε κελί, πάτημα έξω / Esc ρωτούν πριν κλείσουν', async () => {
    const be = availabilityApp();
    const app = await start(be.routes);
    try {
        await openAvailability(app);
        // Χωρίς αλλαγές: πάτημα έξω κλείνει όπως πριν.
        app.doc.getElementById('modal-overlay').click();
        await waitFor(app.w, () => !overlayOpen(app));

        await openAvailability(app);
        app.doc.querySelector('.avail-cell[data-day="0"][data-period="2"]').click();
        app.doc.getElementById('modal-overlay').click();
        assert.ok(overlayOpen(app), 'μένει ανοιχτό');
        const bar = app.doc.getElementById('modal-discard');
        assert.equal(bar.hidden, false, 'ρωτά «Να κλείσει χωρίς αποθήκευση;»');
        bar.querySelector('[data-discard="keep"]').click();
        app.doc.dispatchEvent(new app.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        assert.equal(bar.hidden, false);
        bar.querySelector('[data-discard="drop"]').click();
        assert.ok(!overlayOpen(app));
        assert.equal(be.puts.length, 0);
    } finally { app.close(); }
});

test('Κωλύματα: όσο φορτώνει δεν υπάρχει «Αποθήκευση», και δεν ξανανοίγει αν ο χρήστης το έκλεισε', async () => {
    let release;
    const be = availabilityApp({
        'GET /api/teachers/*/availability': () => new Promise(r => { release = r; }),
    });
    const app = await start(be.routes);
    try {
        await go(app, 'teachers', '.dt-custom[data-action="availability"][data-id="21"]');
        app.doc.querySelector('.dt-custom[data-action="availability"][data-id="21"]').click();
        await waitFor(app.w, () => overlayOpen(app) && typeof release === 'function');
        const footer = app.doc.getElementById('modal-save').parentElement;
        assert.equal(footer.style.display, 'none', 'χωρίς «Αποθήκευση» στο «Φόρτωση...»');
        // Ο χρήστης κλείνει πριν έρθει η απάντηση.
        app.doc.getElementById('modal-close').click();
        assert.ok(!overlayOpen(app));
        release([]);
        await sleep(app.w, 40);
        assert.ok(!overlayOpen(app), 'το πλέγμα δεν ξανανοίγει μόνο του');
        assert.equal(app.doc.getElementById('avail-table'), null);
    } finally { app.close(); }
});

// ─── Ωρολόγιο ────────────────────────────────────────────────────────────

test('Ωρολόγιο: προβολή ΚΑΙ φίλτρο επιβιώνουν το πλήρες re-render (undo)· αλλαγή προβολής = «Όλα»', async () => {
    const { routes, state } = timetableRoutes();
    state.slots = [slot(1), slot(2, { day_of_week: 1, period_id: 2, teacher_name: 'Παππάς', teacher_short: 'ΠΑΠ', teacher_id: 22 })];
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-view-type');
        change(app, app.doc.getElementById('tt-view-type'), 'teacher');
        change(app, app.doc.getElementById('tt-filter'), 'Παππάς');
        const cards = () => [...app.doc.querySelectorAll('#timetable-grid-view .lesson-card')].map(c => c.dataset.slotId);
        assert.deepEqual(cards(), ['2']);
        // Undo → πλήρες re-render της σελίδας
        const before = app.doc.getElementById('tt-view-type');
        await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled);
        app.doc.getElementById('tt-undo').click();
        await waitFor(app.w, () => state.undoCalls === 1 && app.doc.getElementById('tt-view-type')
            && app.doc.getElementById('tt-view-type') !== before && app.doc.getElementById('tt-filter'));
        await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled);
        assert.equal(app.doc.getElementById('tt-view-type').value, 'teacher');
        assert.equal(app.doc.getElementById('tt-filter').value, 'Παππάς', 'το φίλτρο δεν γύρισε σε «Όλα»');
        assert.deepEqual(cards(), ['2'], 'το πλέγμα δείχνει το φίλτρο');
        // Αλλαγή προβολής από τον χρήστη: το φίλτρο ξεκινά από «Όλα».
        change(app, app.doc.getElementById('tt-view-type'), 'class');
        assert.equal(app.doc.getElementById('tt-filter').value, 'all');
        assert.deepEqual(cards().sort(), ['1', '2']);
        // Φίλτρο «Τμήμα» (χωρίς change προβολής) επιβιώνει κι αυτό.
        change(app, app.doc.getElementById('tt-filter'), 'Β2');
        const before2 = app.doc.getElementById('tt-view-type');
        app.doc.getElementById('tt-undo').click();
        await waitFor(app.w, () => state.undoCalls === 2 && app.doc.getElementById('tt-filter')
            && app.doc.getElementById('tt-view-type') !== before2);
        await waitFor(app.w, () => !app.doc.getElementById('tt-undo').disabled);
        assert.equal(app.doc.getElementById('tt-filter').value, 'Β2');
    } finally { app.close(); }
});

test('αργό φόρτωμα Ωρολογίου δεν γράφει πάνω στη σελίδα που άνοιξε ο χρήστης στο μεταξύ', async () => {
    let slow = false;
    let release;
    const { routes } = timetableRoutes({
        'GET /api/solver/solutions/*': ({ path: p }) => {
            const s = { id: +p.split('/').pop(), name: 'Χειμερινό', status: 'optimal', archived: false, slots: [slot(1)] };
            if (!slow) return s;                               // ο Πίνακας Ελέγχου στην εκκίνηση
            return new Promise(r => { release = () => r(s); });
        },
        'GET /api/teachers/': () => [TEACHER],
    });
    const app = await start(routes);
    try {
        slow = true;
        app.G.App.navigateTo('timetable');
        await waitFor(app.w, () => typeof release === 'function');
        await go(app, 'teachers', '.dt-edit[data-id="21"]');
        release();
        await sleep(app.w, 60);
        assert.equal(app.G.App._currentView, 'teachers');
        assert.ok(app.doc.querySelector('#content-area .dt-edit[data-id="21"]'), 'οι Καθηγητές έμειναν');
        assert.equal(app.doc.getElementById('tt-solution'), null, 'κανένα Ωρολόγιο πάνω τους');
    } finally { app.close(); }
});

test('αποτυχία φόρτωσης Ωρολογίου: «Δοκίμασε ξανά» αντί για σκέτο «Σφάλμα»', async () => {
    let fail = true;
    const { routes } = timetableRoutes({
        'GET /api/periods/': () => (fail ? { __status: 503, data: { detail: 'Η βάση δεν απαντά' } } : baseRoutes()['GET /api/periods/']()),
    });
    const app = await start(routes);
    try {
        app.G.App.navigateTo('timetable');
        await waitFor(app.w, () => app.doc.querySelector('#content-area [data-retry]'));
        assert.match(app.doc.getElementById('content-area').textContent, /Η βάση δεν απαντά/);
        fail = false;
        app.doc.querySelector('#content-area [data-retry]').click();
        await waitFor(app.w, () => app.doc.getElementById('tt-solution'));
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('κάρτα από την Παλέτα: μετά το σύρσιμο ντύνεται σαν κάρτα πλέγματος (🔒 και αίθουσα)', async () => {
    const { routes, state } = timetableRoutes({
        'GET /api/lessons/': () => [
            { id: 101, subject_name: 'Φυσική', class_name: 'Β2', teacher_name: 'Νικολάου', periods_per_week: 1 },
            { id: 105, subject_name: 'Χημεία', class_name: 'Γ1', teacher_name: 'Παππάς', periods_per_week: 1 },
        ],
        'PUT /api/solver/solutions/*/slots/*': ({ path: p }) =>
            ({ slot: { id: +p.split('/').pop(), classroom_id: 1, classroom_name: 'Αίθ 1' } }),
        'GET /api/solver/solutions/*/slots/*/placement-map': () => ({ cells: [] }),
    });
    state.slots = [slot(1), slot(5, { lesson_id: 105, subject_name: 'Χημεία', subject_short: 'ΧΗΜ', class_name: 'Γ1', class_short: 'Γ1',
        class_id: 12, teacher_name: 'Παππάς', teacher_short: 'ΠΑΠ', teacher_id: 22, is_unplaced: true, day_of_week: null,
        period_id: null, classroom_id: null, classroom_name: null, students: [] })];
    const app = await start(routes);
    try {
        await go(app, 'timetable', '.lesson-palette .palette-card');
        const pcard = app.doc.querySelector('.lesson-palette .palette-card[data-lesson-id="105"]');
        const dt = { _d: {}, setData(k, v) { this._d[k] = String(v); }, getData(k) { return this._d[k]; }, effectAllowed: '', dropEffect: '' };
        app.G.TimetableGrid.handleDragStart({ dataTransfer: dt, target: pcard }, 5);
        const cell = app.doc.querySelector('#timetable-grid-view td.droppable-cell[data-day="2"][data-period="1"]');
        await app.G.TimetableGrid.handleDrop({ preventDefault() {}, dataTransfer: dt, target: cell }, 7);
        await sleep(app.w, 20);
        const card = app.doc.querySelector('#timetable-grid-view .lesson-card[data-slot-id="5"]');
        assert.ok(card, 'η κάρτα είναι στο πλέγμα');
        assert.ok(!card.classList.contains('palette-card') && !card.classList.contains('parking-card'));
        assert.ok(card.querySelector('.lesson-lock-btn'), 'έχει 🔒');
        assert.equal(card.querySelector('.room-name').textContent.trim(), 'Αίθ 1');
        assert.equal(app.G.TimetableGrid._dragSlotId, null, 'το drag state καθαρίστηκε');
    } finally { app.close(); }
});

test('⏳ όσο υπολογίζεται πρόγραμμα: ένδειξη και απενεργά «Γέμισε τα κενά» / «Κράτα τα κλειδωμένα»', async () => {
    const { routes, state } = timetableRoutes();
    state.solutions.push({ id: 8, name: 'Νέο', status: 'generating', created_at: '2026-10-27T10:00:00Z', archived: false, slots: [] });
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-solution');
        assert.equal(app.doc.getElementById('tt-solver-running').hidden, false);
        assert.match(app.doc.getElementById('tt-solver-running').textContent, /Υπολογίζεται νέο πρόγραμμα/);
        assert.equal(app.doc.getElementById('tt-fill').disabled, true);
        assert.equal(app.doc.getElementById('tt-regen').disabled, true);
        state.solutions.pop();
        change(app, app.doc.getElementById('tt-solution'), '7');
        await waitFor(app.w, () => app.doc.getElementById('tt-solver-running')?.hidden === true);
        assert.equal(app.doc.getElementById('tt-fill').disabled, false);
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('κάρτες του πλέγματος ανοίγουν με Enter/Space από το πληκτρολόγιο, όχι από το 🔒 μέσα τους', async () => {
    const { routes } = timetableRoutes();
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#timetable-grid-view .lesson-card');
        const card = app.doc.querySelector('#timetable-grid-view .lesson-card[data-slot-id="1"]');
        assert.equal(card.getAttribute('tabindex'), '0');
        assert.match(card.getAttribute('aria-label'), /ΦΥΣ/);
        assert.equal(card.getAttribute('role'), null, 'όχι role="button" γύρω από άλλο κουμπί');
        card.dispatchEvent(new app.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        await waitFor(app.w, () => overlayOpen(app) && app.doc.querySelector('.ls-when'));
        app.doc.getElementById('modal-close').click();
        // Space από το κουμπί 🔒: δεν ανοίγει τις πληροφορίες.
        card.querySelector('.lesson-lock-btn').dispatchEvent(new app.w.KeyboardEvent('keydown', { key: ' ', bubbles: true }));
        await sleep(app.w, 20);
        assert.ok(!overlayOpen(app));
        const ev = new app.w.KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
        card.dispatchEvent(ev);
        assert.equal(ev.defaultPrevented, true, 'το Space δεν κάνει scroll');
        await waitFor(app.w, () => overlayOpen(app));
        app.doc.getElementById('modal-close').click();
    } finally { app.close(); }
});

test('εκτύπωση Ωρολογίου: λεζάντα με πρόγραμμα, προβολή και φίλτρο', async () => {
    const { routes } = timetableRoutes();
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-print');
        change(app, app.doc.getElementById('tt-filter'), 'Β2');
        app.doc.getElementById('tt-print').click();
        assert.equal(app.doc.getElementById('tt-print-caption').textContent, 'Χειμερινό · Τμήμα · Β2');
        change(app, app.doc.getElementById('tt-view-type'), 'overview_teacher');
        app.doc.getElementById('tt-print').click();
        assert.equal(app.doc.getElementById('tt-print-caption').textContent, 'Χειμερινό · Συνολική: Καθηγητές × Ώρες');
    } finally { app.close(); }
});

// ─── Σήμερα ──────────────────────────────────────────────────────────────

test('Σήμερα: ομάδα επόμενων ωρών που άνοιξε μένει ανοιχτή στο ανανέωμα του λεπτού', async () => {
    const day = T.schoolDate(0).day;
    const { routes, state } = timetableRoutes();
    state.slots = [1, 2, 3].map(p => slot(p, { day_of_week: day, period_id: p }));
    const app = await start(routes, { hash: '#today' });
    try {
        app.G.TodayHelpers.nowHHMM = () => '16:30';    // 1η τώρα, 2η ακολουθεί, 3η μαζεμένη
        app.G.TodayView._draw();
        const details = app.doc.querySelector('#today-list details.today-group');
        assert.ok(details, 'η 18:00 είναι μαζεμένη');
        assert.equal(details.open, false);
        details.open = true;
        app.G.TodayView._draw();                        // ό,τι κάνει ο χρονοδιακόπτης
        const again = app.doc.querySelector('#today-list details.today-group');
        assert.notEqual(again, details, 'ξανασχεδιάστηκε');
        assert.equal(again.open, true, 'έμεινε ανοιχτή');
    } finally { app.close(); }
});

// ─── Δίκτυο ──────────────────────────────────────────────────────────────

test('χωρίς δίκτυο: ελληνικό μήνυμα με err.network, όχι «Failed to fetch»', async () => {
    const app = await start(baseRoutes());
    try {
        const original = new TypeError('Failed to fetch');
        app.w.fetch = async () => { throw original; };
        await assert.rejects(app.G.API.get('/teachers/'), (err) => {
            assert.equal(err.network, true);
            assert.equal(err.cause, original);
            assert.match(err.message, /Δεν υπάρχει σύνδεση με τον διακομιστή/);
            assert.doesNotMatch(err.message, /Failed to fetch/);
            return true;
        });
    } finally { app.close(); }
});

// ─── Ρυθμίσεις ───────────────────────────────────────────────────────────

test('Ρυθμίσεις: αποθηκευμένες 7 ημέρες δεν γίνονται σιωπηλά 5', async () => {
    const app = await start(baseRoutes({
        'GET /api/settings/': () => ({ days_per_week: 7, school_name: 'Κορυφή' }),
        'GET /api/settings/templates': () => [],
    }));
    try {
        await go(app, 'settings', '#s-days');
        assert.equal(app.doc.getElementById('s-days').value, '7');
        assert.match(app.doc.querySelector('#s-days option[value="7"]').textContent, /τρέχουσα ρύθμιση/);
        await sleep(app.w, 20);
    } finally { app.close(); }
});
