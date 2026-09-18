/**
 * LessonImpactModal — «Τι επηρεάζει αυτή η ώρα;» για τις κάρτες της Παλέτας.
 *
 * Πριν σβήσει ο χρήστης ώρες βλέπει ΑΚΡΙΒΩΣ πού χρησιμοποιείται το μάθημα:
 * σε ποια προγράμματα του σεναρίου, πόσες ώρες είναι ήδη τοποθετημένες, πόσες
 * περιμένουν στην Παλέτα και πόσοι μαθητές έχει το τμήμα. Μετά προσφέρονται
 * δύο ενέργειες:
 *
 *   ✂️ «Κράτα μόνο τις τοποθετημένες» — μειώνει τις ώρες/εβδομάδα· σβήνει
 *      ΜΟΝΟ ώρες της Παλέτας, ποτέ τοποθετημένη (και αναιρείται ανεβάζοντας
 *      πάλι τις ώρες στην καρτέλα Μαθήματα).
 *   🗑️ «Διαγραφή μαθήματος» — σβήνει και τις τοποθετημένες ώρες σε όλα τα
 *      προγράμματα, γι' αυτό ξεκλειδώνει μόνο με ρητό τσεκάρισμα.
 *
 * Dual-mode όπως τα υπόλοιπα components: pure builders (unit tests) + wiring.
 */
const LessonImpactModal = {
    esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    title(data) {
        const l = (data && data.lesson) || {};
        const who = [l.class_name, l.teacher_name].filter(Boolean).join(' • ');
        return `🔍 ${l.subject_name || 'Μάθημα'}${who ? ' — ' + who : ''}`;
    },

    /** Οι γραμμές «τι επηρεάζουν οι ώρες της Παλέτας» (σταθερή εξήγηση). */
    effectLines(data) {
        const t = (data && data.totals) || {};
        const term = ((data && data.lesson) || {}).term_name || 'το σενάριο';
        return [
            `⏳ ${t.unplaced || 0} ώρες περιμένουν στην Παλέτα σε ${t.solutions || 0} πρόγραμμα(τα) του «${term}».`,
            '🖨️ Οι ώρες της Παλέτας ΔΕΝ εμφανίζονται στο τυπωμένο πρόγραμμα, στο Excel ή στο ημερολόγιο.',
            '💶 ΔΕΝ μετράνε στις ώρες και στη μισθοδοσία του CRM — εκεί μετράνε μόνο οι τοποθετημένες.',
            '🧩 Μετράνε μόνο ως «λείπουν ώρες»: τις ψάχνει ο solver σε επόμενη δημιουργία προγράμματος.',
            '🗂️ Αφορούν μόνο αυτό το σενάριο — τα άλλα σενάρια δεν επηρεάζονται.',
        ];
    },

    /** Προειδοποιήσεις που αξίζει να δει ο χρήστης πριν σβήσει. */
    warnings(data) {
        const out = [];
        const l = (data && data.lesson) || {};
        const t = (data && data.totals) || {};
        if ((t.placed || 0) > 0) {
            out.push(`✅ ${t.placed} ώρες αυτού του μαθήματος είναι ΤΟΠΟΘΕΤΗΜΕΝΕΣ και χρησιμοποιούνται.`);
        }
        if (!l.class_students) {
            out.push('⚠️ Το τμήμα δεν έχει μαθητές — ίσως το μάθημα να μη χρειάζεται καθόλου.');
        }
        return out;
    },

    solutionsTableHtml(data) {
        const esc = LessonImpactModal.esc;
        const rows = (data && data.solutions) || [];
        if (!rows.length) {
            return '<p class="text-muted">Δεν υπάρχει αποθηκευμένο πρόγραμμα σε αυτό το σενάριο.</p>';
        }
        const body = rows.map(r => `
            <tr>
                <td>${esc(r.solution_name)}</td>
                <td style="text-align:center">${r.placed}</td>
                <td style="text-align:center">${r.unplaced}</td>
                <td style="text-align:center">${r.missing || 0}</td>
            </tr>`).join('');
        return `
            <table class="data-table">
                <thead><tr>
                    <th>Πρόγραμμα</th><th>Τοποθετημένες</th><th>Στην Παλέτα</th><th>Λείπουν</th>
                </tr></thead>
                <tbody>${body}</tbody>
            </table>`;
    },

    /**
     * Ποια προγράμματα «κρατούν» τις ώρες: αυτά με τις περισσότερες
     * τοποθετημένες. Είναι ο λόγος που μπλοκάρεται το καθάρισμα όταν η
     * Παλέτα του τρέχοντος προγράμματος έχει ώρες — συχνά φταίει ένα ΠΑΛΙΟ
     * πρόγραμμα του ίδιου σεναρίου.
     */
    blockingSolutions(data) {
        const max = ((data && data.totals) || {}).max_placed || 0;
        return ((data && data.solutions) || [])
            .filter(r => max > 0 && r.placed === max)
            .map(r => r.solution_name);
    },

    /** Κείμενα/κατάσταση των δύο κουμπιών — pure, ώστε να ελέγχονται. */
    actionState(data) {
        const trim = (data && data.trim) || {};
        const del = (data && data.delete) || {};
        const l = (data && data.lesson) || {};
        const state = {
            trimEnabled: Boolean(trim.can_trim),
            trimLabel: trim.can_trim
                ? (trim.surplus
                    ? `✂️ Αφαίρεση ${trim.would_remove} περιττών ωρών Παλέτας`
                    : `✂️ Κράτα μόνο τις τοποθετημένες (${trim.trim_to} ώρες/εβδ.)`)
                : '✂️ Καθάρισμα ωρών',
            trimHint: '',
            deleteLabel: '🗑️ Διαγραφή μαθήματος',
            confirmLabel: '',
        };
        if (trim.can_trim && trim.surplus) {
            state.trimHint = `Υπάρχουν ${trim.would_remove} ώρες στην Παλέτα ΠΑΝΩ από τις `
                + `${l.periods_per_week} ώρες/εβδ. του μαθήματος — είναι περιττές. Θα αφαιρεθούν· `
                + 'οι ώρες/εβδ. μένουν ίδιες και καμία τοποθετημένη ώρα δεν θα πειραχτεί.';
        } else if (trim.can_trim) {
            state.trimHint = `Θα αφαιρεθούν ${trim.would_remove} ώρες από την Παλέτα `
                + `(από ${l.periods_per_week} σε ${trim.trim_to} ώρες/εβδομάδα). `
                + 'Καμία τοποθετημένη ώρα δεν θα πειραχτεί.';
        } else if (trim.blocked_reason === 'no_placed_hours') {
            state.trimHint = 'Καμία ώρα δεν είναι τοποθετημένη, οπότε δεν υπάρχει τίποτα να κρατηθεί. '
                + 'Αν δεν το χρειάζεσαι, διάγραψε ολόκληρο το μάθημα.';
        } else {
            const totals = (data && data.totals) || {};
            const holders = LessonImpactModal.blockingSolutions(data);
            state.trimHint = (totals.unplaced || 0) > 0 && holders.length
                ? `Οι ${totals.unplaced} ώρες της Παλέτας δεν κόβονται: στο «${holders.join('», «')}» `
                  + `είναι τοποθετημένες και οι ${l.periods_per_week}. Σβήσε τις πρώτα από εκείνο το `
                  + 'πρόγραμμα, ή διάγραψε ολόκληρο το μάθημα αν δεν το χρειάζεσαι πουθενά.'
                : 'Όλες οι ώρες είναι τοποθετημένες — δεν υπάρχει τίποτα στην Παλέτα.';
        }
        if (del.requires_force) {
            state.confirmLabel = `Ναι, κατάλαβα ότι θα σβηστούν και ${del.placed_total} τοποθετημένες ώρες `
                + `σε ${del.solutions_with_placed} πρόγραμμα(τα).`;
        }
        return state;
    },

    buildHtml(data) {
        const esc = LessonImpactModal.esc;
        const l = (data && data.lesson) || {};
        const st = LessonImpactModal.actionState(data);
        const li = (arr) => arr.map(x => `<li>${esc(x)}</li>`).join('');
        const confirm = st.confirmLabel
            ? `<label class="li-confirm"><input type="checkbox" id="li-confirm"> ${esc(st.confirmLabel)}</label>`
            : '';
        return `
            <div class="lesson-impact">
                <p class="li-head">
                    <b>${esc(l.subject_name || '')}</b> · ${esc(l.class_name || '—')}
                    (${l.class_students || 0} μαθητές) · ${esc(l.teacher_name || '—')}
                    · <b>${l.periods_per_week || 0}</b> ώρες/εβδομάδα
                </p>
                ${LessonImpactModal.solutionsTableHtml(data)}
                <ul class="li-effects">${li(LessonImpactModal.effectLines(data))}</ul>
                ${LessonImpactModal.warnings(data).length
                    ? `<ul class="li-warnings">${li(LessonImpactModal.warnings(data))}</ul>` : ''}
                <div class="li-actions">
                    <button class="btn btn-secondary" id="li-trim" ${st.trimEnabled ? '' : 'disabled'}>
                        ${esc(st.trimLabel)}
                    </button>
                    <p class="li-hint">${esc(st.trimHint)}</p>
                    ${confirm}
                    <button class="btn btn-danger" id="li-delete">${esc(st.deleteLabel)}</button>
                </div>
            </div>`;
    },

    /**
     * Άνοιγμα για ένα μάθημα. `onChanged()` καλείται μετά από επιτυχή ενέργεια
     * ώστε η προβολή να ξαναφορτώσει πρόγραμμα + Παλέτα.
     */
    async open(lessonId, onChanged) {
        Modal.open('🔍 Έλεγχος μαθήματος',
            '<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση…</p></div>',
            null, { hideFooter: true, wide: true });
        let data;
        try {
            data = await API.lessons.impact(lessonId);
        } catch (err) {
            const body = document.getElementById('modal-body');
            if (body) body.innerHTML = `<p>⚠️ ${LessonImpactModal.esc(err.message)}</p>`;
            return;
        }
        const body = document.getElementById('modal-body');
        if (!body) return;                       // ο χρήστης έκλεισε το modal
        const titleEl = document.getElementById('modal-title');
        if (titleEl) titleEl.textContent = LessonImpactModal.title(data);
        body.innerHTML = LessonImpactModal.buildHtml(data);

        const finish = (message) => {
            Toast.success(message);
            Modal.close();
            if (typeof onChanged === 'function') onChanged();
        };

        document.getElementById('li-trim')?.addEventListener('click', async () => {
            try {
                const res = await API.lessons.trimUnplaced(lessonId);
                finish(res.message || 'Οι ώρες καθαρίστηκαν');
            } catch (err) {
                Toast.error('Δεν έγινε: ' + err.message);
            }
        });

        document.getElementById('li-delete')?.addEventListener('click', async () => {
            const needsConfirm = Boolean(data.delete && data.delete.requires_force);
            const ticked = document.getElementById('li-confirm')?.checked;
            if (needsConfirm && !ticked) {
                Toast.error('Τσέκαρε πρώτα ότι κατάλαβες τι θα σβηστεί.');
                return;
            }
            try {
                await API.lessons.delete(lessonId, needsConfirm);
                finish('Το μάθημα διαγράφηκε');
            } catch (err) {
                Toast.error('Δεν έγινε: ' + err.message);
            }
        });
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = LessonImpactModal;
}
