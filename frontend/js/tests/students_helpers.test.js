/**
 * Unit tests for frontend/js/views/students_helpers.js (σειρά + φίλτρα λίστας).
 * Run with: node --test frontend/js/tests/
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');

const H = require('../views/students_helpers.js');

const GRADES = ['Ε΄ Δημοτικού', 'ΣΤ΄ Δημοτικού', 'Α΄ Γυμνασίου', 'Β΄ Γυμνασίου', 'Γ΄ Γυμνασίου',
    'Α΄ Λυκείου', 'Α΄ ΕΠΑΛ', 'Β΄ Λυκείου', 'Β΄ ΕΠΑΛ', 'Γ΄ Λυκείου', 'Γ΄ ΕΠΑΛ'];
const THETIKI = 'Θετικών Σπουδών (Θετική)';
const OIK = 'Σπουδών Οικονομίας & Πληροφορικής (4ο πεδίο)';
const YGEIA = 'Σπουδών Υγείας (3ο πεδίο)';

const S = [
    { id: 1, last_name: 'Παπαδόπουλος', first_name: 'Νίκος', grade: 'Γ΄ Λυκείου', track: YGEIA, phone: '6900000001' },
    { id: 2, last_name: 'Άγγελος', first_name: 'Μαρία', grade: 'Β΄ Λυκείου', track: THETIKI },
    { id: 3, last_name: 'Αλεξίου', first_name: 'Κώστας', grade: 'Β΄ Λυκείου', track: 'Ανθρωπιστικών Σπουδών (Θεωρητική)' },
    { id: 4, last_name: 'αλεξίου', first_name: 'Άννα', grade: null, track: null, email: 'anna@x.gr' },
    { id: 5, last_name: 'Ζήσης', first_name: 'Γιώργος', grade: 'Γ΄ Λυκείου', track: OIK },
    { id: 6, last_name: 'Βλάχος', first_name: 'Πέτρος', grade: 'Β΄ ΕΠΑΛ', track: 'Πληροφορικής' },
    { id: 7, last_name: 'Ιωάννου', first_name: 'Ελένη', grade: 'Παλιά τάξη', track: '' },
    { id: 8, last_name: 'Όμηρος', first_name: 'Άρης', grade: 'Α΄ Γυμνασίου', track: null },
];
const ids = (list) => list.map(s => s.id);
const f = (over) => ({ ...H.emptyFilter(), ...over });

test('sortByName: Greek order by surname, accents do not move a name, then first name', () => {
    // «Άγγελος»/«Όμηρος» μπαίνουν στο γράμμα τους (όχι στην αρχή όπως θα
    // έκανε σύγκριση κωδικών)· ίδιο επώνυμο → κατά όνομα (Άννα πριν Κώστας).
    assert.deepEqual(ids(H.sortByName(S)), [2, 4, 3, 6, 5, 7, 8, 1]);
    assert.notEqual(H.sortByName(S), S);                    // δεν πειράζει την είσοδο
    assert.deepEqual(H.sortByName(null), []);
});

test('applyFilter: OR inside a group, AND across groups, result stays alphabetical', () => {
    assert.deepEqual(ids(H.applyFilter(S, H.emptyFilter())), [2, 4, 3, 6, 5, 7, 8, 1]);
    assert.deepEqual(ids(H.applyFilter(S, f({ grades: ['Β΄ Λυκείου'] }))), [2, 3]);
    assert.deepEqual(ids(H.applyFilter(S, f({ grades: ['Γ΄ Λυκείου', 'Β΄ Λυκείου'] }))), [2, 3, 5, 1]);
    assert.deepEqual(ids(H.applyFilter(S, f({ tracks: ['Πληροφορικής'] }))), [6]);
    assert.deepEqual(ids(H.applyFilter(S, f({ grades: ['Γ΄ Λυκείου'], tracks: [YGEIA] }))), [1]);
    assert.deepEqual(ids(H.applyFilter(S, f({ grades: ['Β΄ Λυκείου'], tracks: [YGEIA] }))), []);
});

test('applyFilter: empty grade means «Χωρίς τάξη»', () => {
    assert.deepEqual(ids(H.applyFilter(S, f({ grades: [''] }))), [4]);
    assert.deepEqual(ids(H.applyFilter(S, f({ grades: ['', 'Α΄ Γυμνασίου'] }))), [4, 8]);
});

test('search: accent/case-insensitive, every word must match name, email or phone', () => {
    assert.deepEqual(ids(H.applyFilter(S, f({ search: 'αλεξιου' }))), [4, 3]);
    assert.deepEqual(ids(H.applyFilter(S, f({ search: 'ΑΝΝΑ αλεξ' }))), [4]);
    assert.deepEqual(ids(H.applyFilter(S, f({ search: '6900000001' }))), [1]);
    assert.deepEqual(ids(H.applyFilter(S, f({ search: 'anna@' }))), [4]);
    assert.deepEqual(ids(H.applyFilter(S, f({ search: '   ' }))).length, S.length);
    // Αναζήτηση + τάξη μαζί
    assert.deepEqual(ids(H.applyFilter(S, f({ search: 'αλεξ', grades: ['Β΄ Λυκείου'] }))), [3]);
});

test('gradeOptions: catalog order, unknown values after, «Χωρίς τάξη» last, with counts', () => {
    const opts = H.gradeOptions(S, GRADES);
    assert.deepEqual(opts.map(o => o.label),
        ['Α΄ Γυμνασίου', 'Β΄ Λυκείου', 'Β΄ ΕΠΑΛ', 'Γ΄ Λυκείου', 'Παλιά τάξη', 'Χωρίς τάξη']);
    assert.deepEqual(opts.map(o => o.count), [1, 2, 1, 2, 1, 1]);
    assert.equal(opts[opts.length - 1].value, '');
    assert.deepEqual(H.gradeOptions([], GRADES), []);
});

test('trackOptions: only tracks of the selected grades (all when none selected)', () => {
    // 5 διακριτές (οι κενές/null δεν είναι επιλογή)
    assert.equal(H.trackOptions(S, H.emptyFilter()).length, 5);
    assert.deepEqual(H.trackOptions(S, f({ grades: ['Γ΄ Λυκείου'] })).map(o => [o.value, o.count]),
        [[OIK, 1], [YGEIA, 1]]);                          // αλφαβητικά: Οικονομίας < Υγείας
    assert.deepEqual(H.trackOptions(S, f({ grades: ['Α΄ Γυμνασίου'] })), []);
});

test('toggle adds/removes without mutating; prune drops choices that no longer apply', () => {
    const a = H.emptyFilter();
    const b = H.toggle(a, 'grades', 'Β΄ Λυκείου');
    assert.deepEqual(a.grades, []);
    assert.deepEqual(b.grades, ['Β΄ Λυκείου']);
    assert.deepEqual(H.toggle(b, 'grades', 'Β΄ Λυκείου').grades, []);

    // «Πληροφορικής» δεν ανήκει στη Β΄ Λυκείου → φεύγει· η «Θετική» μένει.
    const p = H.prune(f({ grades: ['Β΄ Λυκείου'], tracks: ['Πληροφορικής', THETIKI] }), S);
    assert.deepEqual(p.tracks, [THETIKI]);
    // Τάξη χωρίς κανέναν μαθητή → φεύγει (αλλιώς θα έκρυβε τους πάντες χωρίς chip).
    assert.deepEqual(H.prune(f({ grades: ['Ε΄ Δημοτικού'] }), S).grades, []);
    assert.equal(H.prune(f({ search: 'x' }), S).search, 'x');
});

test('exportQuery / withFilter: repeatable params, encoded, appended correctly', () => {
    assert.equal(H.exportQuery(H.emptyFilter()), '');
    const q = H.exportQuery(f({ grades: ['Β΄ Λυκείου', ''], tracks: [OIK], search: ' παπ ' }));
    const params = new URLSearchParams(q);
    assert.deepEqual(params.getAll('grade'), ['Β΄ Λυκείου', '']);
    assert.deepEqual(params.getAll('track'), [OIK]);            // το «&» δεν σπάει το query
    assert.equal(params.get('q'), 'παπ');

    const one = f({ grades: ['Γ΄ Λυκείου'] });
    assert.equal(H.withFilter('/x', H.emptyFilter()), '/x');
    assert.match(H.withFilter('/api/exports/students/print', one), /^\/api\/exports\/students\/print\?grade=/);
    assert.match(H.withFilter('/api/exports/students?format=csv', one), /\?format=csv&grade=/);
});

test('isActive and countText', () => {
    assert.equal(H.isActive(H.emptyFilter()), false);
    assert.equal(H.isActive(f({ search: '   ' })), false);
    assert.equal(H.isActive(f({ grades: [''] })), true);
    assert.equal(H.countText(62, 62), '62 μαθητές');
    assert.equal(H.countText(18, 62), 'Εμφανίζονται 18 από 62');
});

test('buildChipsHtml: pressed state, escaping, no track row when there are no tracks', () => {
    const html = H.buildChipsHtml({
        gradeOpts: [{ value: 'Β΄ Λυκείου', label: 'Β΄ Λυκείου', count: 2 },
                    { value: '<b>', label: '<b>', count: 1 },
                    { value: '', label: 'Χωρίς τάξη', count: 1 }],
        trackOpts: [],
        filter: f({ grades: ['Β΄ Λυκείου'] }),
    });
    assert.match(html, /class="sf-chip is-on" data-kind="grades" data-value="Β΄ Λυκείου" aria-pressed="true"/);
    assert.match(html, /data-value="&lt;b&gt;" aria-pressed="false">&lt;b&gt; <small>1<\/small>/);
    assert.match(html, /data-value="" aria-pressed="false">Χωρίς τάξη/);
    assert.doesNotMatch(html, /Κατεύθυνση/);
    const withTracks = H.buildChipsHtml({
        gradeOpts: [], trackOpts: [{ value: OIK, label: OIK, count: 3 }], filter: f({ tracks: [OIK] }),
    });
    assert.match(withTracks, /Κατεύθυνση \/ Τομέας/);
    assert.match(withTracks, /data-kind="tracks" data-value="Σπουδών Οικονομίας &amp; Πληροφορικής/);
});
