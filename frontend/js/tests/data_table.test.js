/**
 * jsdom tests for components/data-table.js — the optional rowFilter /
 * onRendered hooks (used by the Students list) and the unchanged default.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');

function setup() {
    const dom = new JSDOM('<!DOCTYPE html><body><div id="host"></div></body>');
    global.window = dom.window;
    global.document = dom.window.document;
    global.Toast = { error() {}, success() {}, info() {} };
    global.Modal = { open() {}, close() {} };
    return dom;
}

const DataTable = require('../components/data-table.js');

const ROWS = [
    { id: 1, name: 'Γάμμα' },
    { id: 2, name: 'Άλφα' },
    { id: 3, name: 'Βήτα' },
];

function makeTable(extra, data = ROWS) {
    return new DataTable({
        columns: [{ key: 'name', label: 'Όνομα' }],
        apiService: { list: async () => data },
        entityName: 'Δοκιμή',
        formBuilder: () => '',
        formParser: () => ({}),
        ...extra,
    });
}

const shownIds = () => [...document.querySelectorAll('tbody tr')].map(tr => Number(tr.dataset.id));

test('without rowFilter every row is shown in API order (unchanged behaviour)', async () => {
    setup();
    const t = makeTable({});
    await t.render(document.getElementById('host'));
    assert.deepEqual(shownIds(), [1, 2, 3]);
});

test('rowFilter decides visible rows/order; onRendered gets (all, visible)', async () => {
    setup();
    const seen = [];
    let keep = () => true;
    const t = makeTable({
        rowFilter: (data) => data.filter(r => keep(r)).sort((a, b) => a.name.localeCompare(b.name, 'el')),
        onRendered: (all, visible) => seen.push([all.length, visible.map(r => r.id)]),
    });
    await t.render(document.getElementById('host'));
    assert.deepEqual(shownIds(), [2, 3, 1]);
    assert.deepEqual(seen.at(-1), [3, [2, 3, 1]]);

    keep = (r) => r.id !== 3;
    t.renderTable();                                   // χωρίς νέο fetch
    assert.deepEqual(shownIds(), [2, 1]);
    assert.deepEqual(seen.at(-1), [3, [2, 1]]);
    assert.equal(t.data.length, 3);                    // τα δεδομένα μένουν ολόκληρα
});

test('filter that hides everything shows a filter message, not the «no records» state', async () => {
    setup();
    const seen = [];
    const t = makeTable({ rowFilter: () => [], onRendered: (all, vis) => seen.push([all.length, vis.length]) });
    await t.render(document.getElementById('host'));
    const text = document.getElementById('host').textContent;
    assert.match(text, /Καμία εγγραφή με αυτά τα φίλτρα/);
    assert.doesNotMatch(text, /Δεν υπάρχουν εγγραφές/);
    assert.deepEqual(seen.at(-1), [3, 0]);
});

test('empty data keeps the «no records» state and still notifies', async () => {
    setup();
    const seen = [];
    const t = makeTable({ rowFilter: (d) => d, onRendered: (all, vis) => seen.push([all.length, vis.length]) }, []);
    await t.render(document.getElementById('host'));
    assert.match(document.getElementById('host').textContent, /Δεν υπάρχουν εγγραφές/);
    assert.deepEqual(seen.at(-1), [0, 0]);
});
