/**
 * Classes View — CRUD for school classes/sections.
 *
 * Η επιλογή μαθητών γίνεται με τον StudentPicker (αναζήτηση + checkboxes +
 * chips) αντί για native <select multiple> με Ctrl+Click. Οι λίστες
 * μαθητών/τμημάτων φορτώνονται ΦΡΕΣΚΕΣ κάθε φορά που ανοίγει η φόρμα, ώστε
 * τα badges «σε ποια άλλα τμήματα είναι ήδη» να είναι σωστά.
 */
const ClassesView = {
    async render(container) {
        const classrooms = await API.classrooms.list();

        const table = new DataTable({
            columns: [
                { key: 'name', label: 'Τάξη' },
                { key: 'short_name', label: 'Συντομ.' },
                { key: 'grade_level', label: 'Βαθμίδα', render: v => v ? `${v}` : '—' },
                { key: 'student_ids', label: 'Μαθητές', render: v => (v || []).length },
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
                        <label class="form-label">Βασική Αίθουσα</label>
                        <select class="form-select" id="f-homeroom">
                            <option value="">— Καμία —</option>
                            ${classrooms.map(r => `<option value="${r.id}" ${item?.home_room_id === r.id ? 'selected' : ''}>${r.name}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group col-span-3">
                        <label class="form-label">Μαθητές Τμήματος</label>
                        <div id="f-students-picker">
                            <div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση μαθητών...</p></div>
                        </div>
                        <div class="text-muted" style="font-size: 0.8rem; margin-top: 4px;">
                            Τσέκαρε όσους παρακολουθούν αυτό το τμήμα. Τα badges δείχνουν σε ποια άλλα τμήματα είναι ήδη.
                        </div>
                    </div>
                </div>
            `,
            onFormReady: (item) => this._mountStudentPicker(item),
            formParser: () => ({
                name: document.getElementById('f-name').value.trim(),
                short_name: document.getElementById('f-short_name').value.trim(),
                grade_level: parseInt(document.getElementById('f-grade').value) || null,
                student_ids: StudentPicker.getSelected(),
                home_room_id: parseInt(document.getElementById('f-homeroom').value) || null,
            }),
        });

        container.innerHTML = '<div id="classes-table"></div>';
        await table.render(document.getElementById('classes-table'));
    },

    /** Φρέσκοι μαθητές + τμήματα, μετά mount του επιλογέα στη φόρμα. */
    async _mountStudentPicker(item) {
        try {
            const [students, classes] = await Promise.all([API.students.list(), API.classes.list()]);
            const classesById = new Map(classes.map(c => [c.id, c]));
            const currentId = item ? item.id : null;
            StudentPicker.mount('f-students-picker', {
                items: students,
                selectedIds: item ? (item.student_ids || []) : [],
                badgesOf: s => StudentPicker.otherClassBadges(s, classesById, currentId),
                placeholder: '🔍 Αναζήτηση μαθητή (επώνυμο ή όνομα)…',
                noun: 'μαθητές',
            });
        } catch (err) {
            const el = document.getElementById('f-students-picker');
            if (el) el.innerHTML = `<div class="sp-empty">Σφάλμα φόρτωσης μαθητών: ${StudentPicker.esc(err.message)}</div>`;
        }
    },
};
