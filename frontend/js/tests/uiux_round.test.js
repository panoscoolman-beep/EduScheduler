/**
 * Γύρος UI/UX (Π3, Π4, Π6, Π7, Π9 + μικρότερα): καθαρές συναρτήσεις και
 * ροές σε ολόκληρη την εφαρμογή (jsdom, ψεύτικο backend).
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const { start, go, sleep, waitFor, baseRoutes, timetableRoutes, slot } = require('./app_harness.js');

const H = require('../views/timetable_helpers.js');
const T = require('../views/today_helpers.js');
const Appearance = require('../appearance.js');
const Contact = require('../components/contact.js');

const change = (app, el, value) => { el.value = value; el.dispatchEvent(new app.w.Event('change')); };
const overlayOpen = (app) => app.doc.getElementById('modal-overlay').classList.contains('active');

// ─── Καθαρές συναρτήσεις ──────────────────────────────────────────────────

test('statusInfo: «feasible» = ✓ Εφικτό (πράσινο), όχι αγγλικά σε κόκκινο', () => {
    assert.deepEqual([H.statusInfo('feasible').label, H.statusInfo('feasible').cls], ['✓ Εφικτό', 'ok']);
    assert.equal(H.statusInfo('optimal').label, '★ Βέλτιστο');
    assert.equal(H.statusInfo('infeasible').cls, 'bad');
    assert.equal(H.statusInfo('error').cls, 'bad');
    assert.equal(H.statusInfo('κάτι').label, 'κάτι');
    assert.equal(H.statusInfo(null).label, '—');
});

test('publicationState: δημοσιευμένο / αλλαγές μετά / άλλο πρόγραμμα / ποτέ', () => {
    const prev = { solution_id: 7, solution_name: 'Χειμ', published_at: '2026-10-24T09:00:00' };
    assert.equal(H.publicationState(null, 7), null);
    const same = H.publicationState({ affected: 0, previous: prev }, 7);
    assert.equal(same.cls, 'ok');
    assert.match(same.text, /📢 Δημοσιευμένο · 24\/10/);
    const changed = H.publicationState({ affected: 3, previous: prev }, 7);
    assert.equal(changed.changes, 3);
    assert.match(changed.text, /Αλλαγές για 3 καθηγητές μετά τη δημοσίευση της 24\/10/);
    assert.match(H.publicationState({ affected: 1, previous: prev }, 7).text, /για 1 καθηγητή /);
    const other = H.publicationState({ affected: 2, previous: prev }, 9);
    assert.match(other.text, /Δημοσιευμένο είναι το «Χειμ» · διαφέρει για 2 καθηγητές/);
    assert.match(H.publicationState({ affected: 0, previous: prev }, 9).text, /Ίδιο με το δημοσιευμένο/);
    const never = H.publicationState({ first: true, affected: 4, previous: null }, 7);
    assert.equal(never.changes, 4);
    assert.match(never.text, /Δεν έχει δημοσιευτεί/);
});

test('buildMoveChoicesHtml: ελεύθερες πρώτα, η τρέχουσα θέση έξω, αιτίες με escaping', () => {
    const periods = [
        { id: 1, start_time: '16:00', end_time: '17:00', sort_order: 1 },
        { id: 2, start_time: '17:00', end_time: '18:00', sort_order: 2 },
    ];
    const map = { slot_id: 5, cells: [
        { day: 0, period_id: 1, ok: true },                                  // η τρέχουσα — έξω
        { day: 1, period_id: 2, ok: true },
        { day: 0, period_id: 2, ok: false, reason: 'Ο <b>Νικολάου</b> διδάσκει' },
        { day: 2, period_id: 99, ok: true },                                 // άγνωστη ώρα — έξω
    ] };
    const html = H.buildMoveChoicesHtml(map, periods, { day_of_week: 0, period_id: 1 });
    assert.equal((html.match(/data-move-day=/g) || []).length, 1);
    assert.match(html, /data-move-day="1" data-move-period="2"/);
    assert.match(html, /Τρίτη 17:00–18:00/);
    assert.match(html, /Ο &lt;b&gt;Νικολάου&lt;\/b&gt; διδάσκει/);
    assert.match(html, /1 ελεύθερες θέσεις/);
    const none = H.buildMoveChoicesHtml({ cells: [{ day: 0, period_id: 2, ok: false, reason: 'x' }] }, periods, {});
    assert.match(none, /Καμία ελεύθερη θέση/);
    assert.match(none, /<details class="move-blocked" open>/);
});

test('Σήμερα: λεπτά που απομένουν, τρέχουσα ώρα, ελεύθερα τώρα', () => {
    assert.equal(T.durationText(26), '26′');
    assert.equal(T.durationText(60), '1 ώρα');
    assert.equal(T.durationText(135), '2 ώρες 15′');
    const P = [
        { id: 1, start_time: '16:00', end_time: '17:00' },
        { id: 2, start_time: '17:00', end_time: '18:00' },
        { id: 3, start_time: '18:00', end_time: '19:00' },
        { id: 9, start_time: '17:00', end_time: '17:10', is_break: true },
    ];
    assert.equal(T.currentPeriod(P, '17:05').id, 2);                         // όχι το διάλειμμα
    assert.equal(T.currentPeriod(P, '20:00'), null);
    const S = [
        { day_of_week: 1, period_id: 2, teacher_name: 'Α', classroom_name: 'Αίθ 1' },
        { day_of_week: 1, period_id: 3, teacher_name: 'Β', classroom_name: 'Αίθ 2' },
        { day_of_week: 1, period_id: 1, teacher_name: 'Γ', classroom_name: 'Αίθ 2' },   // τελείωσε
        { day_of_week: 2, period_id: 2, teacher_name: 'Δ', classroom_name: 'Αίθ 3' },   // άλλη μέρα
    ];
    const rooms = [{ name: 'Αίθ 1' }, { name: 'Αίθ 2' }, { name: 'Αίθ 3' }, { name: 'Παλιά', archived: true }];
    const free = T.freeNow(S, P, rooms, 1, '17:30');
    assert.deepEqual(free.rooms, [{ name: 'Αίθ 2', until: '18:00' }, { name: 'Αίθ 3', until: null }]);
    assert.deepEqual(free.teachers, [{ name: 'Β', until: '18:00' }]);      // ο Γ τελείωσε, ο Α διδάσκει
    assert.equal(T.freeNow(S, P, rooms, 1, '21:00'), null);
    assert.match(T.freeHtml(free), /ως 18:00/);
    assert.match(T.freeHtml(free), /όλη τη μέρα/);
});

test('Σήμερα: «λήγει σε», «σε», μαζεμένες επόμενες ώρες, γραμματική', () => {
    const P = [
        { id: 1, start_time: '16:00', end_time: '17:00' },
        { id: 2, start_time: '17:00', end_time: '18:00' },
        { id: 3, start_time: '18:00', end_time: '19:00' },
    ];
    const S = [1, 2, 3].map(p => ({ id: p, day_of_week: 0, period_id: p, subject_name: 'Μ', classroom_name: 'Α' }));
    const html = T.buildHtml(T.buildDay(S, P, 0, '16:34'), { now: '16:34' });
    assert.match(html, /🟢 Τώρα · 16:00–17:00/);
    assert.match(html, /λήγει σε 26′/);
    assert.match(html, /⏭ Ακολουθεί · 17:00–18:00/);
    assert.match(html, /σε 26′/);
    assert.match(html, /<details class="today-group ">/);                   // 18:00 μαζεμένη
    assert.match(html, /1 μάθημα</);
    const other = T.buildHtml(T.buildDay(S, P, 0, null));
    assert.doesNotMatch(other, /<details/);                                   // άλλη μέρα: όλα ανοιχτά
    assert.match(T.buildHtml(T.buildDay(S, P, 0, '20:00'), { now: '20:00' }), /3 ώρες έχουν ήδη ολοκληρωθεί/);
});

test('pickSolution: το δημοσιευμένο αν υπάρχει στη λίστα, αλλιώς το προεπιλεγμένο', () => {
    const sols = [{ id: 9 }, { id: 7 }, { id: 3, archived: true }];
    assert.deepEqual(T.pickSolution(sols, [{ solution_id: 7, published_at: 'x' }], null, 9),
        { id: 7, published: true, publishedAt: 'x' });
    assert.equal(T.pickSolution(sols, [{ solution_id: 3 }], null, 9).id, 9);     // αρχειοθετημένο
    assert.deepEqual(T.pickSolution(sols, [], null, 9), { id: 9, published: false, publishedAt: null });
});

test('Μήνυμα αντικαταστάτη: μικρό όνομα, συνεχόμενες ώρες ενωμένες', () => {
    const msg = T.substituteMessage('ΕΛΕΝΗ ΦΩΤΙΟΥ', 'Δημήτρης Σ.', [
        { start: '18:00', end: '19:00', subject: 'Φυσική', class: 'Β΄', room: 'Αίθουσα 2' },
        { start: '17:00', end: '18:00', subject: 'Φυσική', class: 'Β΄', room: 'Αίθουσα 2' },
        { start: '20:00', end: '21:00', subject: 'Χημεία', class: '', room: '' },
    ], 'αύριο');
    assert.equal(msg, 'Καλησπέρα ΕΛΕΝΗ! Μπορείς αύριο 17:00–19:00 Φυσική (Β΄) στην Αίθουσα 2 και '
        + '20:00–21:00 Χημεία, αντί για Δημήτρης Σ.; Ευχαριστώ!');
});

test('countConflicts: διπλός καθηγητής/αίθουσα/τμήμα την ίδια ώρα', () => {
    const S = [
        { day_of_week: 0, period_id: 1, teacher_id: 1, classroom_id: 1, class_id: 1 },
        { day_of_week: 0, period_id: 1, teacher_id: 1, classroom_id: 2, class_id: 2 },   // ίδιος καθηγητής
        { day_of_week: 0, period_id: 2, teacher_id: 2, classroom_id: 1, class_id: 1 },
        { day_of_week: 1, period_id: 1, teacher_id: 1, classroom_id: 1, class_id: 1 },   // άλλη μέρα
        { day_of_week: 0, period_id: 1, teacher_id: 3, classroom_id: 1, class_id: 3, is_unplaced: true },
    ];
    assert.equal(T.countConflicts(S, 0), 1);
    assert.equal(T.countConflicts(S, 1), 0);
});

test('Contact: ίδιοι κανόνες με το CRM — ποτέ λάθος αριθμός', () => {
    const intl = (raw) => Contact.phoneNumbers(raw).map(p => p.intl);
    assert.deepEqual(intl('691 234 5678'), ['+306912345678']);
    assert.deepEqual(intl('6912345678 / 6987654321'), ['+306912345678', '+306987654321']);
    assert.deepEqual(intl('+6912345678'), []);
    assert.deepEqual(intl('δεν έχει'), []);
    assert.equal(Contact.phoneNumbers('2101234567')[0].mobile, false);
    const l = Contact.links(Contact.phoneNumbers('6912345678')[0], 'Γεια & χαρά');
    assert.equal(l.call, 'tel:+306912345678');
    assert.equal(l.sms, 'sms:+306912345678?body=%CE%93%CE%B5%CE%B9%CE%B1%20%26%20%CF%87%CE%B1%CF%81%CE%AC');
    assert.equal(l.viber, 'viber://chat?number=%2B306912345678');
    assert.equal(Contact.links(Contact.phoneNumbers('2101234567')[0]).sms, null);
});

test('Εμφάνιση: άκυρες τιμές → προεπιλογές, αποθήκευση/εφαρμογή χωρίς localStorage', () => {
    const mem = new Map();
    const store = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
    assert.deepEqual(Appearance.load(store), { accent: 'blue', size: 'm' });
    Appearance.save({ accent: 'red', size: 'xxl' }, store);
    assert.deepEqual(Appearance.load(store), { accent: 'red', size: 'm' });
    const broken = { getItem: () => { throw new Error('private'); }, setItem: () => { throw new Error('private'); } };
    assert.deepEqual(Appearance.load(broken), { accent: 'blue', size: 'm' });
    assert.doesNotThrow(() => Appearance.save({ accent: 'green' }, broken));
    const dom = new JSDOM('<!DOCTYPE html><html></html>');
    Appearance.apply({ accent: 'violet', size: 'l' }, dom.window.document.documentElement);
    assert.equal(dom.window.document.documentElement.getAttribute('data-accent'), 'violet');
    assert.equal(dom.window.document.documentElement.getAttribute('data-size'), 'l');
});

// ─── Ολόκληρη η εφαρμογή ─────────────────────────────────────────────────

test('διευθύνσεις σελίδων: #timetable ανοίγει το Ωρολόγιο, το «Πίσω» γυρίζει στην προηγούμενη', async () => {
    const { routes } = timetableRoutes();
    const app = await start(routes, { hash: '#timetable' });
    try {
        await waitFor(app.w, () => app.doc.getElementById('tt-undo'));
        assert.equal(app.G.App._currentView, 'timetable');
        await go(app, 'lessons', '[id^="dt-add-"]');
        assert.equal(app.w.location.hash, '#lessons');
        app.w.history.back();
        await waitFor(app.w, () => app.G.App._currentView === 'timetable' && app.doc.getElementById('tt-undo'));
        assert.equal(app.w.location.hash, '#timetable');
        assert.ok(app.doc.querySelector('.nav-item.active[data-view="timetable"]'));
        assert.ok(app.doc.querySelector('.bottom-nav-item.active[data-nav="timetable"]'));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('«Πίσω» κλείνει πρώτα το παράθυρο, μετά αλλάζει σελίδα', async () => {
    const { routes } = timetableRoutes();
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-rename');
        await go(app, 'lessons', '[id^="dt-add-"]');
        app.doc.querySelector('[id^="dt-add-"]').click();
        await waitFor(app.w, () => overlayOpen(app));
        app.w.history.back();
        await waitFor(app.w, () => !overlayOpen(app));
        await sleep(app.w, 30);
        assert.equal(app.G.App._currentView, 'lessons', 'η σελίδα δεν άλλαξε');
        app.w.history.back();
        await waitFor(app.w, () => app.G.App._currentView === 'timetable');
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('φόρμα με αλλαγές: πάτημα έξω / Esc / «Πίσω» ρωτούν, «Ακύρωση» κλείνει κατευθείαν', async () => {
    const app = await start(baseRoutes());
    try {
        await go(app, 'teachers', '[id^="dt-add-"]');
        const open = async () => {
            app.doc.querySelector('[id^="dt-add-"]').click();
            await waitFor(app.w, () => overlayOpen(app) && app.doc.getElementById('f-name'));
        };
        await open();
        // Χωρίς αλλαγές: πάτημα έξω κλείνει όπως πριν.
        app.doc.getElementById('modal-overlay').click();
        await waitFor(app.w, () => !overlayOpen(app));

        await open();
        const name = app.doc.getElementById('f-name');
        name.value = 'Νέος';
        name.dispatchEvent(new app.w.Event('input', { bubbles: true }));
        app.doc.getElementById('modal-overlay').click();
        assert.ok(overlayOpen(app), 'μένει ανοιχτό');
        const bar = app.doc.getElementById('modal-discard');
        assert.equal(bar.hidden, false);
        // Esc με την ερώτηση ανοιχτή = «συνέχεια επεξεργασίας»
        app.doc.dispatchEvent(new app.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        assert.equal(bar.hidden, true);
        assert.ok(overlayOpen(app));
        // Esc ξανά = ερώτηση
        app.doc.dispatchEvent(new app.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        assert.equal(bar.hidden, false);
        // «Πίσω» = ερώτηση, το παράθυρο μένει
        app.w.history.back();
        await sleep(app.w, 60);
        assert.ok(overlayOpen(app));
        assert.equal(app.doc.getElementById('f-name').value, 'Νέος', 'η φόρμα δεν χάθηκε');
        bar.querySelector('[data-discard="drop"]').click();
        assert.ok(!overlayOpen(app));

        await open();
        app.doc.getElementById('f-name').value = 'Άλλος';
        app.doc.getElementById('f-name').dispatchEvent(new app.w.Event('input', { bubbles: true }));
        app.doc.getElementById('modal-cancel').click();
        assert.ok(!overlayOpen(app), 'η ρητή «Ακύρωση» δεν ρωτά');
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('Ωρολόγιο: κατάσταση στα ελληνικά, 📢 στη λίστα, μενού με όλες τις ενέργειες', async () => {
    const { routes, state } = timetableRoutes({
        'GET /api/publications': () => [{ id: 1, solution_id: 7, published_at: '2026-10-24T09:00:00' }],
        'GET /api/publications/preview/*': () => ({
            first: false, affected: 2, unplaced: 0, teachers: [],
            previous: { solution_id: 7, solution_name: 'Χειμερινό', published_at: '2026-10-24T09:00:00' },
        }),
    });
    state.solutions[0].status = 'feasible';
    const app = await start(routes);
    try {
        await go(app, 'timetable', '#tt-solution');
        assert.equal(app.doc.getElementById('tt-solution-status').textContent.trim(), '✓ Εφικτό');
        assert.ok(app.doc.getElementById('tt-solution-status').classList.contains('ok'));
        assert.match(app.doc.querySelector('#tt-solution option[value="7"]').textContent, /Χειμερινό · 📢 δημοσιευμένο/);
        await waitFor(app.w, () => app.doc.getElementById('tt-pub-chip'));
        assert.match(app.doc.getElementById('tt-pub-chip').textContent, /Αλλαγές για 2 καθηγητές μετά τη δημοσίευση της 24\/10/);
        assert.equal(app.doc.getElementById('tt-publish-count').hidden, false);
        // Όλες οι παλιές ενέργειες υπάρχουν (στα μενού) με τα ίδια id.
        for (const id of ['tt-fill', 'tt-regen', 'tt-empty', 'tt-compare', 'tt-diff', 'tt-violations', 'tt-gaps',
            'tt-bulk-export', 'tt-ics', 'tt-substitute', 'tt-print', 'tt-publish', 'tt-history', 'tt-rename', 'tt-archive']) {
            assert.ok(app.doc.getElementById(id), id);
        }
        const menus = [...app.doc.querySelectorAll('.tt-actions [data-menu]')];
        assert.equal(menus.length, 3);
        const btn = menus[1].querySelector('.menu-btn');
        btn.click();
        assert.equal(btn.getAttribute('aria-expanded'), 'true');
        assert.equal(menus[1].querySelector('.menu-list').hidden, false);
        app.doc.body.click();                                                   // πάτημα έξω
        assert.equal(menus[1].querySelector('.menu-list').hidden, true);
        // Μετονομασία: το όνομα χωρίς το «📢 δημοσιευμένο»
        app.doc.getElementById('tt-rename').click();
        await waitFor(app.w, () => app.doc.getElementById('f-solution-name'));
        assert.equal(app.doc.getElementById('f-solution-name').value, 'Χειμερινό');
        app.doc.getElementById('modal-cancel').click();
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('κινητό: μία μέρα, παράθυρο με ώρα, «↔ Μετακίνηση» με επιβεβαίωση', async () => {
    const puts = [];
    const { routes, state } = timetableRoutes({
        'GET /api/solver/solutions/*/slots/*/placement-map': () => ({ slot_id: 1, cells: [
            { day: 0, period_id: 1, ok: true },
            { day: 0, period_id: 3, ok: true },
            { day: 1, period_id: 1, ok: false, reason: 'Ο Νικολάου διδάσκει' },
        ] }),
        'PUT /api/solver/solutions/*/slots/*': ({ body, path: p }) => {
            puts.push({ id: +p.split('/').pop(), body });
            return { status: 'ok', slot: { classroom_id: 1, classroom_name: 'Αίθ 1' } };
        },
    });
    state.slots = [slot(1), slot(2, { day_of_week: 1, period_id: 2, is_locked: true })];
    const app = await start(routes, { phone: true });
    try {
        await go(app, 'timetable', '.tt-days');
        assert.equal(app.doc.querySelector('.timetable-grid'), null, 'όχι πλέγμα 800px στο κινητό');
        app.doc.querySelector('.tt-day-tab[data-day="0"]').click();
        await waitFor(app.w, () => app.doc.querySelector('.tt-lesson[data-slot-id="1"]'));
        app.doc.querySelector('.tt-lesson[data-slot-id="1"]').click();
        await waitFor(app.w, () => overlayOpen(app));
        assert.match(app.doc.querySelector('.ls-when').textContent, /Δευτέρα 16:00–17:00/);
        assert.equal(app.doc.getElementById('modal-cancel').hidden, true, 'μόνο «Κλείσιμο»');
        app.doc.querySelector('[data-ls="move"]').click();
        await waitFor(app.w, () => app.doc.querySelector('.move-option'));
        assert.equal(app.doc.querySelectorAll('.move-option').length, 1, 'χωρίς την τρέχουσα θέση');
        assert.match(app.doc.getElementById('ls-move').textContent, /Ο Νικολάου διδάσκει/);
        app.doc.querySelector('.move-option').click();
        assert.match(app.doc.querySelector('.move-confirm').textContent, /Δευτέρα 18:00–19:00/);
        assert.equal(puts.length, 0, 'τίποτα πριν την επιβεβαίωση');
        app.doc.querySelector('[data-move-ok]').click();
        await waitFor(app.w, () => puts.length === 1 && !overlayOpen(app));
        assert.deepEqual(puts[0], { id: 1, body: { day_of_week: 0, period_id: 3 } });
        assert.equal(state.slots[0].period_id, 3, 'η μνήμη ενημερώθηκε');
        assert.ok(app.toasts.some(t => /Μετακινήθηκε: Δευτέρα 18:00–19:00/.test(t.message)));

        // Κλειδωμένο: «Μετακίνηση» απενεργή, «Ξεκλείδωμα» στέλνει is_locked=false
        app.doc.querySelector('.tt-day-tab[data-day="1"]').click();
        await waitFor(app.w, () => app.doc.querySelector('.tt-lesson[data-slot-id="2"]'));
        app.doc.querySelector('.tt-lesson[data-slot-id="2"]').click();
        await waitFor(app.w, () => overlayOpen(app));
        assert.equal(app.doc.querySelector('[data-ls="move"]').disabled, true);
        app.doc.querySelector('[data-ls="lock"]').click();
        await waitFor(app.w, () => puts.length === 2);
        assert.equal(puts[1].body.is_locked, false);
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('Μαθήματα-Κάρτες: αναζήτηση/φίλτρα και διαγραφή με όνομα, όχι «#57»', async () => {
    const lessons = [
        { id: 57, subject_name: 'Φυσική', teacher_name: 'Νικολάου', class_name: 'Β2', periods_per_week: 2, students: ['Νίκος Π.'] },
        { id: 58, subject_name: 'Χημεία', teacher_name: 'Παππάς', class_name: 'Γ1', periods_per_week: 1, students: [] },
    ];
    const app = await start(baseRoutes({
        'GET /api/lessons/': () => lessons,
        'GET /api/teachers/': () => [{ id: 1, name: 'Νικολάου' }, { id: 2, name: 'Παππάς' }],
        'GET /api/classes/': () => [{ id: 1, name: 'Β2' }, { id: 2, name: 'Γ1' }],
    }));
    try {
        await go(app, 'lessons', 'tr[data-id="58"]');
        const rows = () => [...app.doc.querySelectorAll('#lessons-table tbody tr')].map(r => r.dataset.id);
        const search = app.doc.getElementById('lf-search');
        search.value = 'νίκος';                                                 // και ονόματα μαθητών
        search.dispatchEvent(new app.w.Event('input'));
        assert.deepEqual(rows(), ['57']);
        assert.equal(app.doc.getElementById('lf-count').textContent, '1 από 2');
        assert.equal(app.doc.getElementById('lf-clear').hidden, false);
        app.doc.getElementById('lf-clear').click();
        assert.deepEqual(rows(), ['57', '58']);
        change(app, app.doc.getElementById('lf-teacher'), 'Παππάς');
        assert.deepEqual(rows(), ['58']);
        change(app, app.doc.getElementById('lf-teacher'), '');
        change(app, app.doc.getElementById('lf-class'), 'Β2');
        assert.deepEqual(rows(), ['57']);
        app.doc.querySelector('.dt-delete[data-id="57"]').click();
        await waitFor(app.w, () => overlayOpen(app));
        assert.match(app.doc.getElementById('modal-body').textContent, /Φυσική — Β2 \(Νικολάου\)/);
        assert.doesNotMatch(app.doc.getElementById('modal-body').textContent, /#57/);
        app.doc.getElementById('modal-cancel').click();
        app.G.LessonsView._filter = { search: '', teacher: '', cls: '' };
        await sleep(app.w, 30);
    } finally { app.close(); }
});

test('αποτυχία φόρτωσης: μήνυμα και «Δοκίμασε ξανά» αντί για ατελείωτο «Φόρτωση»', async () => {
    let fail = true;
    const app = await start(baseRoutes({
        'GET /api/teachers/': () => (fail ? { __status: 503, data: { detail: 'Η βάση δεν απαντά' } } : []),
    }));
    try {
        // Μαθήματα-Κάρτες: η σελίδα ολόκληρη
        app.G.App.navigateTo('lessons');
        await waitFor(app.w, () => app.doc.querySelector('#content-area [data-retry]'));
        assert.match(app.doc.getElementById('content-area').textContent, /Η βάση δεν απαντά/);
        fail = false;
        app.doc.querySelector('#content-area [data-retry]').click();
        await waitFor(app.w, () => app.doc.getElementById('lf-search'));
        // Καθηγητές: ο πίνακας μόνο
        fail = true;
        app.G.App.navigateTo('teachers');
        await waitFor(app.w, () => app.doc.querySelector('[data-dt-retry]'));
        assert.equal(app.doc.querySelector('#content-area .loading-spinner'), null);
        fail = false;
        app.doc.querySelector('[data-dt-retry]').click();
        await waitFor(app.w, () => app.doc.querySelector('#content-area .empty-state-text')
            && /Δεν υπάρχουν εγγραφές/.test(app.doc.getElementById('content-area').textContent));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('Πίνακας Ελέγχου: «Χρειάζεται προσοχή» και μετάβαση στα 🕳 Κενά', async () => {
    const { routes, state } = timetableRoutes({
        'GET /api/publications/preview/*': () => ({ first: true, affected: 2, previous: null, teachers: [] }),
        'GET /api/solver/solutions/*/gaps': () => ({
            students: [{ id: 1, name: 'Νίκος', grade: '', weekly_hours: 4, days: 2, gap_total: 2,
                         gaps: [{ day: 3, day_name: 'Πέμπτη', from: '16:00', to: '18:00', hours: 2 }] }],
            teachers: [], totals: { student_gaps: 2, teacher_gaps: 0 },
        }),
        'GET /api/integration/crm/students/preview': () => ({ available: true, rows: [{ status: 'new' }, { status: 'exists' }] }),
        'GET /api/teachers/': () => [{ id: 21, name: 'Νικολάου' }],
        'GET /api/lessons/': () => [{ id: 101, subject_name: 'Φυσική' }],
    });
    state.slots.push(slot(3, { is_unplaced: true, day_of_week: null, period_id: null, subject_short: 'ΧΗΜ', class_short: 'Γ1' }));
    {
        const app = await start(routes);
        try {
            app.G.DashboardView._crmCache = null;
            await go(app, 'dashboard', '.dash-attn-row');
            const text = app.doc.getElementById('dash-attn').textContent.replace(/\s+/g, ' ');
            assert.match(text, /2 καθηγητές δεν έχουν λάβει ακόμα το πρόγραμμα/);
            assert.match(text, /1 ώρα περιμένουν στην Παλέτα \(ΧΗΜ Γ1\)/);
            assert.match(text, /1 μαθητής με κενό 2 ή περισσότερων ωρών την Πέμπτη/);
            assert.match(text, /1 νέος μαθητής στο CRM/);
            assert.equal(app.doc.querySelector('.dash-start'), null, 'χωρίς «Γρήγορη Εκκίνηση» όταν υπάρχουν τα βασικά');
            app.doc.querySelector('[data-attn="gaps"]').click();
            await waitFor(app.w, () => app.G.App._currentView === 'timetable' && app.doc.getElementById('gaps-kind'));
            assert.match(app.doc.getElementById('modal-title').textContent, /Κενά/);
            await sleep(app.w, 30);
        } finally { app.close(); }
    }
});

test('Σήμερα: «Λείπει σήμερα» → αντικαταστάτης → έτοιμο μήνυμα με SMS', async () => {
    const day = T.edsDay(new Date());
    const { routes, state } = timetableRoutes({
        'GET /api/teachers/': () => [{ id: 21, name: 'Νικολάου', phone: '' }, { id: 22, name: 'ΕΛΕΝΗ ΦΩΤΙΟΥ', phone: '6912345678' }],
        'GET /api/solver/solutions/*/substitute-suggestions': () => ({
            affected_slots: [{ slot_id: 1, period_id: 1, period_name: '1η', subject_name: 'Φυσική', class_name: 'Β2',
                classroom_name: 'Αίθ 1', candidates: [{ teacher_id: 22, name: 'ΕΛΕΝΗ ΦΩΤΙΟΥ', score: 9, reasons: ['ελεύθερος'] }],
                reschedule_options: [] }],
            stats: { affected_count: 1, with_candidates: 1 },
        }),
    });
    state.slots = [slot(1, { day_of_week: day, period_id: 1 })];
    const app = await start(routes, { hash: '#today' });
    try {
        await waitFor(app.w, () => app.doc.querySelector('.today-item-main'));
        app.doc.querySelector('.today-item-main').click();
        await waitFor(app.w, () => app.doc.querySelector('[data-today-absent]'));
        assert.match(app.doc.querySelector('[data-today-absent]').textContent, /Λείπει σήμερα/);
        app.doc.querySelector('[data-today-absent]').click();
        await waitFor(app.w, () => app.doc.querySelector('.absent-cand'));
        assert.match(app.doc.getElementById('modal-title').textContent, /Λείπει σήμερα/);
        app.doc.querySelector('.absent-cand').click();
        const text = app.doc.getElementById('absent-text').value;
        assert.equal(text, 'Καλησπέρα ΕΛΕΝΗ! Μπορείς σήμερα 16:00–17:00 Φυσική (Β2) στην Αίθ 1, αντί για Νικολάου; Ευχαριστώ!');
        const sms = app.doc.querySelector('#absent-msg a[href^="sms:"]');
        assert.ok(sms.href.startsWith('sms:+306912345678?body=Καλησπέρα') || sms.getAttribute('href').startsWith('sms:+306912345678?body=%CE'));
        // Κανένα αίτημα εγγραφής από το «Σήμερα»
        assert.ok(!app.calls.some(c => c.method !== 'GET'));
        await sleep(app.w, 20);
    } finally { app.close(); }
});

test('αλλαγή σεναρίου από το μενού «Περισσότερα»: με επιβεβαίωση', async () => {
    let term = 1;
    const activations = [];
    const app = await start(baseRoutes({
        'GET /api/terms/': () => [{ id: 1, name: 'Χειμ', is_active: term === 1 }, { id: 2, name: 'Θερινό', is_active: term === 2 }],
        'POST /api/terms/*/activate': ({ path: p }) => { term = +p.split('/')[3]; activations.push(term); return { id: term }; },
    }), { phone: true });
    try {
        await waitFor(app.w, () => app.doc.querySelector('[data-term-id="2"]'));
        app.doc.getElementById('bn-more').click();
        assert.equal(app.doc.getElementById('more-sheet').hidden, false);
        app.doc.querySelector('[data-term-id="2"]').click();
        await waitFor(app.w, () => overlayOpen(app));
        assert.equal(app.doc.getElementById('more-sheet').hidden, true);
        assert.deepEqual(activations, []);
        app.doc.getElementById('modal-save').click();
        await waitFor(app.w, () => activations.length === 1 && !overlayOpen(app));
        assert.equal(term, 2);
        await sleep(app.w, 30);
    } finally { app.close(); }
});
