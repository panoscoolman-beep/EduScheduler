/**
 * Terms / Scenarios View — manage scheduling scenarios ("sessions").
 *
 * Each term scopes its own lessons, availability and generated programs.
 * Activating a term switches the whole app to that scenario; the others are
 * untouched. "Αντιγραφή" deep-copies a term's inputs into a new scenario.
 */
const TermsView = {
    _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    async render(container) {
        container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>`;
        try {
            const terms = await API.terms.list();
            container.innerHTML = `
                <div class="card mb-lg">
                    <div class="card-header">
                        <h2 class="card-title">🗂️ Σενάρια Ωραρίου</h2>
                        <button class="btn btn-primary" id="terms-new">➕ Νέο σενάριο (κενό)</button>
                    </div>
                    <p class="text-muted" style="margin:0 0 1rem">
                        Κάθε σενάριο έχει ΞΕΧΩΡΙΣΤΑ μαθήματα, διαθεσιμότητες και προγράμματα.
                        Πάτησε <strong>Ενεργοποίηση</strong> για να δουλέψεις σε άλλο σενάριο — τα υπόλοιπα δεν αλλάζουν.
                        Με <strong>Αντιγραφή</strong> φτιάχνεις νέο σενάριο με αντίγραφο των μαθημάτων/διαθεσιμοτήτων (π.χ. για χειμερινό ωράριο).
                    </p>
                    <div id="terms-list"></div>
                </div>`;
            this._renderList(terms, container);
            document.getElementById('terms-new').addEventListener('click', () => this._openCreate(container));
        } catch (err) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <p class="empty-state-text">Σφάλμα: ${this._esc(err.message)}</p>
                </div>`;
        }
    },

    _renderList(terms, container) {
        const host = document.getElementById('terms-list');
        host.innerHTML = `
            <table class="data-table">
                <thead><tr><th>Σενάριο</th><th>Σύντομο</th><th>Κατάσταση</th><th style="text-align:right">Ενέργειες</th></tr></thead>
                <tbody>
                    ${terms.map(t => `
                        <tr>
                            <td><strong>${this._esc(t.name)}</strong></td>
                            <td>${this._esc(t.short_name || '—')}</td>
                            <td>${t.is_active ? '<span class="constraint-badge soft">● Ενεργό</span>' : '<span class="text-muted">ανενεργό</span>'}</td>
                            <td style="text-align:right; white-space:nowrap">
                                ${t.is_active ? '' : `<button class="btn btn-sm btn-secondary" data-act="activate" data-id="${t.id}">Ενεργοποίηση</button>`}
                                <button class="btn btn-sm btn-secondary" data-act="clone" data-id="${t.id}" data-name="${this._esc(t.name)}">Αντιγραφή</button>
                                <button class="btn btn-sm btn-secondary" data-act="shift" data-id="${t.id}" data-name="${this._esc(t.name)}">Μετατόπιση ωρών</button>
                                <button class="btn btn-sm btn-danger" data-act="delete" data-id="${t.id}" data-name="${this._esc(t.name)}">Διαγραφή</button>
                            </td>
                        </tr>`).join('')}
                </tbody>
            </table>`;
        host.querySelectorAll('button[data-act]').forEach(btn =>
            btn.addEventListener('click', () => this._action(btn.dataset, container))
        );
    },

    async _action(ds, container) {
        const id = parseInt(ds.id);
        if (ds.act === 'activate') {
            try {
                await API.terms.activate(id);
                Toast.success('Άλλαξε το ενεργό σενάριο');
                if (App.refreshTermSelector) await App.refreshTermSelector();
                await this.render(container);
            } catch (err) { Toast.error(err.message); }
        } else if (ds.act === 'clone') {
            this._openClone(id, ds.name, container);
        } else if (ds.act === 'shift') {
            this._openShift(id, ds.name, container);
        } else if (ds.act === 'delete') {
            this._confirmDelete(id, ds.name, false, container);
        }
    },

    _openShift(id, name, container) {
        Modal.open('🕐 Μετατόπιση ωρών',
            `<p>Μετατόπιση ΟΛΩΝ των ωρών του σεναρίου <strong>${this._esc(name)}</strong> (διαθεσιμότητες + προγράμματα) κατά σταθερό αριθμό διδακτικών ωρών.</p>
             <div class="form-group">
                <label class="form-label">Μετατόπιση κατά (ώρες)</label>
                <input class="form-input" id="shift-offset" type="number" value="6" step="1">
                <small class="text-muted">Θετικό = αργότερα μέσα στη μέρα (π.χ. <strong>+6</strong>: πρωινές 1η–6η → απογευματινές 7η–12η). Αρνητικό = νωρίτερα.</small>
             </div>
             <label style="display:block"><input type="checkbox" id="shift-sols" checked> Μετατόπιση και των υπαρχόντων προγραμμάτων (ό,τι βγαίνει εκτός εύρους πάει στο parking lot)</label>`,
            async () => {
                const offset = parseInt(document.getElementById('shift-offset').value, 10);
                if (!offset) { Toast.error('Δώσε μη-μηδενική μετατόπιση.'); return; }
                try {
                    const r = await API.terms.shiftTimes(id, {
                        offset,
                        shift_solutions: document.getElementById('shift-sols').checked,
                    });
                    Toast.success(`Μετατοπίστηκαν: ${r.availability_moved} διαθεσιμότητες, ${r.slots_moved} ώρες προγράμματος` +
                        (r.availability_dropped || r.slots_unplaced ? ` (εκτός εύρους: ${r.availability_dropped}+${r.slots_unplaced})` : ''));
                    Modal.close();
                    await this.render(container);
                } catch (err) { Toast.error(err.message); }
            }, { saveText: '🕐 Μετατόπιση' });
    },

    _openCreate(container) {
        Modal.open('➕ Νέο σενάριο',
            `<div class="form-group">
                <label class="form-label">Όνομα *</label>
                <input class="form-input" id="term-name" placeholder="π.χ. Χειμερινό 2026-27">
             </div>
             <div class="form-group">
                <label class="form-label">Σύντομο</label>
                <input class="form-input" id="term-short" placeholder="π.χ. ΧΕΙΜ" maxlength="20">
             </div>
             <p class="text-muted">Δημιουργείται ΚΕΝΟ σενάριο (χωρίς μαθήματα). Για αντίγραφο υπάρχοντος, χρησιμοποίησε «Αντιγραφή».</p>`,
            async () => {
                const name = document.getElementById('term-name').value.trim();
                if (!name) { Toast.error('Δώσε όνομα.'); return; }
                try {
                    await API.terms.create({ name, short_name: document.getElementById('term-short').value.trim() || null });
                    Toast.success('Δημιουργήθηκε το σενάριο');
                    Modal.close();
                    if (App.refreshTermSelector) await App.refreshTermSelector();
                    await this.render(container);
                } catch (err) { Toast.error(err.message); }
            }, { saveText: 'Δημιουργία' });
    },

    _openClone(id, name, container) {
        Modal.open('📑 Αντιγραφή σεναρίου',
            `<p>Αντιγραφή των μαθημάτων & διαθεσιμοτήτων από <strong>${this._esc(name)}</strong> σε νέο σενάριο. Τα προγράμματα ΔΕΝ αντιγράφονται.</p>
             <div class="form-group">
                <label class="form-label">Όνομα νέου σεναρίου *</label>
                <input class="form-input" id="clone-name" value="${this._esc(name)} (αντίγραφο)">
             </div>
             <div class="form-group">
                <label class="form-label">Σύντομο</label>
                <input class="form-input" id="clone-short" maxlength="20">
             </div>
             <label style="display:block"><input type="checkbox" id="clone-activate" checked> Ενεργοποίηση του νέου σεναρίου</label>`,
            async () => {
                const newName = document.getElementById('clone-name').value.trim();
                if (!newName) { Toast.error('Δώσε όνομα.'); return; }
                try {
                    await API.terms.clone(id, {
                        name: newName,
                        short_name: document.getElementById('clone-short').value.trim() || null,
                        activate: document.getElementById('clone-activate').checked,
                    });
                    Toast.success('Το σενάριο αντιγράφηκε');
                    Modal.close();
                    if (App.refreshTermSelector) await App.refreshTermSelector();
                    await this.render(container);
                } catch (err) { Toast.error(err.message); }
            }, { saveText: '📑 Αντιγραφή' });
    },

    _confirmDelete(id, name, force, container) {
        Modal.open('Διαγραφή σεναρίου',
            `<p>Διαγραφή του σεναρίου <strong>${this._esc(name)}</strong>;</p>
             <p class="text-muted">Διαγράφονται και τα μαθήματα/διαθεσιμότητες/προγράμματά του.</p>`,
            async () => {
                try {
                    await API.terms.delete(id, force);
                    Toast.success('Το σενάριο διαγράφηκε');
                    Modal.close();
                    if (App.refreshTermSelector) await App.refreshTermSelector();
                    await this.render(container);
                } catch (err) {
                    if (err.status === 409 && err.detail && err.detail.requires_force) {
                        Modal.close();
                        Modal.open('⚠️ Επιβεβαίωση',
                            `<p style="color:var(--accent-rose,#F43F5E);font-weight:600">${this._esc(err.detail.message)}</p>`,
                            async () => {
                                try {
                                    await API.terms.delete(id, true);
                                    Toast.success('Το σενάριο διαγράφηκε');
                                    Modal.close();
                                    if (App.refreshTermSelector) await App.refreshTermSelector();
                                    await this.render(container);
                                } catch (e2) { Toast.error(e2.message); }
                            }, { saveText: 'Ναι, διαγραφή όλων', saveClass: 'btn-danger' });
                    } else {
                        Toast.error(err.message);
                    }
                }
            }, { saveText: 'Διαγραφή', saveClass: 'btn-danger' });
    },
};
