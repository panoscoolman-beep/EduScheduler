/**
 * Periods View — Setup daily time slots / bell schedule.
 */
const PeriodsView = {
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
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Όνομα *</label>
                        <input class="form-input" id="f-name" value="${item?.name || ''}" placeholder="π.χ. 1η Ώρα">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Συντομογραφία *</label>
                        <input class="form-input" id="f-short_name" value="${item?.short_name || ''}" placeholder="π.χ. 1" maxlength="10">
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
                Toast.error(err.message);
            }
        });

        await table.render(document.getElementById('periods-table'));
    },
};
