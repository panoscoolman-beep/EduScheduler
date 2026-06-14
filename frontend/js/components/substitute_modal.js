/**
 * Substitute-teacher modal (extracted from views/timetable.js).
 *
 * Opens a modal to pick an absent teacher + day, then shows the affected
 * lessons with candidate substitutes / reschedule options (HTML built by the
 * pure TimetableHelpers.buildSubstituteResultHtml). Read-only — the user
 * applies a choice via the existing drag-drop UI. Dual-mode: classic-script
 * global `SubstituteModal` in the browser, module.exports under Node. Depends
 * on Modal, Toast, API, TimetableHelpers.
 */
const SubstituteModal = {
    async open(solutionId, periods, daysCount) {
        let teachers;
        try {
            teachers = await API.teachers.list();
        } catch (err) {
            Toast.error(`Αποτυχία φόρτωσης καθηγητών: ${err.message}`);
            return;
        }

        const dayNames = ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη',
                          'Παρασκευή', 'Σάββατο', 'Κυριακή'];
        const teacherOptions = teachers.map(t =>
            `<option value="${t.id}">${TimetableHelpers.esc(t.name)}</option>`
        ).join('');
        const dayOptions = Array.from({length: daysCount}, (_, i) =>
            `<option value="${i}">${dayNames[i]}</option>`
        ).join('');

        Modal.open(
            '👤 Αντικατάσταση Καθηγητή',
            `
            <p class="text-muted" style="margin-bottom:1rem;">
                Επίλεξε τον καθηγητή που λείπει και τη μέρα. Θα δούμε
                τα μαθήματα που επηρεάζονται και προτάσεις για κάθε ένα.
            </p>
            <div style="display:flex; gap:1rem; margin-bottom:1rem; flex-wrap:wrap;">
                <div class="form-group" style="flex:1; min-width:200px; margin:0;">
                    <label class="form-label">Καθηγητής</label>
                    <select class="form-select" id="sub-teacher">${teacherOptions}</select>
                </div>
                <div class="form-group" style="flex:1; min-width:150px; margin:0;">
                    <label class="form-label">Μέρα</label>
                    <select class="form-select" id="sub-day">${dayOptions}</select>
                </div>
            </div>
            <div style="text-align:right;">
                <button class="btn btn-primary" id="sub-find">🔍 Βρες προτάσεις</button>
            </div>
            <div id="sub-result" style="margin-top:1.5rem;"></div>
            `,
            null,
            { hideFooter: true }
        );

        document.getElementById('sub-find').addEventListener('click', async () => {
            const teacherId = parseInt(document.getElementById('sub-teacher').value);
            const dayOfWeek = parseInt(document.getElementById('sub-day').value);
            const resultEl = document.getElementById('sub-result');
            resultEl.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';
            try {
                const data = await API.solver.substituteSuggestions(
                    solutionId, teacherId, dayOfWeek);
                SubstituteModal.renderResult(data, resultEl, dayNames[dayOfWeek]);
            } catch (err) {
                resultEl.innerHTML = `<p class="text-muted">Σφάλμα: ${TimetableHelpers.esc(err.message)}</p>`;
            }
        });
    },

    renderResult(data, mountEl, dayLabel) {
        mountEl.innerHTML = TimetableHelpers.buildSubstituteResultHtml(data, dayLabel);
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = SubstituteModal;
}
