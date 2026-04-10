/**
 * Teachers View — CRUD + Availability matrix.
 */
const TeachersView = {
    async render(container) {
        const table = new DataTable({
            columns: [
                { key: 'color', label: '', render: (v) => `<span class="color-dot" style="background:${v}"></span>` },
                { key: 'name', label: 'Ονοματεπώνυμο' },
                { key: 'short_name', label: 'Συντομογραφία' },
                { key: 'email', label: 'Email' },
                { key: 'max_periods_per_day', label: 'Max/Ημέρα', render: v => v || '—' },
                { key: 'max_periods_per_week', label: 'Max/Εβδ', render: v => v || '—' },
            ],
            apiService: API.teachers,
            entityName: 'Καθηγητές',
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Ονοματεπώνυμο *</label>
                        <input class="form-input" id="f-name" value="${item?.name || ''}" placeholder="π.χ. Γιάννης Νικολάου" required>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Συντομογραφία *</label>
                        <input class="form-input" id="f-short_name" value="${item?.short_name || ''}" placeholder="π.χ. ΓΝ" required maxlength="20">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Email</label>
                        <input class="form-input" id="f-email" type="email" value="${item?.email || ''}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Τηλέφωνο</label>
                        <input class="form-input" id="f-phone" value="${item?.phone || ''}">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Max Ώρες / Ημέρα</label>
                        <input class="form-input" id="f-max_day" type="number" min="1" max="12" value="${item?.max_periods_per_day || ''}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Max Ώρες / Εβδομάδα</label>
                        <input class="form-input" id="f-max_week" type="number" min="1" max="60" value="${item?.max_periods_per_week || ''}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Min Ώρες / Ημέρα</label>
                        <input class="form-input" id="f-min_day" type="number" min="0" max="12" value="${item?.min_periods_per_day || 0}">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Χρώμα</label>
                    <div class="color-input-wrapper">
                        <input type="color" id="f-color" value="${item?.color || '#3B82F6'}">
                        <input class="form-input" id="f-color-text" value="${item?.color || '#3B82F6'}" style="width:120px">
                    </div>
                </div>
            `,
            formParser: () => ({
                name: document.getElementById('f-name').value.trim(),
                short_name: document.getElementById('f-short_name').value.trim(),
                email: document.getElementById('f-email').value.trim() || null,
                phone: document.getElementById('f-phone').value.trim() || null,
                max_periods_per_day: parseInt(document.getElementById('f-max_day').value) || null,
                max_periods_per_week: parseInt(document.getElementById('f-max_week').value) || null,
                min_periods_per_day: parseInt(document.getElementById('f-min_day').value) || 0,
                color: document.getElementById('f-color').value,
            }),
        });

        container.innerHTML = '<div id="teachers-table"></div>';
        await table.render(document.getElementById('teachers-table'));
    },
};
