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

        container.innerHTML = `
            <div class="flex-between mb-lg">
                <div></div>
                <button class="btn btn-secondary" id="bulk-import-lessons">
                    📥 Bulk Import (CSV)
                </button>
            </div>
            <div id="lessons-table"></div>
        `;
        await table.render(document.getElementById('lessons-table'));

        document.getElementById('bulk-import-lessons')
            .addEventListener('click', () => self._openBulkImportModal(table));
    },

    // ---------- bulk import modal -----------------------------------------

    async _openBulkImportModal(table) {
        const csvHeader = 'subject,teacher,class,classroom,periods_per_week,distribution';
        const csvSample = [
            csvHeader,
            'Μαθηματικά,ΠΠ,Α-ΛΥΚ,ΑΙΘ-1,4,2,2',
            'Φυσική,ΠΠ,Α-ΛΥΚ,,3,2,1',
        ].join('\n');

        Modal.open(
            '📥 Bulk Import Lessons',
            `
            <p class="text-muted" style="margin-bottom:1rem;">
                Επικόλλησε CSV ή ανέβασε αρχείο. Μπορείς να χρησιμοποιήσεις
                πλήρες όνομα ή <em>short_name</em> για subject/teacher/class/classroom.
                Η στήλη <code>distribution</code> αποδέχεται κόμμα-χωρισμένα
                blocks (π.χ. 2,2 για 4 ώρες).
            </p>
            <div class="form-group">
                <label class="form-label">CSV αρχείο</label>
                <input type="file" id="bulk-csv-file" accept=".csv,.txt"
                       class="form-input">
            </div>
            <div class="form-group">
                <label class="form-label">ή paste CSV εδώ</label>
                <textarea class="form-input" id="bulk-csv-text" rows="8"
                          style="font-family: monospace; font-size: 0.9em;"
                          placeholder="${csvHeader}\n...">${csvSample}</textarea>
            </div>
            <div style="margin: 0.5rem 0;">
                <button class="btn btn-primary" id="bulk-preview-btn">
                    👁️ Preview
                </button>
            </div>
            <div id="bulk-preview-result" style="margin-top:1rem;"></div>
            `,
            null,  // No save handler — we use our own footer
            { hideFooter: true }
        );

        const fileInput = document.getElementById('bulk-csv-file');
        const textArea = document.getElementById('bulk-csv-text');
        const previewBtn = document.getElementById('bulk-preview-btn');
        const resultArea = document.getElementById('bulk-preview-result');

        fileInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (file) {
                textArea.value = await file.text();
            }
        });

        previewBtn.addEventListener('click', async () => {
            const csv = textArea.value;
            if (!csv.trim()) {
                Toast.error('Παρακαλώ δώσε CSV πρώτα');
                return;
            }
            previewBtn.disabled = true;
            previewBtn.textContent = '⏳ Validating...';
            try {
                const result = await API.lessonsBulkImport.preview(csv);
                this._renderPreviewResult(result, csv, table, resultArea);
            } catch (err) {
                Toast.error(err.message);
            }
            previewBtn.disabled = false;
            previewBtn.textContent = '👁️ Preview';
        });
    },

    _renderPreviewResult(result, csvText, table, resultArea) {
        if (result.fatal_error) {
            resultArea.innerHTML = `
                <div style="background:#FEE2E2; color:#991B1B; padding:0.75rem; border-radius:4px;">
                    ⛔ ${result.fatal_error}
                </div>
            `;
            return;
        }

        const total = result.rows.length;
        const hasErrors = result.error_count > 0;

        const rowsHtml = result.rows.map(r => {
            const icon = r.is_valid ? '✅' : '⛔';
            const bg = r.is_valid ? '' : 'background:#FEF3C7;';
            const errorsHtml = r.errors.length
                ? `<div style="color:#991B1B; font-size:0.85em;">${r.errors.map(e => '• ' + e).join('<br>')}</div>`
                : '';
            return `
                <tr style="${bg}">
                    <td>${icon}</td>
                    <td>${r.line_number}</td>
                    <td>${this._esc(r.raw.subject || '')}</td>
                    <td>${this._esc(r.raw.teacher || '')}</td>
                    <td>${this._esc(r.raw.class || '')}</td>
                    <td>${this._esc(r.raw.classroom || '—')}</td>
                    <td>${this._esc(r.raw.periods_per_week || '')}</td>
                    <td>${this._esc(r.raw.distribution || '—')}${errorsHtml}</td>
                </tr>
            `;
        }).join('');

        resultArea.innerHTML = `
            <div style="display:flex; gap:1rem; margin-bottom:0.5rem;">
                <div style="background:#D1FAE5; padding:0.5rem 0.75rem; border-radius:4px;">
                    ✅ ${result.valid_count} έγκυρες
                </div>
                <div style="background:${hasErrors ? '#FEE2E2' : '#D1FAE5'}; padding:0.5rem 0.75rem; border-radius:4px;">
                    ${hasErrors ? '⛔' : '✅'} ${result.error_count} με σφάλμα
                </div>
                <div style="background:#F3F4F6; padding:0.5rem 0.75rem; border-radius:4px;">
                    Σύνολο: ${total}
                </div>
            </div>
            <table class="data-table" style="font-size:0.9em;">
                <thead>
                    <tr><th></th><th>#</th><th>Subject</th><th>Teacher</th><th>Class</th><th>Room</th><th>ppw</th><th>Distribution</th></tr>
                </thead>
                <tbody>${rowsHtml}</tbody>
            </table>
            <div style="margin-top:1rem; display:flex; gap:0.5rem; justify-content:flex-end;">
                <button class="btn btn-secondary" id="bulk-cancel">Άκυρο</button>
                <button class="btn btn-success" id="bulk-commit"
                        ${hasErrors ? 'disabled' : ''}
                        title="${hasErrors ? 'Διόρθωσε πρώτα τα σφάλματα' : ''}">
                    ✅ Εισαγωγή ${result.valid_count} lessons
                </button>
            </div>
        `;

        document.getElementById('bulk-cancel').addEventListener('click', () => Modal.close());
        document.getElementById('bulk-commit').addEventListener('click', async () => {
            const btn = document.getElementById('bulk-commit');
            btn.disabled = true;
            btn.textContent = '⏳ Commit...';
            try {
                const summary = await API.lessonsBulkImport.commit(csvText);
                if (summary.status === 'ok') {
                    Toast.success(summary.message);
                    Modal.close();
                    await table.loadData();
                } else {
                    Toast.error(summary.message);
                }
            } catch (err) {
                Toast.error(err.message);
            }
            btn.disabled = false;
            btn.textContent = '✅ Εισαγωγή';
        });
    },

    _esc(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
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
                    <label class="form-label">Κατανομή σε Blocks</label>
                    <div id="f-dist-chips" style="
                        display: flex; flex-wrap: wrap; gap: 0.4rem;
                        margin-bottom: 0.5rem; min-height: 2rem;">
                        <span class="text-muted" style="font-size:0.85em;">
                            Συμπλήρωσε ώρες/εβδομάδα και επίλεξε…
                        </span>
                    </div>
                    <input class="form-input" id="f-dist" type="text"
                           placeholder="π.χ. 2,2,1 (ή κάνε κλικ σε επιλογή)"
                           value="${item?.distribution || ''}">
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

        // Wire the distribution chips: re-fetch suggestions whenever
        // the user changes ppw, and let chip clicks set the dist input.
        const ppwInput = document.getElementById('f-ppw');
        const distInput = document.getElementById('f-dist');
        const refreshChips = () => this._refreshDistributionChips(
            parseInt(ppwInput.value) || 0, distInput
        );
        ppwInput.addEventListener('input', refreshChips);
        ppwInput.addEventListener('change', refreshChips);
        // Initial render (use the current ppw value, important for edit mode)
        refreshChips();

        update();
    },

    /**
     * Fetch the canonical splits for the current ppw and render them
     * as clickable chips. Highlights the chip whose `value` matches
     * what's already in the dist text input (so edit-mode shows the
     * pre-selected split).
     */
    async _refreshDistributionChips(ppw, distInput) {
        const chipsEl = document.getElementById('f-dist-chips');
        if (!chipsEl) return;
        if (!ppw || ppw < 1) {
            chipsEl.innerHTML = `<span class="text-muted" style="font-size:0.85em;">
                Συμπλήρωσε ώρες/εβδομάδα και επίλεξε…
            </span>`;
            return;
        }

        try {
            const resp = await this._cachedSuggestions(ppw);
            const current = (distInput.value || '').replace(/\s/g, '');

            const chips = resp.options.map(opt => {
                const isActive = opt.value === current;
                return `
                    <button type="button"
                            class="dist-chip"
                            data-dist-value="${opt.value}"
                            style="
                                padding: 0.35rem 0.7rem;
                                border-radius: 999px;
                                border: 1px solid ${isActive ? 'var(--primary, #3B82F6)' : 'var(--border, #d1d5db)'};
                                background: ${isActive ? 'var(--primary, #3B82F6)' : 'transparent'};
                                color: ${isActive ? '#fff' : 'inherit'};
                                font-size: 0.85em;
                                cursor: pointer;
                                white-space: nowrap;
                            "
                            title="${opt.value}">
                        ${opt.label}
                    </button>
                `;
            }).join('');

            // Add an "Empty" chip too — sets distribution to blank
            const emptyActive = current === '';
            chipsEl.innerHTML = `
                <button type="button" class="dist-chip" data-dist-value=""
                        style="
                            padding: 0.35rem 0.7rem;
                            border-radius: 999px;
                            border: 1px dashed ${emptyActive ? 'var(--primary, #3B82F6)' : 'var(--border, #d1d5db)'};
                            background: ${emptyActive ? 'rgba(59, 130, 246, 0.1)' : 'transparent'};
                            font-size: 0.85em; cursor: pointer;
                        ">
                    χωρίς κατανομή (default)
                </button>
                ${chips}
            `;

            // Wire clicks
            chipsEl.querySelectorAll('.dist-chip').forEach(btn => {
                btn.addEventListener('click', () => {
                    distInput.value = btn.dataset.distValue || '';
                    distInput.dispatchEvent(new Event('input'));
                    // Re-render to update active highlight
                    this._refreshDistributionChips(ppw, distInput);
                });
            });
        } catch (err) {
            chipsEl.innerHTML = `<span class="text-muted" style="font-size:0.85em;">
                ⚠️ Σφάλμα: ${err.message}
            </span>`;
        }
    },

    /**
     * Tiny memoization so we don't pound the API while the user
     * types numbers in the ppw input.
     */
    async _cachedSuggestions(ppw) {
        if (!this._suggestionsCache) this._suggestionsCache = new Map();
        if (this._suggestionsCache.has(ppw)) {
            return this._suggestionsCache.get(ppw);
        }
        const resp = await API.lessonsDistributionSuggestions(ppw);
        this._suggestionsCache.set(ppw, resp);
        return resp;
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
