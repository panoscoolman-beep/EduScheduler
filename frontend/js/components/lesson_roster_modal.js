/**
 * 👥 «Μαθητές της κάρτας» — ποιοι παρακολουθούν ΑΥΤΟ το μάθημα.
 *
 * Βάση είναι το τμήμα· εδώ βγάζεις όποιον δεν έρχεται σε αυτές τις ώρες και
 * προσθέτεις όποιον έρχεται από άλλο τμήμα (π.χ. «το ένα δίωρο Φυσικής το
 * κάνει αλλού»). Το πρόγραμμα, οι έλεγχοι συγκρούσεων, τα κενά και οι
 * εκτυπώσεις ακολουθούν αυτή τη λίστα.
 *
 * Browser: global LessonRosterModal. Node: module.exports (pure builders).
 */
const LessonRosterModal = {
    esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    /** Ποιοι παρακολουθούν τώρα (για το αρχικό state του επιλογέα). */
    attendingIds(students) {
        return (students || []).filter(s => s.attends).map(s => s.student_id);
    },

    /** Οι υποψήφιοι του επιλογέα: του τμήματος πρώτα, μετά οι υπόλοιποι. */
    pickerItems(students, allStudents) {
        const known = new Map((students || []).map(s => [s.student_id, s]));
        const items = (students || []).map(s => ({
            id: s.student_id, name: s.name, grade: s.grade, from_class: s.from_class,
        }));
        (allStudents || []).forEach(s => {
            if (known.has(s.id)) return;
            items.push({ id: s.id, name: `${s.last_name} ${s.first_name}`.trim(), grade: s.grade || '', from_class: false });
        });
        return items;
    },

    summary(students, attending) {
        const chosen = new Set(attending || []);
        const excluded = (students || []).filter(s => s.from_class && !chosen.has(s.student_id));
        const added = [...chosen].filter(id => {
            const s = (students || []).find(x => x.student_id === id);
            return !s || !s.from_class;
        });
        const parts = [`${chosen.size} παρακολουθούν`];
        if (excluded.length) parts.push(`${excluded.length} εξαιρούνται από το τμήμα`);
        if (added.length) parts.push(`${added.length} από άλλο τμήμα`);
        return parts.join(' · ');
    },

    headerHtml(lesson, data) {
        const esc = LessonRosterModal.esc;
        return `<p class="text-muted" style="font-size:0.85rem">
                    ${esc(lesson.subject_name || '')} · τμήμα <b>${esc(data.class_name || '')}</b> ·
                    ${lesson.periods_per_week} ώρες/εβδ. Ξετίκαρε όποιον ΔΕΝ έρχεται σε αυτές τις ώρες,
                    πρόσθεσε όποιον έρχεται από άλλο τμήμα.</p>
                <div id="roster-picker"></div>
                <p id="roster-summary" class="text-muted" style="font-size:0.85rem"></p>`;
    },

    // ── Browser ─────────────────────────────────────────────────────────────

    async open(lesson, onSaved) {
        Modal.open('👥 Μαθητές της κάρτας',
            '<div class="loading-spinner"><div class="spinner"></div></div>', null, { hideFooter: true, wide: true });
        let data;
        let all;
        try {
            [data, all] = await Promise.all([API.lessons.students(lesson.id), API.students.list()]);
        } catch (err) {
            Modal.close();
            Toast.error(err.message);
            return;
        }
        let attending = LessonRosterModal.attendingIds(data.students);
        const items = LessonRosterModal.pickerItems(data.students, all);
        Modal.open('👥 Μαθητές της κάρτας', LessonRosterModal.headerHtml(lesson, data),
            () => LessonRosterModal._save(lesson, attending, onSaved),
            { wide: true, saveText: '💾 Αποθήκευση' });
        const refresh = () => {
            const el = document.getElementById('roster-summary');
            if (el) el.textContent = LessonRosterModal.summary(data.students, attending);
        };
        StudentPicker.mount(document.getElementById('roster-picker'), {
            items,
            selectedIds: attending,
            labelOf: (it) => it.name,
            badgesOf: (it) => [it.grade, it.from_class ? 'τμήμα' : 'άλλο τμήμα'].filter(Boolean),
            noun: 'μαθητές',
            onChange: (ids) => {
                attending = ids;
                refresh();
            },
        });
        refresh();
    },

    async _save(lesson, attending, onSaved, force = false) {
        try {
            const res = await API.lessons.setStudents(lesson.id, { attending }, force);
            Modal.close();
            Toast.success(`👥 Αποθηκεύτηκε — ${res.attending} μαθητές σε αυτή την κάρτα.`);
            if (onSaved) await onSaved();
        } catch (err) {
            if (err.status === 409 && err.detail && err.detail.requires_force) {
                Modal.open('⚠️ Επικάλυψη ωρών',
                    `<p style="font-weight:600">${LessonRosterModal.esc(err.detail.message)}</p>
                     <p class="text-muted mt-sm">Συνέχισε μόνο αν θα διορθώσεις τις ώρες μετά.</p>`,
                    () => LessonRosterModal._save(lesson, attending, onSaved, true),
                    { saveText: 'Ναι, αποθήκευση', saveClass: 'btn-warning' });
                return;
            }
            Toast.error(err.message);
        }
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = LessonRosterModal;
}
