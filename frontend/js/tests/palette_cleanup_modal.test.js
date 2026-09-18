/**
 * «🧹 Καθάρισμα Παλέτας» — pure builders + επιλογή με jsdom.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');

const M = require('../components/palette_cleanup_modal.js');
const H = require('../views/timetable_helpers.js');

const item = (id, suggestion, over = {}) => ({
    lesson_id: id, subject_name: `Μάθημα ${id}`, teacher_name: 'Καθ', class_name: 'Β2',
    class_students: 3, periods_per_week: 4, placed_total: 3, unplaced_total: 1, max_placed: 3,
    trim: { can_trim: suggestion === 'trim', trim_to: 3, would_remove: 1 }, suggestion, ...over,
});
const REVIEW = {
    items: [item(1, 'trim'), item(2, 'delete', { placed_total: 0, unplaced_total: 2, max_placed: 0,
                                                 class_students: 0 }),
            item(3, 'keep', { max_placed: 3 })],
    totals: { lessons: 3, palette_hours: 4, trim_hours: 1, deletable: 1 },
};

test('suggestionText για κάθε πρόταση', () => {
    assert.match(M.suggestionText(REVIEW.items[0]), /✂️ Κράτα 3 ώρες\/εβδ\. — σβήνει 1/);
    assert.match(M.suggestionText(REVIEW.items[1]), /🗑️ Διαγραφή μαθήματος — καμία τοποθετημένη/);
    assert.match(M.suggestionText(REVIEW.items[2]), /✋ Κράτα — 3 ώρες είναι τοποθετημένες σε άλλο/);
});

test('buildHtml: trim τσεκαρισμένο, delete ΟΧΙ, keep χωρίς checkbox, escape, κενή Παλέτα', () => {
    const html = M.buildHtml({ ...REVIEW, items: [...REVIEW.items, item(4, 'trim', { subject_name: '<b>x</b>' })] });
    assert.match(html, /data-kind="trim"\s+data-id="1" checked/);
    assert.match(html, /data-kind="delete"\s+data-id="2">/);
    assert.doesNotMatch(html, /data-id="3"/);
    assert.match(html, /Το τμήμα δεν έχει μαθητές/);
    assert.match(html, /&lt;b&gt;x&lt;\/b&gt;/);
    assert.match(M.buildHtml({ items: [], totals: {} }), /Η Παλέτα είναι καθαρή/);
});

test('selection + summaryText από τα checkboxes', () => {
    const dom = new JSDOM(`<!DOCTYPE html><body><div id="r">${M.buildHtml(REVIEW)}</div></body>`);
    const root = dom.window.document.getElementById('r');
    let sel = M.selection(root);
    assert.deepEqual(sel, { trim_ids: [1], delete_ids: [] });
    assert.match(M.summaryText(REVIEW, sel), /Θα αφαιρεθούν 1 ώρες.*διαγραφούν 0 μαθήματα.*Καμία τοποθετημένη/);
    root.querySelector('.pc-pick[data-id="2"]').checked = true;
    root.querySelector('.pc-pick[data-id="1"]').checked = false;
    sel = M.selection(root);
    assert.deepEqual(sel, { trim_ids: [], delete_ids: [2] });
    root.querySelector('.pc-pick[data-id="2"]').checked = false;
    assert.equal(M.summaryText(REVIEW, M.selection(root)), 'Δεν έχει επιλεγεί τίποτα.');
});

test('η Παλέτα δείχνει «🧹 Καθάρισμα» μόνο όταν περιμένουν ώρες', () => {
    const entry = (remaining) => ({
        lesson_id: 7, subject_name: 'Άλγεβρα', class_name: 'Β2', teacher_name: 'Καθ',
        total: 4, placed: 4 - remaining, remaining, missing: 0,
        drag_slot: remaining ? { id: 11 } : null,
    });
    const palette = (remaining) => H.buildLessonPaletteHtml({
        entries: [entry(remaining)],
        totals: { hours_total: 4, hours_placed: 4 - remaining, hours_remaining: remaining, hours_missing: 0 },
    }, {});
    assert.match(palette(2), /id="palette-cleanup"/);
    assert.doesNotMatch(palette(0), /id="palette-cleanup"/);
});


test('περιττές ώρες Παλέτας (πάνω από τις ώρες/εβδ.): σωστή διατύπωση', () => {
    const it = item(9, 'trim', { periods_per_week: 1,
        trim: { can_trim: true, trim_to: 1, would_remove: 1, surplus: true } });
    assert.match(M.suggestionText(it), /Αφαίρεση 1 περιττών ωρών Παλέτας \(πάνω από τις 1 ώρες\/εβδ\.\)/);
});
