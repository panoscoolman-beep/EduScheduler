/**
 * InsightsModal — τα τρία «αναλυτικά» dialogs του ωρολογίου:
 *
 *   openDiff(solutions, currentId)  «Τι άλλαξε;» ανάμεσα σε δύο λύσεις
 *   openViolations(solutionId)      «Γιατί αυτό το score;» (soft violations)
 *   openBulkExport(solutionId)      Μαζική εκτύπωση / Excel export
 *
 * Λεπτό component: το HTML των αποτελεσμάτων χτίζεται από pure builders στο
 * TimetableHelpers (unit-tested), εδώ ζει μόνο το Modal/API wiring.
 * Dual-mode όπως τα υπόλοιπα components (browser global + module.exports).
 */
const InsightsModal = {
    /** Διάλεξε «άλλη» λύση και δες slot-level diff με την τρέχουσα. */
    openDiff(solutions, currentId) {
        const others = solutions.filter(s => s.id !== currentId);
        if (!others.length) {
            Toast.info('Δεν υπάρχει άλλη λύση για σύγκριση διαφορών.');
            return;
        }
        const body = `
            <div class="form-group">
                <label class="form-label">Σύγκριση της τρέχουσας με</label>
                <select class="form-select" id="diff-other">
                    ${others.map(s => `<option value="${s.id}">${TimetableHelpers.esc(s.name)}</option>`).join('')}
                </select>
            </div>
            <div id="diff-result"></div>`;
        // Το Modal μένει ανοιχτό μέχρι να κληθεί Modal.close() — εδώ ποτέ:
        // τα αποτελέσματα ζωγραφίζονται μέσα στο ίδιο dialog.
        Modal.open('🔀 Τι άλλαξε;', body, async () => {
            const otherId = parseInt(document.getElementById('diff-other').value);
            try {
                const diff = await API.solver.diff(currentId, otherId);
                document.getElementById('diff-result').innerHTML =
                    TimetableHelpers.buildDiffResultHtml(diff);
            } catch (err) {
                Toast.error(`Το diff απέτυχε: ${err.message}`);
            }
        }, { saveText: '🔍 Δείξε διαφορές', wide: true });
    },

    /** Ονομαστική αναφορά soft-constraint παραβιάσεων της λύσης. */
    async openViolations(solutionId) {
        try {
            const rep = await API.solver.violations(solutionId);
            // Ο τίτλος μπαίνει με textContent (Modal.open) — ΟΧΙ esc, θα φαινόταν διπλο-escaped.
            Modal.open(
                `⚖️ Ποιότητα λύσης — ${rep.solution.name || ''}`,
                TimetableHelpers.buildViolationsHtml(rep),
                null,
                { hideFooter: true },
            );
        } catch (err) {
            Toast.error(`Η αναφορά απέτυχε: ${err.message}`);
        }
    },

    /** Μαζική εκτύπωση (ένα έγγραφο, page-break ανά οντότητα) ή Excel. */
    openBulkExport(solutionId) {
        const body = `
            <div class="form-group">
                <label class="form-label">Τι θέλεις;</label>
                <label style="display:block"><input type="radio" name="bx-kind" value="print" checked> 🖨️ Εκτύπωση — όλα σε ένα έγγραφο (μία σελίδα ο καθένας)</label>
                <label style="display:block"><input type="radio" name="bx-kind" value="xlsx"> 📊 Excel — ένα φύλλο ο καθένας</label>
            </div>
            <div class="form-group">
                <label class="form-label">Ανά</label>
                <select class="form-select" id="bx-mode">
                    <option value="teachers">Καθηγητή</option>
                    <option value="classes">Τμήμα</option>
                    <option value="rooms">Αίθουσα (μόνο Excel)</option>
                </select>
            </div>`;
        Modal.open('📦 Μαζική εξαγωγή προγραμμάτων', body, () => {
            const kind = document.querySelector('input[name="bx-kind"]:checked').value;
            const mode = document.getElementById('bx-mode').value;
            if (kind === 'print') {
                if (mode === 'rooms') {
                    Toast.info('Η εκτύπωση υποστηρίζει Καθηγητές ή Τμήματα — για αίθουσες διάλεξε Excel.');
                    return;  // μείνε ανοιχτό για να αλλάξει επιλογή
                }
                window.open(`/api/exports/print?solution_id=${solutionId}&all=${mode}`, '_blank');
            } else {
                window.open(`/api/exports/xlsx?solution_id=${solutionId}&mode=${mode}`, '_blank');
            }
            Modal.close();
        }, { saveText: '⬇️ Εξαγωγή' });
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = InsightsModal;
}
