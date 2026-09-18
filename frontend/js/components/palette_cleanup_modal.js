/**
 * PaletteCleanupModal — «🧹 Καθάρισμα Παλέτας»: ο έλεγχος «🔍 Τι επηρεάζει;»
 * για ΟΛΑ τα μαθήματα που έχουν ώρες στην Παλέτα, με μία ασφαλή πρόταση ανά
 * μάθημα:
 *
 *   ✂️ trim   — κράτα μόνο τις τοποθετημένες (σβήνει ΜΟΝΟ ώρες Παλέτας) — τσεκαρισμένο
 *   🗑️ delete — διαγραφή μαθήματος χωρίς ΚΑΜΙΑ τοποθετημένη ώρα — ΜΗ τσεκαρισμένο
 *   ✋ keep   — οι ώρες χρειάζονται σε άλλο πρόγραμμα — χωρίς επιλογή
 *
 * Ο server ξαναελέγχει κάθε μάθημα στην εφαρμογή (ποτέ τοποθετημένη ώρα).
 * Dual-mode: pure builders (unit tests) + Modal/API wiring.
 */
const PaletteCleanupModal = {
    esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    /** Κείμενο πρότασης για ένα μάθημα. */
    suggestionText(item) {
        if (item.suggestion === 'trim') {
            return `✂️ Κράτα ${item.trim.trim_to} ώρες/εβδ. — σβήνει ${item.trim.would_remove} ώρα(ες) Παλέτας`;
        }
        if (item.suggestion === 'delete') {
            return '🗑️ Διαγραφή μαθήματος — καμία τοποθετημένη ώρα σε κανένα πρόγραμμα';
        }
        return `✋ Κράτα — ${item.max_placed} ώρες είναι τοποθετημένες σε άλλο πρόγραμμα`;
    },

    rowHtml(item) {
        const esc = PaletteCleanupModal.esc;
        const actionable = item.suggestion !== 'keep';
        const checked = item.suggestion === 'trim' ? ' checked' : '';
        const box = actionable
            ? `<input type="checkbox" class="pc-pick" data-kind="${item.suggestion}"
                      data-id="${item.lesson_id}"${checked}>`
            : '';
        const warn = item.class_students ? '' : ' <span title="Το τμήμα δεν έχει μαθητές">⚠️</span>';
        return `
            <tr class="pc-row pc-${item.suggestion}">
                <td>${box}</td>
                <td><b>${esc(item.subject_name)}</b><br>
                    <small>${esc(item.class_name)} (${item.class_students} μαθ.)${warn} · ${esc(item.teacher_name)}</small></td>
                <td style="text-align:center">${item.placed_total}</td>
                <td style="text-align:center">${item.unplaced_total}</td>
                <td>${esc(PaletteCleanupModal.suggestionText(item))}</td>
            </tr>`;
    },

    buildHtml(review) {
        const items = (review && review.items) || [];
        if (!items.length) {
            return '<p>✅ Η Παλέτα είναι καθαρή — κανένα μάθημα δεν έχει ώρες που περιμένουν.</p>';
        }
        const t = review.totals || {};
        return `
            <div class="palette-cleanup">
                <p>${t.lessons} μαθήματα έχουν <b>${t.palette_hours}</b> ώρες στην Παλέτα.
                   Οι ώρες της Παλέτας δεν τυπώνονται και δεν μετράνε στη μισθοδοσία — απλώς περιμένουν.</p>
                <div style="max-height:380px; overflow:auto;">
                    <table class="data-table">
                        <thead><tr><th></th><th>Μάθημα</th><th>Τοποθ.</th><th>Παλέτα</th><th>Πρόταση</th></tr></thead>
                        <tbody>${items.map(PaletteCleanupModal.rowHtml).join('')}</tbody>
                    </table>
                </div>
                <p class="pc-summary" id="pc-summary"></p>
                <button class="btn btn-primary" id="pc-apply">🧹 Εφαρμογή</button>
            </div>`;
    },

    /** Τι είναι τσεκαρισμένο → {trim_ids, delete_ids}. */
    selection(root) {
        const pick = (kind) => [...root.querySelectorAll(`.pc-pick[data-kind="${kind}"]`)]
            .filter(b => b.checked).map(b => Number(b.dataset.id));
        return { trim_ids: pick('trim'), delete_ids: pick('delete') };
    },

    summaryText(review, sel) {
        const byId = new Map(((review && review.items) || []).map(i => [i.lesson_id, i]));
        const hours = sel.trim_ids.reduce((sum, id) => sum + ((byId.get(id) || {}).trim || {}).would_remove || 0, 0);
        if (!sel.trim_ids.length && !sel.delete_ids.length) return 'Δεν έχει επιλεγεί τίποτα.';
        return `Θα αφαιρεθούν ${hours} ώρες από την Παλέτα (${sel.trim_ids.length} μαθήματα) και θα `
            + `διαγραφούν ${sel.delete_ids.length} μαθήματα χωρίς τοποθετημένες ώρες. `
            + 'Καμία τοποθετημένη ώρα δεν θα πειραχτεί.';
    },

    async open(onChanged, termId = null) {
        Modal.open('🧹 Καθάρισμα Παλέτας',
            '<div class="loading-spinner"><div class="spinner"></div><p>Έλεγχος…</p></div>',
            null, { hideFooter: true, wide: true });
        let review;
        try {
            review = await API.lessons.paletteReview(termId);
        } catch (err) {
            const body = document.getElementById('modal-body');
            if (body) body.innerHTML = `<p>⚠️ ${PaletteCleanupModal.esc(err.message)}</p>`;
            return;
        }
        const body = document.getElementById('modal-body');
        if (!body) return;
        body.innerHTML = PaletteCleanupModal.buildHtml(review);
        const summary = document.getElementById('pc-summary');
        const refresh = () => {
            if (summary) summary.textContent = PaletteCleanupModal.summaryText(review, PaletteCleanupModal.selection(body));
        };
        body.querySelectorAll('.pc-pick').forEach(b => b.addEventListener('change', refresh));
        refresh();
        document.getElementById('pc-apply')?.addEventListener('click', async () => {
            const sel = PaletteCleanupModal.selection(body);
            if (!sel.trim_ids.length && !sel.delete_ids.length) {
                Toast.error('Δεν έχει επιλεγεί τίποτα.');
                return;
            }
            try {
                const res = await API.lessons.paletteCleanup(sel);
                Toast.success(res.message || 'Έγινε');
                if (res.skipped && res.skipped.length) {
                    Toast.info(`${res.skipped.length} μαθήματα παραλείφθηκαν (άλλαξαν στο μεταξύ).`);
                }
                Modal.close();
                if (typeof onChanged === 'function') onChanged();
            } catch (err) {
                Toast.error('Δεν έγινε: ' + err.message);
            }
        });
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = PaletteCleanupModal;
}
