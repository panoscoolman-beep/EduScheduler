/**
 * 📦 ArchiveControls (καθηγητές/τμήματα/αίθουσες) + toolbarHtml στο DataTable.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');

const A = require('../components/archive_controls.js');

test('nameRender: escape + σήμα αρχειοθέτησης', () => {
    assert.equal(A.nameRender('Αίθ <1>', { archived: false }), 'Αίθ &lt;1&gt;');
    assert.match(A.nameRender('Παλιός', { archived: true }), /Παλιός <span class="archived-badge"[^>]*>📦 αρχειοθετημένο/);
    assert.match(A.toolbarHtml(true), /class="archive-show" checked/);
    assert.doesNotMatch(A.toolbarHtml(false), /checked/);
});

test('create(): λίστα με include_archived, 📦 με επιβεβαίωση, ♻️ απευθείας', async () => {
    const dom = new JSDOM('<!DOCTYPE html><body><div id="c"><input type="checkbox" class="archive-show"></div></body>');
    global.document = dom.window.document;
    const calls = [];
    const opened = [];
    global.Toast = { success: (m) => calls.push(['toast', m]), error: (m) => calls.push(['err', m]) };
    global.Modal = { open: (t, body, onSave) => opened.push({ t, body, onSave }), close() {} };
    const base = {
        list: async (inc) => { calls.push(['list', inc]); return []; },
        archive: async (id) => { calls.push(['archive', id]); return { message: 'αρχειοθετήθηκε' }; },
        unarchive: async (id) => { calls.push(['unarchive', id]); return { message: 'επανήλθε' }; },
        delete: () => {},
    };
    const ctl = A.create(base, 'τον καθηγητή');
    assert.equal(typeof ctl.api.delete, 'function');             // τα υπόλοιπα μένουν
    await ctl.api.list();
    const table = { loadData: async () => ctl.api.list() };
    ctl.wire(document.getElementById('c'), table);
    const box = document.querySelector('.archive-show');
    box.checked = true;
    box.dispatchEvent(new dom.window.Event('change'));
    await new Promise(r => setTimeout(r, 0));
    assert.deepEqual(calls.filter(c => c[0] === 'list'), [['list', false], ['list', true]]);

    ctl.action.handler({ id: 3, name: 'Γιώργος <b>', archived: false });
    assert.equal(opened.length, 1);
    assert.match(opened[0].body, /τον καθηγητή «<b>Γιώργος &lt;b&gt;<\/b>»/);
    await opened[0].onSave();
    assert.ok(calls.some(c => c[0] === 'archive' && c[1] === 3));

    ctl.action.handler({ id: 4, name: 'Χ', archived: true });
    await new Promise(r => setTimeout(r, 0));
    assert.ok(calls.some(c => c[0] === 'unarchive' && c[1] === 4));
    assert.equal(opened.length, 1);                              // επαναφορά χωρίς modal
});

test('DataTable: toolbarHtml εμφανίζεται δίπλα στο «Προσθήκη»', async () => {
    const dom = new JSDOM('<!DOCTYPE html><body><div id="host"></div></body>');
    global.window = dom.window;
    global.document = dom.window.document;
    global.Toast = { error() {}, success() {} };
    const DataTable = require('../components/data-table.js');
    const t = new DataTable({
        columns: [{ key: 'name', label: 'Όνομα' }], apiService: { list: async () => [] },
        entityName: 'Αίθουσες', formBuilder: () => '', formParser: () => ({}),
        toolbarHtml: A.toolbarHtml(false),
    });
    await t.render(document.getElementById('host'));
    assert.ok(document.querySelector('.card-header .archive-show'));
});
