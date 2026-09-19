/**
 * 📢 PublishModal: προεπιλογή/γρήγορες επιλογές παραληπτών, HTML, αποτελέσματα,
 * και η ροή στον browser (jsdom) με ψεύτικο API — κανένα πραγματικό email.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const P = require('../components/publish_modal.js');

const T = [
    { teacher_id: 1, teacher: 'Γεωργέλλης', email: 'g@x.gr', changed: true, hours: 44, message: 'm1',
      changes: { moved: [{}], added: [{}], removed: [] } },
    { teacher_id: 2, teacher: 'Γκούγκη <b>', email: 'k@x.gr', changed: false, hours: 1, message: 'm2',
      changes: { moved: [], added: [], removed: [] } },
    { teacher_id: 3, teacher: 'Χωρίς mail', email: '', changed: true, hours: 5, message: 'm3',
      changes: { moved: [{}], added: [], removed: [] } },
];
const PREVIEW = { first: false, affected: 2, unplaced: 1, teachers: T,
                  previous: { solution_name: 'ΧΕΙΜ', published_at: '2026-09-19T10:52:00' } };

test('προεπιλογή: όσοι έχουν αλλαγές ΚΑΙ email· γρήγορες επιλογές', () => {
    assert.deepEqual(P.defaultSelection(T), [1]);
    assert.deepEqual(P.selectionFor(T, 'all'), [1, 2]);
    assert.deepEqual(P.selectionFor(T, 'none'), []);
    assert.deepEqual(P.selectionFor(T, 'changed'), [1]);
    assert.equal(P.countText([1, 2]), '2 θα πάρουν email');
    assert.equal(P.countText([]), 'κανένα email');
});

test('buildHtml: badges, χωρίς email → disabled, escaping, Παλέτα, «τίποτα νέο»', () => {
    const html = P.buildHtml(PREVIEW, [1], 'me@x.gr');
    assert.ok(html.includes('2 αλλαγές') && html.includes('χωρίς αλλαγές'));
    assert.ok(/data-id="3"\s+disabled/.test(html));
    assert.ok(/data-id="1"\s+ checked/.test(html));
    assert.ok(html.includes('Γκούγκη &lt;b&gt;') && !html.includes('Γκούγκη <b>'));
    assert.ok(html.includes('1 ώρες είναι ακόμα στην Παλέτα') && html.includes('value="me@x.gr"'));
    assert.ok(!html.includes('<option value="3">'));                 // δοκιμή μόνο σε όσους έχουν email
    const first = P.buildHtml({ ...PREVIEW, first: true }, [], '');
    assert.ok(first.includes('Πρώτη δημοσίευση') && first.includes('νέο πρόγραμμα'));
    const none = P.buildHtml({ ...PREVIEW, affected: 0 }, [], '');
    assert.ok(none.includes('δεν άλλαξε τίποτα') && !none.includes('pub-telegram'));
    assert.ok(none.includes('pub-mail') && !none.includes('pub-note'));   // email ναι, νέα δημοσίευση όχι
    assert.equal(P.isResend({ ...PREVIEW, affected: 0 }), true);
    assert.equal(P.isResend(PREVIEW), false);
    assert.equal(P.isResend({ ...PREVIEW, first: true, affected: 0 }), false);
});

test('buildResultsHtml: μετρητές, σφάλματα με escaping, σε εξέλιξη vs ολοκληρώθηκε', () => {
    const detail = { email_state: 'sending', notify_telegram: true,
        emails: { requested: 2, sent: 1, failed: 1, pending: 0 },
        messages: [{ teacher: 'Α', email: { to: 'a@x', status: 'sent' } },
                   { teacher: 'Β', email: { to: 'b@x', status: 'failed', error: '<SMTP>' } },
                   { teacher: 'Γ', email: null }] };
    const html = P.buildResultsHtml(detail);
    assert.ok(html.includes('σε εξέλιξη') && html.includes('1 απέτυχαν') && html.includes('&lt;SMTP&gt;'));
    assert.ok(!html.includes('>Γ<'));
    assert.ok(P.buildResultsHtml({ ...detail, email_state: 'done' }).includes('Ολοκληρώθηκε'));
});

test('ροή: επιλογή «όλους» → δημοσίευση με τους σωστούς παραλήπτες → αποτελέσματα', async () => {
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
    const calls = [];
    global.API = { solver: {
        publishPreview: async () => PREVIEW,
        publish: async (sid, body) => { calls.push(['publish', sid, body]);
            return { id: 9, email_state: 'sending', notify_telegram: true, emails: { requested: 2, sent: 0 }, messages: [] }; },
        publication: async () => ({ id: 9, email_state: 'done', notify_telegram: true,
            emails: { requested: 2, sent: 2, failed: 0 }, messages: [] }),
        publishTestEmail: async (sid, body) => { calls.push(['test', sid, body]); return {}; },
    } };
    P.POLL_MS = 1;
    await P.open(37);
    assert.equal(document.getElementById('pub-count').textContent, '1 θα πάρει email');
    document.querySelector('.pub-select[data-mode="all"]').click();
    assert.equal(document.getElementById('pub-count').textContent, '2 θα πάρουν email');
    document.getElementById('pub-test-to').value = 'λάθος';
    await P._sendTest(37);
    assert.ok(toasts.at(-1).startsWith('ERR'));                        // άκυρο email → καμία κλήση
    document.getElementById('pub-test-to').value = 'me@x.gr';
    await P._sendTest(37);
    document.getElementById('pub-note').value = 'από Δευτέρα';
    await opened[1].onSave();
    assert.deepEqual(calls, [
        ['test', 37, { teacher_id: 1, to: 'me@x.gr' }],
        ['publish', 37, { note: 'από Δευτέρα', notify_telegram: true, email_teacher_ids: [1, 2] }],
    ]);
    assert.ok(document.getElementById('modal-body').textContent.includes('Ολοκληρώθηκε'));
});

test('τίποτα νέο: email για την τελευταία δημοσίευση — μόνο με επιλογή, χωρίς νέα δημοσίευση', async () => {
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
    const calls = [];
    const previous = { id: 4, solution_name: 'ΧΕΙΜ', published_at: '2026-09-19T10:52:00' };
    global.API = { solver: {
        publishPreview: async () => ({ ...PREVIEW, affected: 0, previous,
            teachers: T.map(t => ({ ...t, changed: false })) }),
        publish: async () => { calls.push('publish'); return {}; },
        publicationEmails: async (id, body) => { calls.push(['emails', id, body]);
            return { id, email_state: 'done', emails: { requested: 1, sent: 1 }, messages: [] }; },
        publication: async () => ({ email_state: 'done', emails: {}, messages: [] }),
    } };
    await P.open(37);
    assert.match(opened[1].title, /τελευταία δημοσίευση/);
    await opened[1].onSave();
    assert.ok(toasts.at(-1).startsWith('ERR'));                          // κανένας επιλεγμένος
    document.querySelector('.pub-mail[data-id="2"]').click();
    await opened[1].onSave();
    assert.deepEqual(calls, [['emails', 4, { teacher_ids: [2] }]]);      // ΟΧΙ νέα δημοσίευση
});
