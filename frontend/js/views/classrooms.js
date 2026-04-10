/**
 * Classrooms View — CRUD for physical rooms.
 */
const ClassroomsView = {
    ROOM_TYPES: { regular: 'Κανονική', lab: 'Εργαστήριο', gym: 'Γυμναστήριο', computer_lab: 'Εργ. Πληροφ.' },

    async render(container) {
        const self = this;
        const table = new DataTable({
            columns: [
                { key: 'name', label: 'Αίθουσα' },
                { key: 'short_name', label: 'Συντομ.' },
                { key: 'capacity', label: 'Χωρητικότητα' },
                { key: 'room_type', label: 'Τύπος', render: v => self.ROOM_TYPES[v] || v },
                { key: 'building', label: 'Κτίριο', render: v => v || '—' },
            ],
            apiService: API.classrooms,
            entityName: 'Αίθουσες',
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Όνομα Αίθουσας *</label>
                        <input class="form-input" id="f-name" value="${item?.name || ''}" placeholder="π.χ. Αίθουσα 1">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Συντομογραφία *</label>
                        <input class="form-input" id="f-short_name" value="${item?.short_name || ''}" placeholder="π.χ. Α1" maxlength="20">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Χωρητικότητα</label>
                        <input class="form-input" id="f-capacity" type="number" min="1" max="500" value="${item?.capacity || 30}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Τύπος</label>
                        <select class="form-select" id="f-type">
                            ${Object.entries(self.ROOM_TYPES).map(([k, v]) =>
                                `<option value="${k}" ${item?.room_type === k ? 'selected' : ''}>${v}</option>`
                            ).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Κτίριο</label>
                        <input class="form-input" id="f-building" value="${item?.building || ''}">
                    </div>
                </div>
            `,
            formParser: () => ({
                name: document.getElementById('f-name').value.trim(),
                short_name: document.getElementById('f-short_name').value.trim(),
                capacity: parseInt(document.getElementById('f-capacity').value) || 30,
                room_type: document.getElementById('f-type').value,
                building: document.getElementById('f-building').value.trim() || null,
            }),
        });

        container.innerHTML = '<div id="classrooms-table"></div>';
        await table.render(document.getElementById('classrooms-table'));
    },
};
