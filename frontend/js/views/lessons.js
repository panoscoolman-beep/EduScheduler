/**
 * Lessons View — CRUD for lesson cards (Subject + Teacher + Class + Room).
 */
const LessonsView = {
    _teachers: [],
    _subjects: [],
    _classes: [],
    _classrooms: [],

    async render(container) {
        const self = this;

        // Pre-load related data for dropdowns
        [self._teachers, self._subjects, self._classes, self._classrooms] = await Promise.all([
            API.teachers.list(),
            API.subjects.list(),
            API.classes.list(),
            API.classrooms.list(),
        ]);

        const table = new DataTable({
            columns: [
                { key: 'subject_name', label: 'Μάθημα' },
                { key: 'teacher_name', label: 'Καθηγητής' },
                { key: 'class_name', label: 'Τάξη' },
                { key: 'classroom_name', label: 'Αίθουσα', render: v => v || '—αυτόματη—' },
                { key: 'periods_per_week', label: 'Ώρες/Εβδ' },
                { key: 'duration', label: 'Διάρκεια', render: v => v === 1 ? 'Μονή' : `${v}πλή` },
            ],
            apiService: API.lessons,
            entityName: 'Μαθήματα-Κάρτες',
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Μάθημα *</label>
                        <select class="form-select" id="f-subject">
                            <option value="">— Επιλέξτε —</option>
                            ${self._subjects.map(s => `<option value="${s.id}" ${item?.subject_id === s.id ? 'selected' : ''}>${s.name}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Καθηγητής *</label>
                        <select class="form-select" id="f-teacher">
                            <option value="">— Επιλέξτε —</option>
                            ${self._teachers.map(t => `<option value="${t.id}" ${item?.teacher_id === t.id ? 'selected' : ''}>${t.name} (${t.short_name})</option>`).join('')}
                        </select>
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Τάξη *</label>
                        <select class="form-select" id="f-class">
                            <option value="">— Επιλέξτε —</option>
                            ${self._classes.map(c => `<option value="${c.id}" ${item?.class_id === c.id ? 'selected' : ''}>${c.name}</option>`).join('')}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Αίθουσα (προαιρετικά)</label>
                        <select class="form-select" id="f-classroom">
                            <option value="">— Αυτόματη —</option>
                            ${self._classrooms.map(r => `<option value="${r.id}" ${item?.classroom_id === r.id ? 'selected' : ''}>${r.name}</option>`).join('')}
                        </select>
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Συνολικές Ώρες Διδ/λίας (Εβδομαδιαίως) *</label>
                        <input class="form-input" id="f-ppw" type="number" min="1" max="20" value="${item?.periods_per_week || 1}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Συνεχόμενες Ώρες ανά μάθημα (Block)</label>
                        <select class="form-select" id="f-duration">
                            <option value="1" ${item?.duration === 1 ? 'selected' : ''}>Μονή (1 ώρα)</option>
                            <option value="2" ${item?.duration === 2 ? 'selected' : ''}>Διπλή (2 ώρες)</option>
                            <option value="3" ${item?.duration === 3 ? 'selected' : ''}>Τριπλή (3 ώρες)</option>
                        </select>
                    </div>
                </div>
            `,
            formParser: () => {
                const subject_id = parseInt(document.getElementById('f-subject').value);
                const teacher_id = parseInt(document.getElementById('f-teacher').value);
                const class_id = parseInt(document.getElementById('f-class').value);
                
                if (isNaN(subject_id)) throw new Error("Παρακαλώ επιλέξτε Μάθημα.");
                if (isNaN(teacher_id)) throw new Error("Παρακαλώ επιλέξτε Καθηγητή.");
                if (isNaN(class_id)) throw new Error("Παρακαλώ επιλέξτε Τάξη.");

                return {
                    subject_id,
                    teacher_id,
                    class_id,
                    classroom_id: parseInt(document.getElementById('f-classroom').value) || null,
                    periods_per_week: parseInt(document.getElementById('f-ppw').value) || 1,
                    duration: parseInt(document.getElementById('f-duration').value) || 1,
                    is_locked: false,
                };
            },
        });

        container.innerHTML = '<div id="lessons-table"></div>';
        await table.render(document.getElementById('lessons-table'));
    },
};
