/**
 * Students View — CRUD for tutoring center students.
 */
const StudentsView = {
    _classesById: new Map(),
    // Φίλτρο λίστας· μένει στη μνήμη όσο είναι ανοιχτή η σελίδα, ώστε η
    // επιστροφή στην καρτέλα να βρίσκει την ίδια επιλογή (reload = καθαρό).
    _filter: null,

    async render(container) {
        this._filter = this._filter || StudentsHelpers.emptyFilter();
        await Promise.all([this._loadClasses(), this._loadGradeCatalog()]);
        const table = new DataTable({
            columns: [
                { key: 'last_name', label: 'Επώνυμο' },
                { key: 'first_name', label: 'Όνομα' },
                { key: 'grade', label: 'Τάξη', render: v => v ? StudentPicker.esc(v) : '—' },
                { key: 'track', label: 'Κατεύθυνση / Τομέας', render: v => v ? StudentPicker.esc(v) : '—' },
                { key: 'class_ids', label: 'Τμήματα', render: v => this._classBadgesHtml(v) },
                { key: 'email', label: 'Email', render: v => v ? `${v}` : '—' },
                { key: 'phone', label: 'Τηλέφωνο', render: v => v ? `${v}` : '—' },
                { key: 'max_days_per_week', label: 'Max Ημέρες/Εβδ', render: v => v || '—' },
            ],
            apiService: API.students,
            entityName: 'Μαθητές',
            rowFilter: (data) => this._visibleStudents(data),
            onRendered: (all, visible) => this._renderFilterBar(all, visible),
            onFormReady: (item) => this._onStudentFormReady(item),
            customActions: [
                {
                    id: 'classes',
                    title: 'Τμήματα του μαθητή',
                    icon: '🏫',
                    handler: (item) => this._openClassPicker(item, table)
                },
                {
                    id: 'availability',
                    title: 'Πρόγραμμα / Κωλύματα',
                    icon: '📅',
                    handler: (item) => AvailabilityModal.open('students', item)
                }
            ],
            formBuilder: (item) => `
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Επώνυμο *</label>
                        <input class="form-input" id="f-last_name" value="${item?.last_name || ''}" placeholder="π.χ. Παπαδόπουλος">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Όνομα *</label>
                        <input class="form-input" id="f-first_name" value="${item?.first_name || ''}" placeholder="π.χ. Νίκος">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Email</label>
                        <input class="form-input" id="f-email" type="email" value="${item?.email || ''}" placeholder="π.χ. nikos@example.com">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Τηλέφωνο</label>
                        <input class="form-input" id="f-phone" type="tel" value="${item?.phone || ''}" placeholder="π.χ. 6900000000">
                    </div>
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Τάξη</label>
                        <select class="form-select" id="f-grade">
                            ${this._gradeSelectOptions(item?.grade)}
                        </select>
                    </div>
                    <div class="form-group" id="f-track-group">
                        <label class="form-label" id="f-track-label">Κατεύθυνση / Τομέας</label>
                        <select class="form-select" id="f-track"></select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Max Ημέρες / Εβδομάδα</label>
                        <input class="form-input" id="f-max_days" type="number" min="1" max="7" value="${item?.max_days_per_week || ''}">
                    </div>
                </div>
            `,
            formParser: () => ({
                last_name: document.getElementById('f-last_name').value.trim(),
                first_name: document.getElementById('f-first_name').value.trim(),
                email: document.getElementById('f-email').value.trim() || null,
                phone: document.getElementById('f-phone').value.trim() || null,
                grade: document.getElementById('f-grade').value.trim() || null,
                track: (document.getElementById('f-track')?.value || '').trim() || null,
                max_days_per_week: parseInt(document.getElementById('f-max_days').value) || null,
            }),
        });

        container.innerHTML = `
            <div style="display:flex; justify-content:flex-end; gap:0.5rem; margin-bottom:0.5rem">
                <button class="btn btn-secondary" id="students-print"
                        title="Εκτυπώσιμος κατάλογος (αλφαβητικά ή ανά τάξη) — μόνο όσοι φαίνονται με τα τρέχοντα φίλτρα">
                    🖨️ Εκτύπωση
                </button>
                <button class="btn btn-secondary" id="students-export-xlsx"
                        title="Κατέβασε τους μαθητές που φαίνονται (με τα φίλτρα) με στοιχεία, τάξη και τμήματα (Excel)">
                    ⬇️ Εξαγωγή Excel
                </button>
                <button class="btn btn-secondary" id="students-export-csv"
                        title="Ίδια στοιχεία σε CSV (ανοίγει σε Excel/Google Sheets) — με τα τρέχοντα φίλτρα">
                    ⬇️ CSV
                </button>
                <button class="btn btn-secondary" id="crm-import-btn"
                        title="Τράβα τους μαθητές από το Korifi CRM — τέλος η διπλή καταχώρηση">
                    ⬇️ Εισαγωγή από CRM
                </button>
            </div>
            <div class="card sf-card">
                <div class="sf-toolbar">
                    <input class="form-input sf-search" id="sf-search" type="search"
                           placeholder="🔍 Αναζήτηση ονόματος, email ή τηλεφώνου…"
                           value="${StudentsHelpers.esc(this._filter.search)}">
                    <span class="sf-count" id="sf-count"></span>
                    <button class="btn btn-sm btn-secondary" id="sf-clear" style="display:none">
                        ✖ Καθαρισμός φίλτρων
                    </button>
                </div>
                <div id="sf-chips"></div>
            </div>
            <div id="students-table"></div>`;
        this._wireFilters(table);
        await table.render(document.getElementById('students-table'));
        const withFilter = (url) => StudentsHelpers.withFilter(url, this._filter);
        document.getElementById('students-print').addEventListener('click', () =>
            window.open(withFilter('/api/exports/students/print'), '_blank'));
        document.getElementById('students-export-xlsx').addEventListener('click', () =>
            window.open(withFilter('/api/exports/students?format=xlsx'), '_blank'));
        document.getElementById('students-export-csv').addEventListener('click', () =>
            window.open(withFilter('/api/exports/students?format=csv'), '_blank'));
        document.getElementById('crm-import-btn').addEventListener('click', () =>
            this._openCrmImport(container));
    },

    /**
     * Ό,τι δείχνει ο πίνακας: φιλτραρισμένοι + αλφαβητικά κατά επώνυμο. Εδώ
     * «καθαρίζει» και το φίλτρο από επιλογές που δεν ισχύουν πια (π.χ. μετά
     * από διαγραφή του τελευταίου μαθητή μιας τάξης).
     */
    _visibleStudents(data) {
        this._filter = StudentsHelpers.prune(this._filter, data);
        return StudentsHelpers.applyFilter(data, this._filter);
    },

    /** Αναζήτηση + chips + καθαρισμός: listeners μία φορά ανά render. */
    _wireFilters(table) {
        document.getElementById('sf-search').addEventListener('input', (e) =>
            this._setFilter({ ...this._filter, search: e.target.value }, table));
        document.getElementById('sf-chips').addEventListener('click', (e) => {
            const chip = e.target.closest('.sf-chip');
            if (!chip) return;
            this._setFilter(
                StudentsHelpers.toggle(this._filter, chip.dataset.kind, chip.dataset.value), table);
        });
        document.getElementById('sf-clear').addEventListener('click', () => {
            document.getElementById('sf-search').value = '';
            this._setFilter(StudentsHelpers.emptyFilter(), table);
        });
    },

    /** Νέο φίλτρο → ξανασχεδίαση από τα ήδη φορτωμένα δεδομένα (χωρίς fetch). */
    _setFilter(filter, table) {
        this._filter = filter;
        table.renderTable();
    },

    /** Καλείται από το DataTable μετά από κάθε σχεδίαση (και μετά από αποθήκευση). */
    _renderFilterBar(all, visible) {
        const chips = document.getElementById('sf-chips');
        if (!chips) return;
        chips.innerHTML = StudentsHelpers.buildChipsHtml({
            gradeOpts: StudentsHelpers.gradeOptions(all, this._catalog?.grades),
            trackOpts: StudentsHelpers.trackOptions(all, this._filter),
            filter: this._filter,
        });
        document.getElementById('sf-count').textContent =
            StudentsHelpers.countText(visible.length, all.length);
        document.getElementById('sf-clear').style.display =
            StudentsHelpers.isActive(this._filter) ? '' : 'none';
    },

    /**
     * Options της «Τάξης». Ο κατάλογος έρχεται από το backend (μία πηγή
     * αλήθειας)· αν ο μαθητής έχει παλιά τιμή εκτός καταλόγου, μπαίνει κι
     * αυτή ώστε να μη χαθεί σιωπηλά σε ένα save.
     */
    _gradeSelectOptions(current) {
        const esc = StudentPicker.esc;
        const grades = (this._catalog?.grades || []).slice();
        if (current && !grades.includes(current)) grades.unshift(current);
        return ['<option value="">— Χωρίς τάξη —</option>']
            .concat(grades.map(g =>
                `<option value="${esc(g)}"${g === current ? ' selected' : ''}>${esc(g)}</option>`))
            .join('');
    },

    /**
     * Γέμισε/κρύψε το δεύτερο dropdown ανάλογα με την τάξη: κατεύθυνση για
     * Β΄/Γ΄ Λυκείου, τομέας για Β΄/Γ΄ ΕΠΑΛ, τίποτα αλλού.
     */
    _syncTrackField(current, allowUnknown = false) {
        const esc = StudentPicker.esc;
        const grade = document.getElementById('f-grade')?.value || '';
        const group = document.getElementById('f-track-group');
        const select = document.getElementById('f-track');
        const label = document.getElementById('f-track-label');
        if (!group || !select) return;
        const tracks = (this._catalog?.tracks || {})[grade] || [];
        if (!tracks.length) {
            group.style.display = 'none';
            select.innerHTML = '';
            return;
        }
        group.style.display = '';
        if (label) {
            label.textContent = (this._catalog?.track_labels || {})[grade]
                || this._catalog?.default_track_label || 'Κατεύθυνση / Τομέας';
        }
        // `allowUnknown` ΜΟΝΟ στο άνοιγμα της φόρμας: κρατά μια αποθηκευμένη
        // τιμή εκτός καταλόγου (π.χ. ειδικότητα ΕΠΑΛ γραμμένη με το χέρι).
        // Σε ΑΛΛΑΓΗ τάξης δεν ισχύει — αλλιώς η «Σπουδών Υγείας» θα κουβαλιόταν
        // στο Β΄ ΕΠΑΛ ως δήθεν τομέας.
        const list = tracks.slice();
        const keep = current && (list.includes(current) || allowUnknown) ? current : '';
        if (keep && !list.includes(keep)) list.unshift(keep);
        select.innerHTML = ['<option value="">— Χωρίς επιλογή —</option>']
            .concat(list.map(t =>
                `<option value="${esc(t)}"${t === keep ? ' selected' : ''}>${esc(t)}</option>`))
            .join('');
    },

    /** Collapse/expand helper: wiring της φόρμας μετά το άνοιγμα του modal. */
    _onStudentFormReady(item) {
        this._syncTrackField(item?.track || '', true);
        const gradeSelect = document.getElementById('f-grade');
        if (gradeSelect && !gradeSelect.dataset.wired) {
            gradeSelect.dataset.wired = '1';
            // Αλλαγή τάξης → νέες επιλογές κατεύθυνσης (η προηγούμενη κρατιέται
            // μόνο αν εξακολουθεί να ισχύει για τη νέα τάξη).
            gradeSelect.addEventListener('change', () => {
                const keep = document.getElementById('f-track')?.value || '';
                this._syncTrackField(keep);
            });
        }
    },

    /** Κατάλογος τάξεων/κατευθύνσεων από το backend (μία φορά ανά render). */
    async _loadGradeCatalog() {
        try {
            this._catalog = await API.students.gradeOptions();
        } catch (err) {
            // Χωρίς κατάλογο η φόρμα δείχνει μόνο την υπάρχουσα τιμή —
            // καλύτερα από το να μη ανοίγει καθόλου.
            this._catalog = { grades: [], tracks: {}, track_labels: {} };
        }
    },

    async _loadClasses() {
        try {
            const classes = await API.classes.list();
            this._classesById = new Map(classes.map(c => [c.id, c]));
        } catch (err) {
            this._classesById = new Map();
        }
    },

    /** Badges τμημάτων στη λίστα μαθητών (από τα class_ids της απάντησης). */
    _classBadgesHtml(classIds) {
        const names = (classIds || [])
            .map(id => this._classesById.get(id))
            .filter(Boolean)
            .map(c => `<span class="sp-badge" title="${StudentPicker.esc(c.name)}">${StudentPicker.esc(c.short_name)}</span>`);
        return names.length ? `<span class="sp-badges">${names.join('')}</span>` : '—';
    },

    /**
     * Αντίστροφη κατεύθυνση: Μαθητής → Τμήματα. Ίδιος επιλογέας, items =
     * τμήματα· στην αποθήκευση γράφονται μόνο οι διαφορές μέσω των
     * idempotent POST/DELETE /classes/{id}/students/{sid}.
     */
    async _openClassPicker(student, table) {
        const name = StudentPicker.studentLabel(student);
        Modal.open(`🏫 Τμήματα — ${name}`,
            '<div id="f-classes-picker"><div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div></div>',
            async () => {
                const before = new Set(student.class_ids || []);
                const after = new Set(StudentPicker.getSelected());
                const added = [...after].filter(id => !before.has(id));
                const removed = [...before].filter(id => !after.has(id));
                if (!added.length && !removed.length) { Modal.close(); return; }
                try {
                    for (const cid of added) await API.classes.addStudent(cid, student.id);
                    for (const cid of removed) await API.classes.removeStudent(cid, student.id);
                    Toast.success(`${name}: +${added.length} / −${removed.length} τμήματα`);
                    Modal.close();
                    await this._loadClasses();
                    await table.loadData();
                } catch (err) {
                    Toast.error('Αποτυχία ενημέρωσης τμημάτων: ' + err.message);
                }
            });
        try {
            const classes = await API.classes.list();
            this._classesById = new Map(classes.map(c => [c.id, c]));
            StudentPicker.mount('f-classes-picker', {
                items: classes,
                selectedIds: student.class_ids || [],
                labelOf: c => `${c.short_name} — ${c.name}`,
                badgesOf: c => [{ text: `${(c.student_ids || []).length} μαθ.`, title: 'Μαθητές στο τμήμα' }],
                placeholder: '🔍 Αναζήτηση τμήματος…',
                noun: 'τμήματα',
            });
        } catch (err) {
            const el = document.getElementById('f-classes-picker');
            if (el) el.innerHTML = `<div class="sp-empty">Σφάλμα φόρτωσης τμημάτων: ${StudentPicker.esc(err.message)}</div>`;
        }
    },

    async _openCrmImport(container) {
        Modal.open('⬇️ Εισαγωγή μαθητών από CRM',
            '<div id="crm-import-body"><div class="loading-spinner"><div class="spinner"></div><p>Σύνδεση με CRM…</p></div></div>',
            null, { hideFooter: true, wide: true });
        let preview;
        try {
            preview = await API.students.crmPreview();
        } catch (err) {
            document.getElementById('crm-import-body').innerHTML =
                `<p>⚠️ Σφάλμα: ${TimetableHelpers.esc(err.message)}</p>`;
            return;
        }
        const body = document.getElementById('crm-import-body');
        if (!body) return;  // ο χρήστης έκλεισε το modal
        if (!preview.available) {
            body.innerHTML = `<p>⚠️ ${TimetableHelpers.esc(preview.fatal_error || 'Το CRM δεν είναι διαθέσιμο.')}</p>`;
            return;
        }
        const newRows = preview.rows.filter(r => r.status === 'new');
        if (!newRows.length) {
            body.innerHTML = `<p>✅ Όλοι οι μαθητές του CRM (${preview.exists_count}) υπάρχουν ήδη στο EduScheduler — τίποτα να εισαχθεί.</p>`;
            return;
        }
        body.innerHTML = `
            <p><b>${newRows.length}</b> νέοι μαθητές θα εισαχθούν · <b>${preview.exists_count}</b> υπάρχουν ήδη (θα παραλειφθούν).</p>
            <div style="max-height:320px; overflow:auto; border:1px solid var(--border-color,#ccc); border-radius:6px; padding:0.5rem; margin:0.5rem 0">
                <table class="data-table"><thead><tr><th>Επώνυμο</th><th>Όνομα</th><th>Email/Τηλ.</th></tr></thead>
                <tbody>${newRows.map(r => `
                    <tr><td>${TimetableHelpers.esc(r.last_name)}</td>
                        <td>${TimetableHelpers.esc(r.first_name)}</td>
                        <td>${TimetableHelpers.esc(r.email || r.phone || '—')}</td></tr>`).join('')}
                </tbody></table>
            </div>
            <button class="btn btn-primary" id="crm-import-confirm">✅ Εισαγωγή ${newRows.length} μαθητών</button>`;
        document.getElementById('crm-import-confirm').addEventListener('click', async () => {
            try {
                const res = await API.students.crmImport(newRows.map(r => ({
                    first_name: r.first_name, last_name: r.last_name,
                    email: r.email, phone: r.phone,
                })));
                Toast.success(`✅ Εισήχθησαν ${res.created} μαθητές (${res.skipped} παραλείφθηκαν)`);
                Modal.close();
                await this.render(container);
            } catch (err) {
                Toast.error(`Η εισαγωγή απέτυχε: ${err.message}`);
            }
        });
    },
};
