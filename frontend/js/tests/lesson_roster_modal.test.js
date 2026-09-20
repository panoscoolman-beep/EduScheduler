/**
 * 👥 LessonRosterModal: ποιοι παρακολουθούν, τι δείχνει η σύνοψη, και η ροή
 * αποθήκευσης με επιβεβαίωση σε επικάλυψη.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const R = require('../components/lesson_roster_modal.js');

const STUDENTS = [
    { student_id: 1, name: 'ΜΟΥΤΑΦΗΣ ΙΓΝΑΤΗΣ', grade: 'Β΄', from_class: true, attends: false, source: 'τμήμα' },
    { student_id: 2, name: 'ΚΑΣΙΑΚΟΣ ΑΝΔΡΟΜΑΧΗ', grade: 'Β΄', from_class: true, attends: true, source: 'τμήμα' },
    { student_id: 3, name: 'ΠΑΣΒΟΥΡΗ ΔΗΜΗΤΡΑ', grade: 'Β΄', from_class: false, attends: true, source: 'άλλο τμήμα' },
];

test('attendingIds / pickerItems: το τμήμα πρώτα, μετά οι υπόλοιποι μαθητές', () => {
    assert.deepEqual(R.attendingIds(STUDENTS), [2, 3]);
    const items = R.pickerItems(STUDENTS, [
        { id: 3, first_name: 'ΔΗΜΗΤΡΑ', last_name: 'ΠΑΣΒΟΥΡΗ', grade: 'Β΄' },
        { id: 9, first_name: 'ΝΙΚΟΣ', last_name: 'ΠΑΠΠΑΣ', grade: 'Α΄' },
    ]);
    assert.deepEqual(items.map(i => [i.id, i.from_class]), [[1, true], [2, true], [3, false], [9, false]]);
    assert.equal(items.at(-1).name, 'ΠΑΠΠΑΣ ΝΙΚΟΣ');
});

test('summary: πόσοι παρακολουθούν, πόσοι εξαιρούνται, πόσοι από αλλού', () => {
    assert.equal(R.summary(STUDENTS, [2, 3]), '2 παρακολουθούν · 1 εξαιρούνται από το τμήμα · 1 από άλλο τμήμα');
    assert.equal(R.summary(STUDENTS, [1, 2]), '2 παρακολουθούν');
    assert.equal(R.summary(STUDENTS, []), '0 παρακολουθούν · 2 εξαιρούνται από το τμήμα');
});

test('headerHtml: στοιχεία κάρτας με escaping', () => {
    const html = R.headerHtml({ subject_name: 'ΦΥΣΙΚΗ <Β>', periods_per_week: 2 }, { class_name: 'ΤΜΗΜΑ & Α' });
    assert.ok(html.includes('ΦΥΣΙΚΗ &lt;Β&gt;') && html.includes('ΤΜΗΜΑ &amp; Α') && html.includes('2 ώρες'));
    assert.ok(html.includes('id="roster-picker"'));
});

test('ροή: αλλαγή λίστας → 409 επικάλυψη → επιβεβαίωση → αποθήκευση με force', async () => {
    const dom = new JSDOM('<!DOCTYPE html><body><div id="modal-body"></div></body>');
    global.window = dom.window;
    global.document = dom.window.document;
    const opened = [];
    global.Modal = {
        open(title, body, onSave) { opened.push({ title, onSave }); document.getElementById('modal-body').innerHTML = body; },
        close() {},
    };
    const toasts = [];
    global.Toast = { success: (m) => toasts.push(m), error: (m) => toasts.push(`ERR ${m}`) };
    let onChange = null;
    global.StudentPicker = { mount: (el, opts) => { onChange = opts.onChange; return null; } };
    const calls = [];
    let reloaded = 0;
    global.API = {
        lessons: {
            students: async () => ({ lesson_id: 7, class_name: 'ΤΜΗΜΑ Α', students: STUDENTS }),
            setStudents: async (id, body, force) => {
                calls.push([id, body.attending, force]);
                if (!force) {
                    const err = new Error('clash');
                    err.status = 409;
                    err.detail = { requires_force: true, message: 'ΠΑΣΒΟΥΡΗ ΔΗΜΗΤΡΑ — Δευ 1η: ΧΗΜΕΙΑ (Β2)' };
                    throw err;
                }
                return { attending: body.attending.length };
            },
        },
        students: { list: async () => [] },
    };
    await R.open({ id: 7, subject_name: 'ΦΥΣΙΚΗ', periods_per_week: 2 }, async () => { reloaded += 1; });
    assert.equal(document.getElementById('roster-summary').textContent,
                 '2 παρακολουθούν · 1 εξαιρούνται από το τμήμα · 1 από άλλο τμήμα');
    onChange([1, 2, 3]);
    assert.equal(document.getElementById('roster-summary').textContent, '3 παρακολουθούν · 1 από άλλο τμήμα');
    await opened[1].onSave();
    assert.match(opened[2].title, /Επικάλυψη/);
    await opened[2].onSave();
    assert.deepEqual(calls, [[7, [1, 2, 3], false], [7, [1, 2, 3], true]]);
    assert.equal(reloaded, 1);
    assert.ok(toasts.at(-1).includes('3 μαθητές'));
});
