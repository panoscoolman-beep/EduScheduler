/**
 * StudentPicker — pure builders (node --test) + jsdom mount/interaction.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');

const P = require('../components/student_picker.js');

const STUDENTS = [
    { id: 1, last_name: 'Παπαδόπουλος', first_name: 'Νίκος', class_ids: [10, 11] },
    { id: 2, last_name: 'Αλεξίου', first_name: 'Μαρία', class_ids: [] },
    { id: 3, last_name: 'Βασιλείου', first_name: 'Κώστας', class_ids: [11] },
    { id: 4, last_name: 'Παππάς', first_name: 'Γιώργος <b>', class_ids: [] },
];
const CLASSES = new Map([
    [10, { id: 10, short_name: 'Α1', name: 'Α1 Μαθηματικά' }],
    [11, { id: 11, short_name: 'Β2', name: 'Β2 Φυσική' }],
]);

test('normalizeGr: strips accents, lowercases, final sigma', () => {
    assert.equal(P.normalizeGr('Παπαδόπουλος'), 'παπαδοπουλοσ');
    assert.equal(P.normalizeGr('ΝΊΚΟΣ'), 'νικοσ');
    assert.equal(P.normalizeGr('  Ϊ ΐ '), 'ι ι');
    assert.equal(P.normalizeGr(null), '');
});

test('filterItems: accent-insensitive, every word must match, sorted el', () => {
    const sel = new Set();
    const names = (list) => list.map(P.studentLabel);
    assert.deepEqual(names(P.filterItems(STUDENTS, { search: 'παπ', selectedIds: sel })),
        ['Παπαδόπουλος Νίκος', 'Παππάς Γιώργος <b>']);
    assert.deepEqual(names(P.filterItems(STUDENTS, { search: 'νικ παπ', selectedIds: sel })),
        ['Παπαδόπουλος Νίκος']);
    assert.deepEqual(names(P.filterItems(STUDENTS, { search: 'ΜΑΡΊΑ', selectedIds: sel })),
        ['Αλεξίου Μαρία']);
    assert.equal(P.filterItems(STUDENTS, { search: 'zzz', selectedIds: sel }).length, 0);
    // χωρίς αναζήτηση: όλοι, ταξινομημένοι κατά επώνυμο
    assert.deepEqual(names(P.filterItems(STUDENTS, { selectedIds: sel }))[0], 'Αλεξίου Μαρία');
    // μόνο επιλεγμένοι
    assert.deepEqual(names(P.filterItems(STUDENTS, { selectedIds: new Set([3]), onlySelected: true })),
        ['Βασιλείου Κώστας']);
});

test('buildListHtml: checkbox state, escaping, badges of OTHER classes', () => {
    const html = P.buildListHtml(STUDENTS, {
        selectedIds: new Set([1]),
        badgesOf: s => P.otherClassBadges(s, CLASSES, 10),
    });
    assert.match(html, /class="sp-row is-selected" data-id="1"/);
    assert.match(html, /data-id="1" checked/);
    assert.match(html, /class="sp-row" data-id="2"/);
    assert.match(html, /Παππάς Γιώργος &lt;b&gt;/);          // escaped
    // Ο 1 είναι σε 10 (τρέχον) και 11 → badge μόνο για Β2. Σειρά λίστας:
    // Αλεξίου(2), Βασιλείου(3), Παπαδόπουλος(1), Παππάς(4).
    const row1 = html.slice(html.indexOf('data-id="1"'), html.indexOf('data-id="4"'));
    assert.match(row1, /sp-badge[^>]*>Β2</);
    assert.doesNotMatch(row1, />Α1</);
    assert.match(row1, /Είναι ήδη στο Β2 Φυσική/);
});

test('buildListHtml: empty states', () => {
    assert.match(P.buildListHtml([], { selectedIds: new Set() }), /Δεν υπάρχουν εγγραφές/);
    assert.match(P.buildListHtml(STUDENTS, { selectedIds: new Set(), search: 'qqq' }),
        /Κανένα αποτέλεσμα για «qqq»/);
});

test('buildChipsHtml: sorted chips with ✕, empty hint', () => {
    const html = P.buildChipsHtml(STUDENTS, new Set([3, 2]));
    assert.ok(html.indexOf('Αλεξίου Μαρία') < html.indexOf('Βασιλείου Κώστας'));
    assert.equal((html.match(/sp-chip-x/g) || []).length, 2);
    assert.match(P.buildChipsHtml(STUDENTS, new Set()), /Κανένας επιλεγμένος/);
});

function mountDom(opts = {}) {
    const dom = new JSDOM('<!DOCTYPE html><body><div id="picker"></div></body>');
    global.window = dom.window;
    global.document = dom.window.document;
    const changes = [];
    P.mount('picker', {
        items: STUDENTS,
        selectedIds: [1],
        badgesOf: s => P.otherClassBadges(s, CLASSES, 10),
        noun: 'μαθητές',
        onChange: (ids) => changes.push(ids),
        ...opts,
    });
    return { dom, doc: dom.window.document, changes };
}

test('mount: renders skeleton, initial selection, count', () => {
    const { doc } = mountDom();
    assert.equal(doc.querySelectorAll('.sp-row').length, 4);
    assert.equal(doc.querySelectorAll('.sp-chip').length, 1);
    assert.match(doc.querySelector('.sp-count').innerHTML, /<b>1<\/b> μαθητές/);
    assert.deepEqual(P.getSelected(), [1]);
});

test('mount: checkbox toggles selection, chips + count follow, onChange fires', () => {
    const { doc, dom, changes } = mountDom();
    const cb = doc.querySelector('.sp-check[data-id="3"]');
    cb.checked = true;
    cb.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    assert.deepEqual(P.getSelected(), [1, 3]);
    assert.equal(doc.querySelectorAll('.sp-chip').length, 2);
    assert.ok(doc.querySelector('.sp-row[data-id="3"]').classList.contains('is-selected'));
    assert.deepEqual(changes.at(-1), [1, 3]);

    // chip ✕ αφαιρεί και ξετσεκάρει τη γραμμή
    doc.querySelector('.sp-chip-x[data-id="1"]').dispatchEvent(
        new dom.window.MouseEvent('click', { bubbles: true }));
    assert.deepEqual(P.getSelected(), [3]);
    assert.equal(doc.querySelector('.sp-check[data-id="1"]').checked, false);
});

test('mount: search filters rows without losing the selection', () => {
    const { doc, dom } = mountDom();
    const search = doc.querySelector('.sp-search');
    search.value = 'παπ';
    search.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    assert.equal(doc.querySelectorAll('.sp-row').length, 2);
    assert.deepEqual(P.getSelected(), [1]);           // η επιλογή μένει
    search.value = '';
    search.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    assert.equal(doc.querySelectorAll('.sp-row').length, 4);
});

test('mount: Enter with exactly one match selects it and clears the search', () => {
    const { doc, dom } = mountDom();
    const search = doc.querySelector('.sp-search');
    search.value = 'μαρια';
    search.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
    search.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    assert.deepEqual(P.getSelected(), [1, 2]);
    assert.equal(search.value, '');
    assert.equal(doc.querySelectorAll('.sp-row').length, 4);
});

test('mount: «μόνο επιλεγμένοι» narrows the list; unchecking there removes the row', () => {
    const { doc, dom } = mountDom({ selectedIds: [1, 3] });
    const only = doc.querySelector('.sp-only-selected');
    only.checked = true;
    only.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    assert.equal(doc.querySelectorAll('.sp-row').length, 2);
    const cb = doc.querySelector('.sp-check[data-id="3"]');
    cb.checked = false;
    cb.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
    assert.equal(doc.querySelectorAll('.sp-row').length, 1);
    assert.deepEqual(P.getSelected(), [1]);
});

test('mount: reverse direction (classes as items) with custom label + badges', () => {
    const classes = [...CLASSES.values()].map(c => ({ ...c, student_ids: [1, 3] }));
    const { doc } = mountDom({
        items: classes, selectedIds: [11],
        labelOf: c => `${c.short_name} — ${c.name}`,
        badgesOf: c => [{ text: `${c.student_ids.length} μαθ.` }],
        noun: 'τμήματα',
    });
    assert.match(doc.querySelector('.sp-chip').textContent, /Β2 — Β2 Φυσική/);
    assert.match(doc.querySelector('.sp-row[data-id="10"] .sp-badge').textContent, /2 μαθ\./);
    assert.match(doc.querySelector('.sp-count').innerHTML, /τμήματα/);
});
