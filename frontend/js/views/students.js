/**
 * Students View — CRUD for tutoring center students.
 */
const StudentsView = {
    async render(container) {
        const table = new DataTable({
            columns: [
                { key: 'last_name', label: 'Επώνυμο' },
                { key: 'first_name', label: 'Όνομα' },
                { key: 'email', label: 'Email', render: v => v ? `${v}` : '—' },
                { key: 'phone', label: 'Τηλέφωνο', render: v => v ? `${v}` : '—' },
                { key: 'max_days_per_week', label: 'Max Ημέρες/Εβδ', render: v => v || '—' },
            ],
            apiService: API.students,
            entityName: 'Μαθητές',
            customActions: [
                {
                    id: 'availability',
                    title: 'Πρόγραμμα / Κωλύματα',
                    icon: '📅',
                    handler: (item) => AvailabilityModal.open('students', item)
                }
            ],
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Επώνυμο *</label>
                        <input class="form-input" id="f-last_name" value="${item?.last_name || ''}" placeholder="π.χ. Παπαδόπουλος">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Όνομα *</label>
                        <input class="form-input" id="f-first_name" value="${item?.first_name || ''}" placeholder="π.χ. Νίκος">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Email</label>
                        <input class="form-input" id="f-email" type="email" value="${item?.email || ''}" placeholder="π.χ. nikos@example.com">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Τηλέφωνο</label>
                        <input class="form-input" id="f-phone" type="tel" value="${item?.phone || ''}" placeholder="π.χ. 6900000000">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Max Ημέρες / Εβδομάδα</label>
                        <input class="form-input" id="f-max_days" type="number" min="1" max="7" value="${item?.max_days_per_week || ''}">
                    </div>
                </div>
            `,
            formParser: () => ({
                last_name: document.getElementById('f-last_name').value.trim(),
                first_name: document.getElementById('f-first_name').value.trim(),
                email: document.getElementById('f-email').value.trim() || null,
                phone: document.getElementById('f-phone').value.trim() || null,
                max_days_per_week: parseInt(document.getElementById('f-max_days').value) || null,
            }),
        });

        container.innerHTML = `
            <div style="display:flex; justify-content:flex-end; margin-bottom:0.5rem">
                <button class="btn btn-secondary" id="crm-import-btn"
                        title="Τράβα τους μαθητές από το Korifi CRM — τέλος η διπλή καταχώρηση">
                    ⬇️ Εισαγωγή από CRM
                </button>
            </div>
            <div id="students-table"></div>`;
        await table.render(document.getElementById('students-table'));
        document.getElementById('crm-import-btn').addEventListener('click', () =>
            this._openCrmImport(container));
    },

    async _openCrmImport(container) {
        Modal.open('⬇️ Εισαγωγή μαθητών από CRM',
            '<div id="crm-import-body"><div class="loading-spinner"><div class="spinner"></div><p>Σύνδεση με CRM…</p></div></div>',
            null, { hideFooter: true, wide: true });
        let preview;
        try {
            preview = await API.students.crmPreview();
        } catch (err) {
            document.getElementById('crm-import-body').innerHTML =
                `<p>⚠️ Σφάλμα: ${TimetableHelpers.esc(err.message)}</p>`;
            return;
        }
        const body = document.getElementById('crm-import-body');
        if (!body) return;  // ο χρήστης έκλεισε το modal
        if (!preview.available) {
            body.innerHTML = `<p>⚠️ ${TimetableHelpers.esc(preview.fatal_error || 'Το CRM δεν είναι διαθέσιμο.')}</p>`;
            return;
        }
        const newRows = preview.rows.filter(r => r.status === 'new');
        if (!newRows.length) {
            body.innerHTML = `<p>✅ Όλοι οι μαθητές του CRM (${preview.exists_count}) υπάρχουν ήδη στο EduScheduler — τίποτα να εισαχθεί.</p>`;
            return;
        }
        body.innerHTML = `
            <p><b>${newRows.length}</b> νέοι μαθητές θα εισαχθούν · <b>${preview.exists_count}</b> υπάρχουν ήδη (θα παραλειφθούν).</p>
            <div style="max-height:320px; overflow:auto; border:1px solid var(--border-color,#ccc); border-radius:6px; padding:0.5rem; margin:0.5rem 0">
                <table class="data-table"><thead><tr><th>Επώνυμο</th><th>Όνομα</th><th>Email/Τηλ.</th></tr></thead>
                <tbody>${newRows.map(r => `
                    <tr><td>${TimetableHelpers.esc(r.last_name)}</td>
                        <td>${TimetableHelpers.esc(r.first_name)}</td>
                        <td>${TimetableHelpers.esc(r.email || r.phone || '—')}</td></tr>`).join('')}
                </tbody></table>
            </div>
            <button class="btn btn-primary" id="crm-import-confirm">✅ Εισαγωγή ${newRows.length} μαθητών</button>`;
        document.getElementById('crm-import-confirm').addEventListener('click', async () => {
            try {
                const res = await API.students.crmImport(newRows.map(r => ({
                    first_name: r.first_name, last_name: r.last_name,
                    email: r.email, phone: r.phone,
                })));
                Toast.success(`✅ Εισήχθησαν ${res.created} μαθητές (${res.skipped} παραλείφθηκαν)`);
                Modal.close();
                await this.render(container);
            } catch (err) {
                Toast.error(`Η εισαγωγή απέτυχε: ${err.message}`);
            }
        });
    },
};
