/**
 * Classes View — CRUD for school classes/sections.
 */
const ClassesView = {
    async render(container) {
        const classrooms = await API.classrooms.list();

        const table = new DataTable({
            columns: [
                { key: 'name', label: 'Τάξη' },
                { key: 'short_name', label: 'Συντομ.' },
                { key: 'grade_level', label: 'Βαθμίδα', render: v => v ? `${v}` : '—' },
                { key: 'student_count', label: 'Μαθητές' },
            ],
            apiService: API.classes,
            entityName: 'Τάξεις',
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Όνομα Τάξης *</label>
                        <input class="form-input" id="f-name" value="${item?.name || ''}" placeholder="π.χ. Α1 Γυμνασίου">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Συντομογραφία *</label>
                        <input class="form-input" id="f-short_name" value="${item?.short_name || ''}" placeholder="π.χ. Α1" maxlength="20">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Βαθμίδα</label>
                        <input class="form-input" id="f-grade" type="number" min="1" max="6" value="${item?.grade_level || ''}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Αριθμός Μαθητών</label>
                        <input class="form-input" id="f-students" type="number" min="0" value="${item?.student_count || 0}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Βασική Αίθουσα</label>
                        <select class="form-select" id="f-homeroom">
                            <option value="">— Καμία —</option>
                            ${classrooms.map(r => `<option value="${r.id}" ${item?.home_room_id === r.id ? 'selected' : ''}>${r.name}</option>`).join('')}
                        </select>
                    </div>
                </div>
            `,
            formParser: () => ({
                name: document.getElementById('f-name').value.trim(),
                short_name: document.getElementById('f-short_name').value.trim(),
                grade_level: parseInt(document.getElementById('f-grade').value) || null,
                student_count: parseInt(document.getElementById('f-students').value) || 0,
                home_room_id: parseInt(document.getElementById('f-homeroom').value) || null,
            }),
        });

        container.innerHTML = '<div id="classes-table"></div>';
        await table.render(document.getElementById('classes-table'));
    },
};
