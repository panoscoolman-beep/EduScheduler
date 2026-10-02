/**
 * Periods View — Setup daily time slots / bell schedule.
 */
const PeriodsView = {
    /**
     * Επιβεβαίωση «ώρα με μαθήματα → Διάλειμμα» (409 period_in_use) από τη λίστα
     * `programmes` του server: ποια προγράμματα επηρεάζονται. Τα αρχειοθετημένα
     * ΔΕΝ αλλάζουν (απλώς δεν φαίνονται όσο η ώρα είναι διάλειμμα)· οι ώρες των
     * ενεργών πάνε στην Παλέτα και επανέρχονται με «↩️ Αναίρεση». Χωρίς λίστα
     * (παλιός server) → null = τα γενικά κείμενα.
     */
    breakConfirm(detail) {
        const list = detail && Array.isArray(detail.programmes) ? detail.programmes : null;
        if (!list || !list.length) return null;
        const esc = DataTable.esc;
        const count = (p) => Number(p.slots ?? p.count) || 0;
        const items = list.map(p => `<li>«${esc(p.solution_name ?? p.name ?? '')}»`
            + (p.term_name ? ` <span class="text-muted">(σενάριο «${esc(p.term_name)}»)</span>` : '')
            + (p.archived ? ' · 📦 αρχειοθετημένο' : '')
            + `: <b>${count(p)}</b> ${count(p) === 1 ? 'ώρα' : 'ώρες'}</li>`).join('');
        const active = list.filter(p => !p.archived).reduce((sum, p) => sum + count(p), 0);
        const archivedOnly = list.every(p => p.archived);
        const archivedNote = list.some(p => p.archived)
            ? '<p class="text-muted mt-sm">Τα αρχειοθετημένα προγράμματα <b>δεν αλλάζουν</b>: όσο η ώρα είναι '
              + 'διάλειμμα οι ώρες τους απλώς δεν φαίνονται, και ξαναεμφανίζονται αν ξαναγίνει διδακτική.</p>'
            : '';
        if (archivedOnly) {
            return {
                title: '⚠️ Η ώρα γίνεται διάλειμμα',
                bodyHtml: `<p>Η ώρα έχει τοποθετημένα μαθήματα μόνο σε αρχειοθετημένα προγράμματα:</p>
                           <ul>${items}</ul>${archivedNote}`,
                saveText: 'Ναι, αποθήκευση',
                successText: 'Αποθηκεύτηκε — δεν μετακινήθηκε καμία ώρα· τα αρχειοθετημένα προγράμματα έμειναν όπως ήταν.',
            };
        }
        return {
            title: '⚠️ Η αλλαγή συγκρούεται με το πρόγραμμα',
            bodyHtml: `<p>Η ώρα έχει τοποθετημένα μαθήματα σε:</p><ul>${items}</ul>
                       <p style="font-weight:600">Οι ${active} ώρες των ενεργών προγραμμάτων θα πάνε στην Παλέτα·
                       αν ξανακάνεις την ώρα διδακτική, επανέρχονται με «↩️ Αναίρεση».</p>${archivedNote}`,
            saveText: 'Ναι, αποθήκευση',
            successText: `Αποθηκεύτηκε — οι ${active} ώρες των ενεργών προγραμμάτων πήγαν στην Παλέτα· `
                + 'αν ξανακάνεις την ώρα διδακτική, επανέρχονται με «↩️ Αναίρεση».',
        };
    },

    async render(container) {
        const table = new DataTable({
            columns: [
                { key: 'sort_order', label: '#' },
                { key: 'name', label: 'Περίοδος' },
                { key: 'short_name', label: 'Συντομ.' },
                { key: 'start_time', label: 'Αρχή' },
                { key: 'end_time', label: 'Τέλος' },
                { key: 'is_break', label: 'Διάλειμμα', render: v => v ? '☕ Ναι' : '—' },
            ],
            apiService: API.periods,
            entityName: 'Ώρες / Περίοδοι',
            forceUpdateConfirm: (detail) => PeriodsView.breakConfirm(detail),
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Όνομα *</label>
                        <input class="form-input" id="f-name" value="${DataTable.esc(item?.name || '')}" placeholder="π.χ. 1η Ώρα">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Συντομογραφία *</label>
                        <input class="form-input" id="f-short_name" value="${DataTable.esc(item?.short_name || '')}" placeholder="π.χ. 1" maxlength="10">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Ώρα Έναρξης *</label>
                        <input class="form-input" id="f-start" type="time" value="${item?.start_time || '08:00'}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Ώρα Λήξης *</label>
                        <input class="form-input" id="f-end" type="time" value="${item?.end_time || '08:45'}">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Σειρά</label>
                        <input class="form-input" id="f-order" type="number" min="0" value="${item?.sort_order ?? 0}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Διάλειμμα;</label>
                        <select class="form-select" id="f-break">
                            <option value="false" ${!item?.is_break ? 'selected' : ''}>Όχι — Ώρα διδασκαλίας</option>
                            <option value="true" ${item?.is_break ? 'selected' : ''}>Ναι — Διάλειμμα</option>
                        </select>
                    </div>
                </div>
            `,
            formParser: () => ({
                name: document.getElementById('f-name').value.trim(),
                short_name: document.getElementById('f-short_name').value.trim(),
                start_time: document.getElementById('f-start').value,
                end_time: document.getElementById('f-end').value,
                sort_order: parseInt(document.getElementById('f-order').value) || 0,
                is_break: document.getElementById('f-break').value === 'true',
            }),
        });

        container.innerHTML = `
            <div class="flex-between mb-lg">
                <div></div>
                <button class="btn btn-secondary" id="seed-periods">🕐 Φόρτωση Προεπιλεγμένου Ωραρίου</button>
            </div>
            <div id="periods-table"></div>
        `;

        document.getElementById('seed-periods').addEventListener('click', async () => {
            try {
                await API.periods.seedDefaults();
                Toast.success('Φορτώθηκε το προεπιλεγμένο ωράριο');
                await table.loadData();
            } catch (err) {
                Toast.error(DataTable.esc(err.message));
            }
        });

        await table.render(document.getElementById('periods-table'));
    },
};
