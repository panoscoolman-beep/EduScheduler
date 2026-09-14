/**
 * Pure helpers για τη λίστα Μαθητών: αλφαβητική σειρά, φίλτρα τάξης /
 * κατεύθυνσης / αναζήτησης, και το HTML της μπάρας φίλτρων (no DOM, no globals).
 *
 * Dual-mode όπως το lessons_helpers.js: στον browser ορίζει το global
 * `StudentsHelpers`, στο Node εξάγεται με module.exports για τα unit tests.
 *
 * Φίλτρο = { grades: [], tracks: [], search: '' }. Μέσα σε κάθε ομάδα ισχύει
 * «Η» (Β΄ ή Γ΄ Λυκείου), ανάμεσα στις ομάδες «ΚΑΙ» (Γ΄ Λυκείου ΚΑΙ 4ο πεδίο).
 * Η κενή τιμή '' στις τάξεις σημαίνει «Χωρίς τάξη». Ίδιοι κανόνες με το
 * backend (`_filter_students` στο backend/routers/exports.py), ώστε η
 * εκτύπωση/εξαγωγή να βγάζει ακριβώς ό,τι βλέπει ο χρήστης.
 */
const StudentsHelpers = {
    NO_GRADE: '',
    NO_GRADE_LABEL: 'Χωρίς τάξη',

    _collator: new Intl.Collator('el', { sensitivity: 'base', numeric: true }),

    esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    /** Χωρίς τόνους/διαλυτικά, πεζά, τελικό ς → σ (για αναζήτηση). */
    normalize(s) {
        return String(s == null ? '' : s)
            .normalize('NFD').replace(/[̀-ͯ]/g, '')
            .toLowerCase().replace(/ς/g, 'σ').trim();
    },

    /** Επώνυμο → όνομα → id, με ελληνική σειρά (ο τόνος δεν αλλάζει τη θέση). */
    compareByName(a, b) {
        const c = StudentsHelpers._collator;
        return c.compare(a?.last_name || '', b?.last_name || '')
            || c.compare(a?.first_name || '', b?.first_name || '')
            || (a?.id || 0) - (b?.id || 0);
    },

    sortByName(students) {
        return (students || []).slice().sort(StudentsHelpers.compareByName);
    },

    emptyFilter() {
        return { grades: [], tracks: [], search: '' };
    },

    isActive(filter) {
        const f = filter || {};
        return Boolean((f.grades || []).length || (f.tracks || []).length
            || StudentsHelpers.normalize(f.search));
    },

    _gradeOf(student) {
        return (student?.grade || '').trim();
    },

    _trackOf(student) {
        return (student?.track || '').trim();
    },

    /** Κάθε λέξη της αναζήτησης πρέπει να υπάρχει σε επώνυμο/όνομα/email/τηλέφωνο. */
    _matchesSearch(student, search) {
        const words = StudentsHelpers.normalize(search).split(/\s+/).filter(Boolean);
        if (!words.length) return true;
        const hay = StudentsHelpers.normalize(
            [student.last_name, student.first_name, student.email, student.phone].join(' '));
        return words.every(w => hay.includes(w));
    },

    _matchesGrades(student, grades) {
        return !(grades || []).length || grades.includes(StudentsHelpers._gradeOf(student));
    },

    _matchesTracks(student, tracks) {
        return !(tracks || []).length || tracks.includes(StudentsHelpers._trackOf(student));
    },

    matches(student, filter) {
        const f = filter || {};
        return StudentsHelpers._matchesGrades(student, f.grades)
            && StudentsHelpers._matchesTracks(student, f.tracks)
            && StudentsHelpers._matchesSearch(student, f.search);
    },

    /** Οι μαθητές που περνούν το φίλτρο, πάντα αλφαβητικά κατά επώνυμο. */
    applyFilter(students, filter) {
        return StudentsHelpers.sortByName(
            (students || []).filter(s => StudentsHelpers.matches(s, filter)));
    },

    /**
     * Επιλογές τάξης: μόνο όσες έχουν μαθητές, στη σειρά του καταλόγου· μετά
     * τυχόν παλιές τιμές εκτός καταλόγου, και τελευταία το «Χωρίς τάξη».
     * Ο μετρητής αγνοεί τα υπόλοιπα φίλτρα (δείχνει το μέγεθος της τάξης).
     */
    gradeOptions(students, catalogGrades) {
        const counts = new Map();
        for (const s of students || []) {
            const g = StudentsHelpers._gradeOf(s);
            counts.set(g, (counts.get(g) || 0) + 1);
        }
        const known = (catalogGrades || []).filter(g => counts.has(g));
        const extra = [...counts.keys()]
            .filter(g => g && !known.includes(g))
            .sort(StudentsHelpers._collator.compare);
        const order = known.concat(extra);
        if (counts.has(StudentsHelpers.NO_GRADE)) order.push(StudentsHelpers.NO_GRADE);
        return order.map(g => ({
            value: g,
            label: g || StudentsHelpers.NO_GRADE_LABEL,
            count: counts.get(g),
        }));
    },

    /**
     * Επιλογές κατεύθυνσης/τομέα: όσες υπάρχουν στους μαθητές των επιλεγμένων
     * τάξεων (ή όλων, αν δεν έχει επιλεγεί τάξη). Έτσι επιλέγοντας «Γ΄ Λυκείου»
     * μένουν μόνο τα πεδία της.
     */
    trackOptions(students, filter) {
        const grades = (filter || {}).grades || [];
        const counts = new Map();
        for (const s of students || []) {
            const t = StudentsHelpers._trackOf(s);
            if (!t || !StudentsHelpers._matchesGrades(s, grades)) continue;
            counts.set(t, (counts.get(t) || 0) + 1);
        }
        return [...counts.keys()]
            .sort(StudentsHelpers._collator.compare)
            .map(t => ({ value: t, label: t, count: counts.get(t) }));
    },

    /** Άναψε/σβήσε μια τιμή (kind = 'grades' | 'tracks'). Επιστρέφει νέο φίλτρο. */
    toggle(filter, kind, value) {
        const f = { ...StudentsHelpers.emptyFilter(), ...(filter || {}) };
        const list = (f[kind] || []).slice();
        const i = list.indexOf(value);
        if (i >= 0) list.splice(i, 1); else list.push(value);
        return { ...f, [kind]: list };
    },

    /**
     * Πέτα επιλογές που δεν προσφέρονται πια: τάξη χωρίς κανέναν μαθητή, ή
     * κατεύθυνση που δεν ανήκει στις επιλεγμένες τάξεις (π.χ. «Θετική» αφού
     * ξε-επιλέχθηκε η Β΄ Λυκείου) — αλλιώς θα έκρυβαν σιωπηλά μαθητές χωρίς
     * chip για να τις σβήσεις.
     */
    prune(filter, students) {
        const f = { ...StudentsHelpers.emptyFilter(), ...(filter || {}) };
        const present = new Set((students || []).map(s => StudentsHelpers._gradeOf(s)));
        const grades = f.grades.filter(g => present.has(g));
        const offered = new Set(
            StudentsHelpers.trackOptions(students, { ...f, grades }).map(o => o.value));
        return { ...f, grades, tracks: f.tracks.filter(t => offered.has(t)) };
    },

    /** Query string για εκτύπωση/εξαγωγή: grade=…&track=…&q=… (χωρίς «?»). */
    exportQuery(filter) {
        const f = filter || {};
        const parts = [];
        for (const g of f.grades || []) parts.push('grade=' + encodeURIComponent(g));
        for (const t of f.tracks || []) parts.push('track=' + encodeURIComponent(t));
        const q = String(f.search || '').trim();
        if (q) parts.push('q=' + encodeURIComponent(q));
        return parts.join('&');
    },

    /** URL με τα ενεργά φίλτρα, σωστά ενωμένα με ό,τι query έχει ήδη. */
    withFilter(url, filter) {
        const q = StudentsHelpers.exportQuery(filter);
        if (!q) return url;
        return url + (url.includes('?') ? '&' : '?') + q;
    },

    countText(shown, total) {
        if (shown === total) return `${total} μαθητές`;
        return `Εμφανίζονται ${shown} από ${total}`;
    },

    _chipsHtml(kind, options, selected) {
        const esc = StudentsHelpers.esc;
        return options.map(o => {
            const on = selected.includes(o.value);
            return `<button type="button" class="sf-chip${on ? ' is-on' : ''}" data-kind="${kind}"`
                + ` data-value="${esc(o.value)}" aria-pressed="${on}">`
                + `${esc(o.label)} <small>${o.count}</small></button>`;
        }).join('');
    },

    /** Οι δύο σειρές chips (Τάξη, Κατεύθυνση/Τομέας). Pure HTML string. */
    buildChipsHtml({ gradeOpts, trackOpts, filter }) {
        const f = { ...StudentsHelpers.emptyFilter(), ...(filter || {}) };
        const rows = [];
        if ((gradeOpts || []).length) {
            rows.push(`<div class="sf-group"><span class="sf-group-label">Τάξη</span>`
                + `<div class="sf-chips">${StudentsHelpers._chipsHtml('grades', gradeOpts, f.grades)}</div></div>`);
        }
        if ((trackOpts || []).length) {
            rows.push(`<div class="sf-group"><span class="sf-group-label">Κατεύθυνση / Τομέας</span>`
                + `<div class="sf-chips">${StudentsHelpers._chipsHtml('tracks', trackOpts, f.tracks)}</div></div>`);
        }
        return rows.join('');
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = StudentsHelpers;
}
