/**
 * Subjects View — CRUD for school subjects.
 */
const SubjectsView = {
    async render(container) {
        const table = new DataTable({
            columns: [
                { key: 'color', label: '', render: (v) => `<span class="color-dot" style="background:${v}"></span>` },
                { key: 'name', label: 'Μάθημα' },
                { key: 'short_name', label: 'Συντομ.' },
                { key: 'requires_special_room', label: 'Ειδική Αίθ.', render: v => v ? '✅' : '—' },
                { key: 'special_room_type', label: 'Τύπος', render: v => v || '—' },
            ],
            apiService: API.subjects,
            entityName: 'Μαθήματα',
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Όνομα Μαθήματος *</label>
                        <input class="form-input" id="f-name" value="${item?.name || ''}" placeholder="π.χ. Μαθηματικά">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Συντομογραφία *</label>
                        <input class="form-input" id="f-short_name" value="${item?.short_name || ''}" placeholder="π.χ. ΜΑΘ" maxlength="20">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Χρώμα</label>
                    <div class="color-input-wrapper">
                        <input type="color" id="f-color" value="${item?.color || '#8B5CF6'}">
                        <input class="form-input" id="f-color-text" value="${item?.color || '#8B5CF6'}" style="width:120px">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Απαιτεί ειδική αίθουσα</label>
                        <select class="form-select" id="f-special">
                            <option value="false" ${!item?.requires_special_room ? 'selected' : ''}>Όχι</option>
                            <option value="true" ${item?.requires_special_room ? 'selected' : ''}>Ναι</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Τύπος Αίθουσας</label>
                        <select class="form-select" id="f-room_type">
                            <option value="">—</option>
                            <option value="lab" ${item?.special_room_type === 'lab' ? 'selected' : ''}>Εργαστήριο</option>
                            <option value="gym" ${item?.special_room_type === 'gym' ? 'selected' : ''}>Γυμναστήριο</option>
                            <option value="computer_lab" ${item?.special_room_type === 'computer_lab' ? 'selected' : ''}>Εργ. Πληροφορικής</option>
                        </select>
                    </div>
                </div>
            `,
            formParser: () => ({
                name: document.getElementById('f-name').value.trim(),
                short_name: document.getElementById('f-short_name').value.trim(),
                color: document.getElementById('f-color').value,
                requires_special_room: document.getElementById('f-special').value === 'true',
                special_room_type: document.getElementById('f-room_type').value || null,
            }),
        });

        container.innerHTML = '<div id="subjects-table"></div>';
        await table.render(document.getElementById('subjects-table'));
    },
};
