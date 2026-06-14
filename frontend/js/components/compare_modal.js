/**
 * Compare-solutions modal (extracted from views/timetable.js).
 *
 * Opens a modal to pick other solutions and shows a side-by-side metrics
 * table (built by the pure TimetableHelpers.buildCompareResultHtml). Dual-mode:
 * a classic-script global `CompareModal` in the browser, module.exports under
 * Node for tests. Depends on the globals Modal, Toast, API, TimetableHelpers
 * (all loaded before it in index.html).
 */
const CompareModal = {
    /**
     * Open the compare modal. `solutions` is the full list, `currentId` the
     * one being viewed (auto-included in every comparison).
     */
    open(solutions, currentId) {
        const others = solutions.filter(s => s.id !== currentId);
        if (others.length === 0) {
            Toast.error('Χρειάζονται ≥2 solutions για σύγκριση. Δημιούργησε άλλο πρώτα.');
            return;
        }

        const optionsHtml = others.map(s =>
            `<label style="display:flex; align-items:center; gap:0.5rem; padding:0.4rem 0;">
                <input type="checkbox" class="cmp-pick" value="${s.id}">
                <span><strong>${s.name}</strong>
                <span class="text-muted" style="font-size:0.85em">— ${s.status}, score=${s.score?.toFixed(0) || '—'}</span></span>
            </label>`
        ).join('');

        Modal.open(
            '📊 Σύγκριση Λύσεων',
            `
            <p class="text-muted" style="margin-bottom:1rem;">
                Η τρέχουσα λύση συμπεριλαμβάνεται αυτόματα. Επίλεξε
                ≥1 ακόμα για side-by-side metrics.
            </p>
            <div style="margin-bottom:1rem;">${optionsHtml}</div>
            <div style="text-align:right;">
                <button class="btn btn-primary" id="cmp-run">📊 Σύγκρινε</button>
            </div>
            <div id="cmp-result" style="margin-top:1.5rem;"></div>
            `,
            null,
            { hideFooter: true }
        );

        document.getElementById('cmp-run').addEventListener('click', async () => {
            const picked = Array.from(document.querySelectorAll('.cmp-pick:checked'))
                .map(cb => parseInt(cb.value));
            if (picked.length === 0) {
                Toast.error('Επίλεξε τουλάχιστον μία λύση να συγκρίνεις');
                return;
            }
            const ids = [currentId, ...picked];
            try {
                const result = await API.solver.compare(ids);
                CompareModal.renderResult(result, document.getElementById('cmp-result'));
            } catch (err) {
                Toast.error(err.message);
            }
        });
    },

    renderResult(result, mountEl) {
        mountEl.innerHTML = TimetableHelpers.buildCompareResultHtml(result);
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = CompareModal;
}
