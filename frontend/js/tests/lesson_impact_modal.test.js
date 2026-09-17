/**
 * Unit tests για το «🔍 Τι επηρεάζει;» (components/lesson_impact_modal.js)
 * και για το κουμπί ελέγχου στις κάρτες της Παλέτας.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');

const M = require('../components/lesson_impact_modal.js');
const H = require('../views/timetable_helpers.js');

const DATA = {
    lesson: {
        id: 7, subject_name: 'Άλγεβρα', teacher_name: 'Καθ Α', class_name: 'Β2',
        class_students: 3, periods_per_week: 4, term_id: 1, term_name: 'ΧΕΙΜΕΡΙΝΟ',
    },
    solutions: [
        { solution_id: 2, solution_name: 'Πρόγραμμα <b>Β</b>', status: 'optimal', placed: 1, unplaced: 3, missing: 0 },
        { solution_id: 1, solution_name: 'Πρόγραμμα Α', status: 'optimal', placed: 3, unplaced: 1, missing: 0 },
    ],
    totals: { solutions: 2, placed: 4, unplaced: 4, max_placed: 3 },
    trim: { can_trim: true, trim_to: 3, would_remove: 1, blocked_reason: null },
    delete: { placed_total: 4, solutions_with_placed: 2, requires_force: true },
};

const clone = (over = {}) => ({ ...DATA, ...over });


test('title: μάθημα — τμήμα • καθηγητής', () => {
    assert.equal(M.title(DATA), '🔍 Άλγεβρα — Β2 • Καθ Α');
    assert.equal(M.title({ lesson: { subject_name: 'Φυσική' } }), '🔍 Φυσική');
});

test('effectLines: λέει ΠΟΥ μετράνε και πού ΔΕΝ μετράνε οι ώρες της παλέτας', () => {
    const lines = M.effectLines(DATA).join(' ');
    assert.match(lines, /4 ώρες περιμένουν στην Παλέτα σε 2 πρόγραμμα\(τα\) του «ΧΕΙΜΕΡΙΝΟ»/);
    assert.match(lines, /ΔΕΝ εμφανίζονται στο τυπωμένο πρόγραμμα/);
    assert.match(lines, /ΔΕΝ μετράνε στις ώρες και στη μισθοδοσία του CRM/);
    assert.match(lines, /solver/);
    assert.match(lines, /μόνο αυτό το σενάριο/);
});

test('warnings: τοποθετημένες ώρες και τμήμα χωρίς μαθητές', () => {
    assert.deepEqual(M.warnings(DATA), ['✅ 4 ώρες αυτού του μαθήματος είναι ΤΟΠΟΘΕΤΗΜΕΝΕΣ και χρησιμοποιούνται.']);
    const empty = M.warnings(clone({
        lesson: { ...DATA.lesson, class_students: 0 }, totals: { ...DATA.totals, placed: 0 },
    }));
    assert.equal(empty.length, 1);
    assert.match(empty[0], /Το τμήμα δεν έχει μαθητές/);
});

test('actionState: καθάρισμα ενεργό μόνο όταν περισσεύουν ώρες', () => {
    const on = M.actionState(DATA);
    assert.equal(on.trimEnabled, true);
    assert.equal(on.trimLabel, '✂️ Κράτα μόνο τις τοποθετημένες (3 ώρες/εβδ.)');
    assert.match(on.trimHint, /Θα αφαιρεθούν 1 ώρες.*από 4 σε 3.*Καμία τοποθετημένη ώρα/s);
    assert.match(on.confirmLabel, /θα σβηστούν και 4 τοποθετημένες ώρες σε 2 πρόγραμμα\(τα\)/);

    const nothing = M.actionState(clone({
        trim: { can_trim: false, trim_to: 4, would_remove: 0, blocked_reason: 'nothing_to_trim' },
        solutions: [{ solution_id: 1, solution_name: 'Πρόγραμμα Α', placed: 4, unplaced: 0, missing: 0 }],
        totals: { solutions: 1, placed: 4, unplaced: 0, max_placed: 4 },
    }));
    assert.equal(nothing.trimEnabled, false);
    assert.match(nothing.trimHint, /Όλες οι ώρες είναι τοποθετημένες/);

    // Το ΠΑΛΙΟ πρόγραμμα κρατά τις ώρες ενώ στο τρέχον περιμένουν στην Παλέτα.
    const held = M.actionState(clone({
        trim: { can_trim: false, trim_to: 3, would_remove: 0, blocked_reason: 'nothing_to_trim' },
        lesson: { ...DATA.lesson, periods_per_week: 3 },
        solutions: [
            { solution_id: 2, solution_name: 'ΧΕΙΜΕΡΙΝΟ', placed: 0, unplaced: 3, missing: 0 },
            { solution_id: 1, solution_name: 'Παλιό 8/5', placed: 3, unplaced: 0, missing: 0 },
        ],
        totals: { solutions: 2, placed: 3, unplaced: 3, max_placed: 3 },
    }));
    assert.match(held.trimHint, /Οι 3 ώρες της Παλέτας δεν κόβονται: στο «Παλιό 8\/5»/);
    assert.match(held.trimHint, /διάγραψε ολόκληρο το μάθημα/);
    assert.deepEqual(M.blockingSolutions(DATA), ['Πρόγραμμα Α']);

    const none = M.actionState(clone({
        trim: { can_trim: false, trim_to: 4, would_remove: 0, blocked_reason: 'no_placed_hours' },
        delete: { placed_total: 0, solutions_with_placed: 0, requires_force: false },
    }));
    assert.equal(none.trimEnabled, false);
    assert.match(none.trimHint, /διάγραψε ολόκληρο το μάθημα/);
    assert.equal(none.confirmLabel, '');      // χωρίς τοποθετημένες: χωρίς τσεκάρισμα
});

test('buildHtml: πίνακας ανά πρόγραμμα, escape, κουμπιά και επιβεβαίωση', () => {
    const html = M.buildHtml(DATA);
    assert.match(html, /Β2\s*\(3 μαθητές\)/);
    assert.match(html, /<b>4<\/b> ώρες\/εβδομάδα/);
    assert.match(html, /Πρόγραμμα &lt;b&gt;Β&lt;\/b&gt;/);          // escaped
    assert.doesNotMatch(html, /Πρόγραμμα <b>Β<\/b>/);
    assert.match(html, /id="li-trim"(?![^>]*disabled)/);
    assert.match(html, /id="li-confirm"/);
    assert.match(html, /id="li-delete"/);

    const noTrim = M.buildHtml(clone({
        trim: { can_trim: false, trim_to: 4, would_remove: 0, blocked_reason: 'nothing_to_trim' },
        delete: { placed_total: 0, solutions_with_placed: 0, requires_force: false },
    }));
    assert.match(noTrim, /id="li-trim"[^>]*disabled/);
    assert.doesNotMatch(noTrim, /id="li-confirm"/);          // τίποτα δεν χάνεται → χωρίς checkbox
});

test('buildHtml: χωρίς αποθηκευμένο πρόγραμμα δείχνει μήνυμα αντί για πίνακα', () => {
    const html = M.buildHtml(clone({ solutions: [], totals: { solutions: 0, placed: 0, unplaced: 0, max_placed: 0 } }));
    assert.match(html, /Δεν υπάρχει αποθηκευμένο πρόγραμμα/);
    assert.doesNotMatch(html, /<table/);
});

test('κάθε κάρτα της Παλέτας έχει το κουμπί ελέγχου', () => {
    const btn = H._paletteInspectBtnHtml(7);
    assert.match(btn, /TimetableView\.inspectLesson\(7\)/);
    assert.match(btn, /🔍/);

    const card = (over) => H._paletteCardHtml({
        lesson_id: 7, subject_name: 'Άλγεβρα', class_name: 'Β2', teacher_name: 'Καθ Α',
        total: 4, placed: 3, remaining: 0, missing: 0, ...over,
    });
    assert.match(card({ remaining: 1, drag_slot: { id: 11 } }), /inspectLesson\(7\)/);
    assert.match(card({ missing: 2 }), /inspectLesson\(7\)/);
    assert.match(card({ placed: 4 }), /inspectLesson\(7\)/);       // ολοκληρωμένη κάρτα
});

test('επιλογέας προγράμματος: τα αρχειοθετημένα σε δική τους ομάδα', () => {
    const sols = [
        { id: 3, name: 'ΧΕΙΜΕΡΙΝΟ', archived: false },
        { id: 2, name: 'Παλιό <b>8/5</b>', archived: true },
        { id: 1, name: 'Πολύ παλιό', archived: true },
    ];
    const html = H.buildSolutionOptionsHtml(sols, 3);
    assert.match(html, /<option value="3" selected>ΧΕΙΜΕΡΙΝΟ<\/option>/);
    assert.match(html, /<optgroup label="📦 Αρχειοθετημένα \(2\)">/);
    assert.match(html, /Παλιό &lt;b&gt;8\/5&lt;\/b&gt;/);          // escaped
    assert.ok(html.indexOf('optgroup') > html.indexOf('ΧΕΙΜΕΡΙΝΟ'));

    // Χωρίς αρχειοθετημένα: καμία ομάδα
    assert.doesNotMatch(H.buildSolutionOptionsHtml([sols[0]], 3), /optgroup/);
});

test('ποιο πρόγραμμα ανοίγει + κατάσταση κουμπιού αρχειοθέτησης', () => {
    const sols = [
        { id: 3, name: 'ΧΕΙΜΕΡΙΝΟ', archived: false },
        { id: 2, name: 'Παλιό', archived: true },
    ];
    assert.equal(H.defaultSolutionId(sols, 3), 3);
    assert.equal(H.defaultSolutionId(sols, 2), 3);       // αρχειοθετημένο → το νεότερο ενεργό
    assert.equal(H.defaultSolutionId(sols, null), 3);
    assert.equal(H.defaultSolutionId([sols[1]], null), 2);   // μόνο αρχειοθετημένα → δείξε το

    assert.deepEqual(H.archiveButtonState(sols, 3).icon, '📦');
    assert.match(H.archiveButtonState(sols, 3).title, /Αρχειοθέτηση/);
    assert.equal(H.archiveButtonState(sols, 2).archived, true);
    assert.equal(H.archiveButtonState(sols, 2).icon, '♻️');
});
