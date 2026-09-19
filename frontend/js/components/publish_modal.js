/**
 * 📢 Δημοσίευση προγράμματος — προεπισκόπηση, επιλογή email, αποστολή, αποτελέσματα.
 *
 * Pure builders (έλεγχος με node --test) + open(solutionId) για τον browser.
 * Τα email τα στέλνει το CRM (Gmail του φροντιστηρίου) μέσω του backend· εδώ
 * διαλέγεις ποιοι τα παίρνουν. Κανένα email δεν φεύγει χωρίς ρητό «Δημοσίευση».
 *
 * Browser: global PublishModal. Node: module.exports.
 */
const PublishModal = {
    TEST_TO_KEY: 'eds.publish.testTo',
    POLL_MS: 2000,
    POLL_MAX: 90,

    esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    /** Προεπιλογή: όσοι έχουν αλλαγές ΚΑΙ email. */
    defaultSelection(teachers) {
        return (teachers || []).filter(t => t.changed && t.email).map(t => t.teacher_id);
    },

    /** Γρήγορες επιλογές: 'changed' | 'all' | 'none'. */
    selectionFor(teachers, mode) {
        const withEmail = (teachers || []).filter(t => t.email);
        if (mode === 'all') return withEmail.map(t => t.teacher_id);
        if (mode === 'none') return [];
        return withEmail.filter(t => t.changed).map(t => t.teacher_id);
    },

    changeBadge(t, first) {
        if (first) return '<span class="pub-badge pub-new">νέο πρόγραμμα</span>';
        if (!t.changed) return '<span class="pub-badge">χωρίς αλλαγές</span>';
        const n = t.changes ? t.changes.moved.length + t.changes.added.length + t.changes.removed.length : 0;
        return `<span class="pub-badge pub-changed">${n} αλλαγ${n === 1 ? 'ή' : 'ές'}</span>`;
    },

    buildHtml(preview, selected, testTo) {
        const esc = PublishModal.esc;
        const teachers = (preview && preview.teachers) || [];
        const prev = preview.previous;
        const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);
        const resend = PublishModal.isResend(preview);
        const intro = resend
            ? `<p>✅ Από την τελευταία δημοσίευση («${esc(prev.solution_name)}», ${esc(when(prev.published_at))})
                  δεν άλλαξε τίποτα — δεν χρειάζεται νέα. Μπορείς όμως να στείλεις email με αυτή
                  (π.χ. σε όσους δεν το πήραν):</p>`
            : preview.first
            ? '<p>Πρώτη δημοσίευση σε αυτό το σενάριο: όλοι οι καθηγητές παίρνουν το πρόγραμμά τους.</p>'
            : `<p>Σε σχέση με την τελευταία δημοσίευση («${esc(prev.solution_name)}», ${esc(when(prev.published_at))})
                  αλλάζει κάτι για <b>${preview.affected}</b> από ${teachers.length} καθηγητές.</p>`;
        const warn = preview.unplaced
            ? `<p class="text-warning">⚠️ ${preview.unplaced} ώρες είναι ακόμα στην Παλέτα και δεν περιλαμβάνονται.</p>` : '';
        const chosen = new Set(selected || []);
        const rows = teachers.map((t, i) => `
            <div class="pub-row">
                <label class="pub-pick" title="${t.email ? esc(t.email) : 'Δεν υπάρχει email στην καρτέλα του'}">
                    <input type="checkbox" class="pub-mail" data-id="${t.teacher_id}"
                           ${t.email ? '' : 'disabled'} ${chosen.has(t.teacher_id) ? 'checked' : ''}>
                    ✉️
                </label>
                <details class="pub-details">
                    <summary><b>${esc(t.teacher)}</b> ${PublishModal.changeBadge(t, preview.first)}
                        <small class="text-muted">${t.hours} ώρες${t.email ? '' : ' · χωρίς email'}</small></summary>
                    <pre class="pub-message">${esc(t.message)}</pre>
                    <button class="btn btn-secondary btn-sm pub-copy" data-idx="${i}">📋 Αντιγραφή</button>
                </details>
            </div>`).join('');
        const options = teachers.filter(t => t.email).map(t =>
            `<option value="${t.teacher_id}">${esc(t.teacher)}</option>`).join('');
        return `${intro}${warn}
            <div class="pub-toolbar">
                <b>✉️ Email σε:</b>
                <button class="btn btn-secondary btn-sm pub-select" data-mode="changed">όσους έχουν αλλαγές</button>
                <button class="btn btn-secondary btn-sm pub-select" data-mode="all">όλους</button>
                <button class="btn btn-secondary btn-sm pub-select" data-mode="none">κανέναν</button>
                <span id="pub-count" class="text-muted"></span>
            </div>
            <div class="pub-list">${rows}</div>
            <details class="pub-test">
                <summary>🧪 Στείλε πρώτα δοκιμαστικό email σε μένα</summary>
                <div class="pub-test-row">
                    <select class="form-select" id="pub-test-teacher">${options}</select>
                    <input class="form-input" id="pub-test-to" type="email" placeholder="το email σου"
                           value="${esc(testTo || '')}">
                    <button class="btn btn-secondary btn-sm" id="pub-test-send">Αποστολή δοκιμής</button>
                </div>
                <small class="text-muted">Φτάνει ακριβώς όπως θα το δει ο καθηγητής (με .ics και PDF). Δεν δημοσιεύει τίποτα.</small>
            </details>
            ${resend ? '' : `<div class="form-group" style="margin-top:0.75rem">
                <label class="form-label">Σημείωση (προαιρετική — μπαίνει και στο email)</label>
                <input class="form-input" id="pub-note" maxlength="500" placeholder="π.χ. ισχύει από Δευτέρα 21/9">
            </div>
            <label><input type="checkbox" id="pub-telegram" checked>
                📨 Σύνοψη στο Telegram μου (με κουμπί ανά καθηγητή για προώθηση)</label>`}`;
    },

    /** Τίποτα νέο από την τελευταία δημοσίευση → μόνο αποστολή email για εκείνη. */
    isResend(preview) {
        return Boolean(preview && !preview.first && !preview.affected && preview.previous);
    },

    countText(selected) {
        const n = (selected || []).length;
        return n ? `${n} θα πάρ${n === 1 ? 'ει' : 'ουν'} email` : 'κανένα email';
    },

    /** Αποτελέσματα αποστολής (από GET /publications/{id}). */
    buildResultsHtml(detail) {
        const esc = PublishModal.esc;
        const mails = (detail.messages || []).filter(m => m.email);
        const e = detail.emails || {};
        const icon = { sent: '✅', failed: '❌', pending: '⏳', no_email: '—' };
        const rows = mails.map(m => `<tr>
                <td>${icon[m.email.status] || '•'}</td><td>${esc(m.teacher)}</td>
                <td><small>${esc(m.email.to || 'χωρίς email')}</small></td>
                <td><small class="text-danger">${esc(m.email.error || '')}</small></td></tr>`).join('');
        const done = detail.email_state !== 'sending';
        return `<p>${done ? '✅ Ολοκληρώθηκε' : '⏳ Αποστολή σε εξέλιξη…'} —
                    στάλθηκαν <b>${e.sent || 0}</b>/${e.requested || 0}${e.failed ? `, <b class="text-danger">${e.failed} απέτυχαν</b>` : ''}.</p>
                <table class="data-table"><tbody>${rows}</tbody></table>
                ${detail.notify_telegram && !detail.telegram_sent_at ? '<p class="text-muted" style="font-size:0.85rem">Η σύνοψη έρχεται στο Telegram μέσα σε λίγα λεπτά.</p>' : ''}`;
    },

    // ── Browser ─────────────────────────────────────────────────────────────

    async open(solutionId) {
        Modal.open('📢 Δημοσίευση προγράμματος',
            '<div class="loading-spinner"><div class="spinner"></div></div>', null, { hideFooter: true, wide: true });
        let preview;
        try {
            preview = await API.solver.publishPreview(solutionId);
        } catch (err) {
            Modal.close();
            Toast.error(err.message);
            return;
        }
        const resend = PublishModal.isResend(preview);
        let selected = resend ? [] : PublishModal.defaultSelection(preview.teachers);
        Modal.open(resend ? '✉️ Email για την τελευταία δημοσίευση' : '📢 Δημοσίευση προγράμματος',
            PublishModal.buildHtml(preview, selected, PublishModal._loadTestTo()),
            resend ? () => PublishModal._resend(preview.previous.id, selected)
                   : () => PublishModal._publish(solutionId, selected),
            { wide: true, saveText: resend ? '✉️ Αποστολή email' : '📢 Δημοσίευση' });
        const body = document.getElementById('modal-body');
        const refresh = () => {
            body.querySelectorAll('.pub-mail').forEach(cb => { cb.checked = selected.includes(Number(cb.dataset.id)); });
            document.getElementById('pub-count').textContent = PublishModal.countText(selected);
        };
        body.querySelectorAll('.pub-mail').forEach(cb => cb.addEventListener('change', () => {
            const id = Number(cb.dataset.id);
            selected = cb.checked ? [...new Set([...selected, id])] : selected.filter(x => x !== id);
            refresh();
        }));
        body.querySelectorAll('.pub-select').forEach(btn => btn.addEventListener('click', () => {
            selected = PublishModal.selectionFor(preview.teachers, btn.dataset.mode);
            refresh();
        }));
        body.querySelectorAll('.pub-copy').forEach(btn => btn.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(preview.teachers[Number(btn.dataset.idx)].message);
                Toast.success('Αντιγράφηκε.');
            } catch (_) {
                Toast.error('Η αντιγραφή δεν επιτρέπεται εδώ — επίλεξε το κείμενο χειροκίνητα.');
            }
        }));
        document.getElementById('pub-test-send')?.addEventListener('click', () => PublishModal._sendTest(solutionId));
        refresh();
    },

    async _sendTest(solutionId) {
        const to = document.getElementById('pub-test-to').value.trim();
        const teacherId = Number(document.getElementById('pub-test-teacher').value);
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(to)) {
            Toast.error('Γράψε ένα σωστό email για τη δοκιμή.');
            return;
        }
        PublishModal._saveTestTo(to);
        const btn = document.getElementById('pub-test-send');
        btn.disabled = true;
        btn.textContent = '⏳ Αποστολή…';
        try {
            await API.solver.publishTestEmail(solutionId, { teacher_id: teacherId, to });
            Toast.success(`📧 Στάλθηκε δοκιμή στο ${to} — δες τα εισερχόμενα.`);
        } catch (err) {
            Toast.error(err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Αποστολή δοκιμής';
        }
    },

    async _publish(solutionId, selected) {
        const note = document.getElementById('pub-note')?.value || '';
        const notify = !!document.getElementById('pub-telegram')?.checked;
        let res;
        try {
            res = await API.solver.publish(solutionId, { note, notify_telegram: notify, email_teacher_ids: selected });
        } catch (err) {
            Toast.error(err.message);
            return;
        }
        if (!res.emails || !res.emails.requested) {
            Modal.close();
            Toast.success(notify ? '✅ Δημοσιεύτηκε — η σύνοψη έρχεται στο Telegram σε λίγα λεπτά.' : '✅ Δημοσιεύτηκε.');
            return;
        }
        await PublishModal._track(res);
    },

    async _resend(publicationId, selected) {
        if (!selected.length) {
            Toast.error('Διάλεξε τουλάχιστον έναν καθηγητή.');
            return;
        }
        let res;
        try {
            res = await API.solver.publicationEmails(publicationId, { teacher_ids: selected });
        } catch (err) {
            Toast.error(err.message);
            return;
        }
        await PublishModal._track(res);
    },

    /** Πρόοδος αποστολής: ανανέωση κάθε 2" μέχρι να τελειώσει. */
    async _track(res) {
        Modal.open('📧 Αποστολή email', PublishModal.buildResultsHtml(res), null, { hideFooter: true, wide: true });
        for (let i = 0; i < PublishModal.POLL_MAX; i++) {
            await new Promise(r => setTimeout(r, PublishModal.POLL_MS));
            let detail;
            try {
                detail = await API.solver.publication(res.id);
            } catch (_) {
                continue;
            }
            const body = document.getElementById('modal-body');
            if (!body) return;
            body.innerHTML = PublishModal.buildResultsHtml(detail);
            if (detail.email_state !== 'sending') return;
        }
    },

    _loadTestTo() {
        try { return localStorage.getItem(PublishModal.TEST_TO_KEY) || ''; } catch (_) { return ''; }
    },

    _saveTestTo(value) {
        try { localStorage.setItem(PublishModal.TEST_TO_KEY, value); } catch (_) { /* ιδιωτική περιήγηση */ }
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = PublishModal;
}
