/**
 * jsdom render + interaction tests for the timetable modals
 * (components/compare_modal.js, components/substitute_modal.js).
 *
 * These are classic-script globals in the browser; here we require them as
 * CommonJS and supply the globals they read (Modal/Toast/API/TimetableHelpers/
 * document) via Node's `global`, with a jsdom DOM. The Modal stub injects the
 * modal HTML into the document so getElementById/querySelector resolve.
 *
 * Run via `npm test` (node --test) — needs the jsdom devDependency.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');

const CompareModal = require('../components/compare_modal.js');
const SubstituteModal = require('../components/substitute_modal.js');

function setup() {
    const dom = new JSDOM('<!DOCTYPE html><body></body>');
    global.window = dom.window;
    global.document = dom.window.document;
    global.TimetableHelpers = require('../views/timetable_helpers.js');
    const calls = { toastError: [], compare: null, subs: null };
    global.Toast = { error: (m) => calls.toastError.push(m), success() {}, info() {} };
    global.Modal = {
        open(_title, html) {
            const wrap = global.document.createElement('div');
            wrap.innerHTML = html;
            global.document.body.appendChild(wrap);
        },
        close() {},
    };
    global.API = {
        solver: {
            compare: async (ids) => {
                calls.compare = ids;
                return { metrics: [{ name: 'A', solution_id: 1, score: 1 }], winners: {} };
            },
            substituteSuggestions: async (sid, tid, dow) => {
                calls.subs = [sid, tid, dow];
                return { affected_slots: [], stats: {} };
            },
        },
        teachers: { list: async () => [{ id: 1, name: 'Καθ Α' }, { id: 2, name: 'Καθ Β' }] },
    };
    return { calls };
}

const flush = () => new Promise(r => setTimeout(r, 0));
const click = (id) =>
    global.document.getElementById(id).dispatchEvent(new global.window.Event('click'));


test('CompareModal.open: run button + one checkbox per other solution', () => {
    const { calls } = setup();
    CompareModal.open([
        { id: 1, name: 'Cur', status: 'optimal', score: 100 },
        { id: 2, name: 'B', status: 'feasible', score: 120 },
        { id: 3, name: 'C', status: 'optimal', score: 90 },
    ], 1);
    assert.ok(global.document.getElementById('cmp-run'), 'run button present');
    assert.equal(global.document.querySelectorAll('.cmp-pick').length, 2);
    assert.equal(calls.toastError.length, 0);
});

test('CompareModal.open: no other solutions → warn, no modal', () => {
    const { calls } = setup();
    CompareModal.open([{ id: 1, name: 'Cur', status: 'optimal' }], 1);
    assert.equal(global.document.getElementById('cmp-run'), null);
    assert.equal(calls.toastError.length, 1);
});

test('CompareModal: clicking run compares [current, ...picked] and renders', async () => {
    const { calls } = setup();
    CompareModal.open([{ id: 1, name: 'Cur' }, { id: 2, name: 'B' }], 1);
    global.document.querySelector('.cmp-pick').checked = true;
    click('cmp-run');
    await flush();
    assert.deepEqual(calls.compare, [1, 2]);
    assert.match(global.document.getElementById('cmp-result').innerHTML, /data-table/);
});

test('CompareModal.renderResult delegates to the pure builder', () => {
    setup();
    const el = global.document.createElement('div');
    CompareModal.renderResult({ metrics: [] }, el);
    assert.match(el.innerHTML, /Δεν επιστράφηκαν metrics/);
});

test('SubstituteModal.open: teacher options + day options + find button', async () => {
    setup();
    await SubstituteModal.open(1, [], 5);
    assert.ok(global.document.getElementById('sub-find'));
    assert.equal(global.document.querySelectorAll('#sub-teacher option').length, 2);
    assert.equal(global.document.querySelectorAll('#sub-day option').length, 5);
});

test('SubstituteModal.open: teacher-load failure → warn, no modal', async () => {
    const { calls } = setup();
    global.API.teachers.list = async () => { throw new Error('boom'); };
    await SubstituteModal.open(1, [], 5);
    assert.equal(global.document.getElementById('sub-find'), null);
    assert.equal(calls.toastError.length, 1);
});

test('SubstituteModal: clicking find calls substituteSuggestions with the selection', async () => {
    const { calls } = setup();
    await SubstituteModal.open(7, [], 5);
    global.document.getElementById('sub-teacher').value = '2';
    global.document.getElementById('sub-day').value = '1';
    click('sub-find');
    await flush();
    assert.deepEqual(calls.subs, [7, 2, 1]);
});
