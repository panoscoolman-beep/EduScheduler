/**
 * Lessons View — CRUD for lesson cards (Subject + Teacher + Class + Room).
 *
 * Validation philosophy: Catch the data-quality issues that the
 * solver's _validate_data() would otherwise complain about *before*
 * the user clicks Save, so they don't generate a schedule that ends
 * up with parking-lot entries.
 *
 * Validations:
 *   - subject/teacher/class required (existing)
 *   - distribution must parse as positive ints, sum == periods_per_week
 *   - max block in distribution must fit in the school day
 *   - if subject.requires_special_room and classroom is set, the
 *     classroom.room_type must match (warning, not blocker)
 */
const LessonsView = {
    _teachers: [],
    _subjects: [],
    _classes: [],
    _classrooms: [],
    _periods: [],
    _teachingPeriodsPerDay: 0,

    async render(container) {
        const self = this;

        // Pre-load related data for dropdowns + validation context
        [self._teachers, self._subjects, self._classes, self._classrooms, self._periods] = await Promise.all([
            API.teachers.list(),
            API.subjects.list(),
            API.classes.list(),
            API.classrooms.list(),
            API.periods.list(),
        ]);
        self._teachingPeriodsPerDay = self._periods.filter(p => !p.is_break).length;

        const table = new DataTable({
            columns: [
                { key: 'subject_name', label: 'Μάθημα' },
                { key: 'teacher_name', label: 'Καθηγητής' },
                { key: 'class_name', label: 'Τάξη' },
                { key: 'classroom_name', label: 'Αίθουσα', render: v => v || '—αυτόματη—' },
                { key: 'periods_per_week', label: 'Ώρες/Εβδ' },
                { key: 'distribution', label: 'Blocks', render: v => v || '<span class="text-muted">όλα 1ωρα</span>' },
            ],
            apiService: API.lessons,
            entityName: 'Μαθήματα-Κάρτες',
            formBuilder: (item) => self._buildForm(item),
            formParser: () => self._parseForm(),
            onFormReady: () => self._wireValidation(),
        });

        container.innerHTML = '<div id="lessons-table"></div>';
        await table.render(document.getElementById('lessons-table'));
    },

    // ---------- form -------------------------------------------------------

    _buildForm(item) {
        const periodsHint = `${this._teachingPeriodsPerDay} διδακτικές ώρες/μέρα`;

        return `
            <div class="form-grid">
                <div class="form-group">
                    <label class="form-label">Μάθημα *</label>
                    <select class="form-select" id="f-subject">
                        <option value="">— Επιλέξτε —</option>
                        ${this._subjects.map(s => `<option value="${s.id}" ${item?.subject_id === s.id ? 'selected' : ''}>${s.name}${s.requires_special_room ? ` (απαιτεί ${s.special_room_type || 'ειδική αίθουσα'})` : ''}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Καθηγητής *</label>
                    <select class="form-select" id="f-teacher">
                        <option value="">— Επιλέξτε —</option>
                        ${this._teachers.map(t => `<option value="${t.id}" ${item?.teacher_id === t.id ? 'selected' : ''}>${t.name} (${t.short_name})</option>`).join('')}
                    </select>
                </div>
            </div>
            <div class="form-grid">
                <div class="form-group">
                    <label class="form-label">Τάξη *</label>
                    <select class="form-select" id="f-class">
                        <option value="">— Επιλέξτε —</option>
                        ${this._classes.map(c => `<option value="${c.id}" ${item?.class_id === c.id ? 'selected' : ''}>${c.name}</option>`).join('')}
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Αίθουσα (προαιρετικά)</label>
                    <select class="form-select" id="f-classroom">
                        <option value="">— Αυτόματη —</option>
                        ${this._classrooms.map(r => `<option value="${r.id}" data-room-type="${r.room_type || ''}" ${item?.classroom_id === r.id ? 'selected' : ''}>${r.name}${r.room_type ? ` (${r.room_type})` : ''}</option>`).join('')}
                    </select>
                </div>
            </div>
            <div class="form-grid">
                <div class="form-group">
                    <label class="form-label">Συνολικές Ώρες Διδ/λίας (Εβδομαδιαίως) *</label>
                    <input class="form-input" id="f-ppw" type="number" min="1" max="20" value="${item?.periods_per_week || 1}">
                </div>
                <div class="form-group">
                    <label class="form-label">Κατανομή σε Blocks (Κενό=Μονά)</label>
                    <input class="form-input" id="f-dist" type="text" placeholder="π.χ. 2,2,1" value="${item?.distribution || ''}">
                    <p class="text-muted" style="font-size:0.8em; margin-top:0.3rem;">${periodsHint}</p>
                </div>
            </div>

            <div id="f-validation-msg" style="
                margin-top: 0.5rem;
                padding: 0.5rem 0.75rem;
                border-radius: 4px;
                font-size: 0.9em;
                display: none;
            "></div>
        `;
    },

    /**
     * Wire live-validation hints. The hint area below the form changes
     * color as the user fills in the inputs:
     *   green = looks good
     *   amber = warning (will work but solver may complain)
     *   red   = will fail save
     */
    _wireValidation() {
        const ids = ['f-subject', 'f-classroom', 'f-ppw', 'f-dist'];
        const update = () => this._renderValidationHint();
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('input', update);
                el.addEventListener('change', update);
            }
        });
        update();
    },

    _renderValidationHint() {
        const msgEl = document.getElementById('f-validation-msg');
        if (!msgEl) return;

        const issues = this._collectIssues();
        const errors = issues.filter(i => i.severity === 'error');
        const warnings = issues.filter(i => i.severity === 'warning');

        if (errors.length === 0 && warnings.length === 0) {
            msgEl.style.display = 'none';
            return;
        }

        msgEl.style.display = 'block';
        if (errors.length) {
            msgEl.style.background = '#FEE2E2';
            msgEl.style.color = '#991B1B';
            msgEl.style.border = '1px solid #FCA5A5';
        } else {
            msgEl.style.background = '#FEF3C7';
            msgEl.style.color = '#92400E';
            msgEl.style.border = '1px solid #FCD34D';
        }

        msgEl.innerHTML = [...errors, ...warnings]
            .map(i => `<div>${i.severity === 'error' ? '⛔' : '⚠️'} ${i.message}</div>`)
            .join('');
    },

    /**
     * Inspect the form values and return a list of issues (errors that
     * block save, warnings that just inform). Reused by both
     * _renderValidationHint (live) and _parseForm (final gate).
     */
    _collectIssues() {
        const issues = [];

        const subjectId = parseInt(document.getElementById('f-subject')?.value);
        const classroomId = parseInt(document.getElementById('f-classroom')?.value);
        const ppw = parseInt(document.getElementById('f-ppw')?.value) || 0;
        const distRaw = (document.getElementById('f-dist')?.value || '').trim();

        // Distribution validation
        let blocks = null;
        if (distRaw) {
            const parts = distRaw.split(',').map(p => p.trim()).filter(Boolean);
            if (!parts.every(p => /^\d+$/.test(p))) {
                issues.push({ severity: 'error', message: 'Distribution: μόνο θετικοί ακέραιοι χωρισμένοι με κόμμα.' });
            } else {
                blocks = parts.map(Number);
                if (blocks.some(b => b <= 0)) {
                    issues.push({ severity: 'error', message: 'Distribution: όλα τα blocks πρέπει να είναι ≥ 1.' });
                } else {
                    const sum = blocks.reduce((a, b) => a + b, 0);
                    if (ppw > 0 && sum !== ppw) {
                        issues.push({
                            severity: 'error',
                            message: `Distribution σύνολο = ${sum} αλλά "Ώρες/Εβδ" = ${ppw}. Πρέπει να ταιριάζουν.`,
                        });
                    }
                    if (this._teachingPeriodsPerDay > 0) {
                        const maxBlock = Math.max(...blocks);
                        if (maxBlock > this._teachingPeriodsPerDay) {
                            issues.push({
                                severity: 'error',
                                message: `Block ${maxBlock} ωρών δεν χωράει — η μέρα έχει μόνο ${this._teachingPeriodsPerDay} διδακτικές ώρες.`,
                            });
                        }
                    }
                }
            }
        }

        // Subject + classroom compatibility (warning only)
        if (subjectId && classroomId) {
            const subject = this._subjects.find(s => s.id === subjectId);
            if (subject?.requires_special_room && subject.special_room_type) {
                const roomOpt = document.querySelector(`#f-classroom option[value="${classroomId}"]`);
                const roomType = roomOpt?.dataset.roomType || '';
                if (roomType !== subject.special_room_type) {
                    issues.push({
                        severity: 'warning',
                        message: `Το μάθημα απαιτεί αίθουσα τύπου "${subject.special_room_type}" αλλά η επιλεγμένη είναι "${roomType || 'γενική'}". Ο solver μπορεί να αρνηθεί.`,
                    });
                }
            }
        }

        return issues;
    },

    _parseForm() {
        const subject_id = parseInt(document.getElementById('f-subject').value);
        const teacher_id = parseInt(document.getElementById('f-teacher').value);
        const class_id = parseInt(document.getElementById('f-class').value);

        if (isNaN(subject_id)) throw new Error('Παρακαλώ επιλέξτε Μάθημα.');
        if (isNaN(teacher_id)) throw new Error('Παρακαλώ επιλέξτε Καθηγητή.');
        if (isNaN(class_id)) throw new Error('Παρακαλώ επιλέξτε Τάξη.');

        // Block-saves on errors (warnings just informational)
        const errors = this._collectIssues().filter(i => i.severity === 'error');
        if (errors.length) {
            throw new Error(errors.map(e => '• ' + e.message).join('\n'));
        }

        return {
            subject_id,
            teacher_id,
            class_id,
            classroom_id: parseInt(document.getElementById('f-classroom').value) || null,
            periods_per_week: parseInt(document.getElementById('f-ppw').value) || 1,
            duration: 1, // Deprecated, kept for backward comp
            distribution: document.getElementById('f-dist').value.trim() || null,
            is_locked: false,
        };
    },
};
