/**
 * Unit tests for frontend/js/views/lessons_helpers.js (term-import picker).
 * Run with: node --test frontend/js/tests/
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');

const H = require('../views/lessons_helpers.js');

const SOURCE = [
    { id: 11, subject_id: 1, teacher_id: 5, class_id: 9,
      subject_name: 'Άλγεβρα', class_name: 'Β2', teacher_name: 'Νίκος', periods_per_week: 4 },
    { id: 12, subject_id: 2, teacher_id: 5, class_id: 9,
      subject_name: 'Γεωμετρία', class_name: 'Β2', teacher_name: 'Νίκος', periods_per_week: 2 },
];
const ACTIVE = [
    // Ίδιο triple με το source id 11 (άλλο id/ppw — δεν έχει σημασία)
    { id: 77, subject_id: 1, teacher_id: 5, class_id: 9, periods_per_week: 5 },
];

test('markTermImportDuplicates: triple match σημαδεύει τα υπάρχοντα', () => {
    const marked = H.markTermImportDuplicates(SOURCE, ACTIVE);
    assert.equal(marked.find(l => l.id === 11).exists, true);
    assert.equal(marked.find(l => l.id === 12).exists, false);
    // Κενές λίστες δεν σκάνε
    assert.deepEqual(H.markTermImportDuplicates([], []), []);
    assert.equal(H.markTermImportDuplicates(SOURCE, null)[0].exists, false);
});

test('buildTermImportListHtml: checkbox για νέα, disabled+badge για υπάρχοντα', () => {
    const html = H.buildTermImportListHtml(H.markTermImportDuplicates(SOURCE, ACTIVE));
    assert.match(html, /value="12"[^>]*checked/);     // importable, προεπιλεγμένο
    assert.doesNotMatch(html, /value="11"/);           // το υπάρχον ΔΕΝ έχει value
    assert.match(html, /υπάρχει ήδη/);
    assert.match(html, /Γεωμετρία/);
    assert.match(html, /4 ώρες\/εβδ/);
    assert.match(html, /id="term-import-count">1</);   // 1 προς εισαγωγή
});

test('buildTermImportListHtml: κενή πηγή δίνει φιλικό μήνυμα', () => {
    assert.match(H.buildTermImportListHtml([]), /δεν έχει μαθήματα/);
});

test('_esc: escapes HTML in names', () => {
    assert.equal(H._esc('<b>&"x"'), '&lt;b&gt;&amp;&quot;x&quot;');
});
