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

        const archive = ArchiveControls.create(API.classes, 'το τμήμα');
        const table = new DataTable({
            columns: [
                { key: 'name', label: 'Τάξη' , render: ArchiveControls.nameRender },
                { key: 'short_name', label: 'Συντομ.' },
                { key: 'grade_level', label: 'Βαθμίδα', render: v => v ? `${v}` : '—' },
                { key: 'student_ids', label: 'Μαθητές', render: v => (v || []).length },
            ],
            apiService: archive.api,
            toolbarHtml: archive.toolbarHtml(),
            customActions: [archive.action],
            entityName: 'Τάξεις',
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Όνομα Τάξης *</label>
                        <input class="form-input" id="f-name" value="${DataTable.esc(item?.name || '')}" placeholder="π.χ. Α1 Γυμνασίου">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Συντομογραφία *</label>
                        <input class="form-input" id="f-short_name" value="${DataTable.esc(item?.short_name || '')}" placeholder="π.χ. Α1" maxlength="20">
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
                            ${classrooms.map(r => `<option value="${r.id}" ${item?.home_room_id === r.id ? 'selected' : ''}>${DataTable.esc(r.name)}</option>`).join('')}
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
            formParser: () => {
                const data = {
                    name: document.getElementById('f-name').value.trim(),
                    short_name: document.getElementById('f-short_name').value.trim(),
                    grade_level: parseInt(document.getElementById('f-grade').value) || null,
                    home_room_id: parseInt(document.getElementById('f-homeroom').value) || null,
                };
                // Οι μαθητές στέλνονται ΜΟΝΟ αν φορτώθηκε ο επιλογέας ΑΥΤΗΣ της
                // φόρμας. Αλλιώς (π.χ. σφάλμα φόρτωσης) το πεδίο λείπει και ο
                // server αφήνει τις εγγραφές ως έχουν — πριν, έφευγε [] ή η
                // επιλογή άλλου τμήματος και το τμήμα άδειαζε σιωπηλά.
                if (this._pickerOk) data.student_ids = StudentPicker.getSelected();
                return data;
            },
        });

        container.innerHTML = '<div id="classes-table"></div>';
        await table.render(document.getElementById('classes-table'));
        archive.wire(container, table);
    },

    /** Φρέσκοι μαθητές + τμήματα, μετά mount του επιλογέα στη φόρμα. */
    async _mountStudentPicker(item) {
        // Νέα φόρμα: τίποτα από προηγούμενο επιλογέα, και το «φορτώθηκε» μόνο
        // για αυτό το άνοιγμα (token: μια καθυστερημένη απάντηση παλιάς φόρμας
        // δεν γράφει στη νέα).
        const token = (this._pickerToken = (this._pickerToken || 0) + 1);
        this._pickerOk = false;
        StudentPicker._state = null;
        try {
            const [students, classes] = await Promise.all([API.students.list(), API.classes.list()]);
            if (token !== this._pickerToken) return;
            const classesById = new Map(classes.map(c => [c.id, c]));
            const currentId = item ? item.id : null;
            const mounted = StudentPicker.mount('f-students-picker', {
                items: students,
                selectedIds: item ? (item.student_ids || []) : [],
                badgesOf: s => StudentPicker.otherClassBadges(s, classesById, currentId),
                placeholder: '🔍 Αναζήτηση μαθητή (επώνυμο ή όνομα)…',
                noun: 'μαθητές',
            });
            this._pickerOk = !!mounted;
        } catch (err) {
            if (token !== this._pickerToken) return;
            const el = document.getElementById('f-students-picker');
            if (el) el.innerHTML = `<div class="sp-empty">Σφάλμα φόρτωσης μαθητών: ${StudentPicker.esc(err.message)}</div>`;
        }
    },
};
