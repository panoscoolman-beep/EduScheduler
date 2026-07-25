/**
 * Pure data/HTML helpers for the Lessons view (no DOM, no globals).
 *
 * Dual-mode όπως το timetable_helpers.js: στον browser ορίζει το global
 * `LessonsHelpers`, στο Node εξάγεται με module.exports για τα unit tests.
 */
const LessonsHelpers = {
    _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    /**
     * Σημάδεψε ποια μαθήματα του σεναρίου-πηγής υπάρχουν ήδη στο ενεργό
     * (ίδιο subject+teacher+class → ο ίδιος dedup κανόνας με τον server).
     * Pure: δύο λίστες μέσα, [{...lesson, exists}] έξω.
     */
    markTermImportDuplicates(sourceLessons, activeLessons) {
        const triple = (l) => `${l.subject_id}|${l.teacher_id}|${l.class_id}`;
        const existing = new Set((activeLessons || []).map(triple));
        return (sourceLessons || []).map(l => ({
            ...l,
            exists: existing.has(triple(l)),
        }));
    },

    /**
     * Build the picker list: checkbox ανά μάθημα, τα ήδη υπάρχοντα
     * disabled με badge «υπάρχει ήδη». Pure HTML string.
     */
    buildTermImportListHtml(markedLessons) {
        if (!markedLessons.length) {
            return '<p class="text-muted">Το σενάριο-πηγή δεν έχει μαθήματα-κάρτες.</p>';
        }
        const esc = LessonsHelpers._esc;
        const importable = markedLessons.filter(l => !l.exists).length;
        const rows = markedLessons.map(l => {
            const label = `${esc(l.subject_name || '?')} — ${esc(l.class_name || '?')}`
                + ` — ${esc(l.teacher_name || '?')}`
                + ` <span class="text-muted">(${l.periods_per_week} ώρες/εβδ)</span>`;
            if (l.exists) {
                return `
                    <label class="term-import-row term-import-exists">
                        <input type="checkbox" disabled>
                        <span>${label}</span>
                        <span class="term-import-badge">υπάρχει ήδη</span>
                    </label>`;
            }
            return `
                <label class="term-import-row">
                    <input type="checkbox" class="term-import-check"
                           value="${l.id}" checked>
                    <span>${label}</span>
                </label>`;
        }).join('');

        return `
            <div class="term-import-toolbar">
                <label style="cursor:pointer;">
                    <input type="checkbox" id="term-import-all" checked>
                    Επιλογή όλων (<span id="term-import-count">${importable}</span> προς εισαγωγή)
                </label>
            </div>
            <div class="term-import-list">${rows}</div>`;
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = LessonsHelpers;
}
