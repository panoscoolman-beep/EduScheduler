/**
 * Classes View — CRUD for school classes/sections.
 */
const ClassesView = {
    async render(container) {
        const classrooms = await API.classrooms.list();
        const students = await API.request('/students/');

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
                    <div class="form-group col-span-2">
                        <label class="form-label">Μαθητές Τμήματος (Επιλογή πολλών - Ctrl/Cmd+Click)</label>
                        <select class="form-select" id="f-students" multiple style="height: 120px;">
                            ${students.map(s => `
                                <option value="${s.id}" ${(item?.student_ids || []).includes(s.id) ? 'selected' : ''}>
                                    ${s.last_name} ${s.first_name}
                                </option>
                            `).join('')}
                        </select>
                        <div style="font-size: 0.8rem; color: #a0aec0; margin-top: 4px;">Επιλέξτε όσους μαθητές παρακολουθούν αυτό το τμήμα.</div>
                    </div>
                </div>
            `,
            formParser: () => {
                const selectElement = document.getElementById('f-students');
                const selectedStudentIds = Array.from(selectElement.selectedOptions).map(opt => parseInt(opt.value));
                
                return {
                    name: document.getElementById('f-name').value.trim(),
                    short_name: document.getElementById('f-short_name').value.trim(),
                    grade_level: parseInt(document.getElementById('f-grade').value) || null,
                    student_ids: selectedStudentIds,
                    home_room_id: parseInt(document.getElementById('f-homeroom').value) || null,
                };
            },
        });

        container.innerHTML = '<div id="classes-table"></div>';
        await table.render(document.getElementById('classes-table'));
    },
};
