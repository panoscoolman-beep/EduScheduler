/**
 * Constraints View — Manage scheduling constraints.
 *
 * Form is "smart": instead of asking the user to write a JSON rule by
 * hand, we offer a typed dropdown of every rule type the solver
 * understands and render the matching parameter widgets. Advanced users
 * can still pick "Custom" to fall back to raw JSON.
 *
 * Structure mirrors backend/solver/engine.py — keep these two in sync
 * when adding a new rule_type.
 */

// ---------------------------------------------------------------------------
// Rule type catalogue — single source of truth for the UI
// ---------------------------------------------------------------------------

const RULE_TYPES = {
    // ─── No-param soft rules ────────────────────────────────────────────
    min_teacher_gaps: {
        label: 'Ελάχιστα κενά καθηγητή',
        description: 'Penalty αν ο καθηγητής έχει 1ωρα παράθυρα ανάμεσα σε μαθήματα.',
        params: [],
        defaultCategory: 'teacher',
    },
    min_class_gaps: {
        label: 'Ελάχιστα κενά τμήματος',
        description: 'Penalty αν το τμήμα έχει σπασμένο πρόγραμμα σε μία μέρα.',
        params: [],
        defaultCategory: 'class',
    },
    subject_distribution: {
        label: 'Κατανομή μαθήματος σε διαφορετικές μέρες',
        description: 'Penalty όταν το ίδιο μάθημα γίνεται >1 φορά την ίδια μέρα.',
        params: [],
        defaultCategory: 'subject',
    },
    teacher_day_balance: {
        label: 'Ισορροπία ωρών καθηγητή ανά μέρα',
        description: 'Penalty όταν ένας καθηγητής έχει πολύ φορτωμένη μέρα ή πολύ ελαφριά.',
        params: [],
        defaultCategory: 'teacher',
    },
    consecutive_blocks_preference: {
        label: 'Προτίμηση συνεχόμενων blocks (διπλά αντί 1ωρα)',
        description: 'Για μαθήματα ≥2 ωρών χωρίς explicit distribution, προτίμα 2ωρα blocks.',
        params: [],
        defaultCategory: 'general',
    },
    class_compactness: {
        label: 'Συμπτυγμένο πρόγραμμα τμήματος',
        description: 'Penalty για κάθε επιπλέον μέρα παρουσίας τμήματος πέρα από το ελάχιστο.',
        params: [],
        defaultCategory: 'class',
    },

    // ─── Parametrized soft rules ────────────────────────────────────────
    no_late_day: {
        label: 'Όχι μάθημα μετά από συγκεκριμένη ώρα',
        description: 'Π.χ. "Β\' Λυκείου όχι μετά τις 14:00". Διαλέγεις την τελευταία επιτρεπόμενη ώρα και (προαιρετικά) το συγκεκριμένο τμήμα ή καθηγητή.',
        params: [
            { key: 'max_period_index', label: 'Τελευταία επιτρεπόμενη ώρα (0-indexed)', type: 'number', min: 0, max: 12, default: 5 },
            { key: 'scope', label: 'Εφαρμογή σε', type: 'select', options: [
                { value: 'all', label: 'Όλους' },
                { value: 'class', label: 'Συγκεκριμένο τμήμα' },
                { value: 'teacher', label: 'Συγκεκριμένο καθηγητή' },
            ], default: 'all' },
            { key: 'id', label: 'ID οντότητας (όταν scope ≠ all)', type: 'entity-picker', dependsOn: 'scope' },
        ],
        defaultCategory: 'general',
    },
    teacher_preferred_days: {
        label: 'Προτιμώμενες ημέρες καθηγητή',
        description: 'Penalty όταν ο καθηγητής διδάσκει σε μη-προτιμώμενες μέρες.',
        params: [
            { key: 'teacher_id', label: 'Καθηγητής', type: 'select-teacher' },
            { key: 'days', label: 'Προτιμώμενες ημέρες', type: 'days-checkbox', default: [0, 1, 2, 3, 4] },
        ],
        defaultCategory: 'teacher',
    },

    custom: {
        label: 'Custom (raw JSON)',
        description: 'Για advanced χρήση. Γράψε JSON όπως καταλαβαίνει το engine.',
        params: [{ key: '__raw_json__', label: 'JSON', type: 'textarea', rows: 4, default: '{"type": "custom"}' }],
        defaultCategory: 'general',
    },
};

const DAY_LABELS = ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'];

// ---------------------------------------------------------------------------
// View
// ---------------------------------------------------------------------------

const ConstraintsView = {
    async render(container) {
        // Pre-fetch teachers + classes so the entity pickers can populate
        // synchronously when the form re-renders on rule-type change.
        let teachers = [], classes = [];
        try {
            [teachers, classes] = await Promise.all([
                API.teachers.list(),
                API.classes.list(),
            ]);
        } catch (e) {
            // Soft fail — entity pickers will degrade to raw number input
        }

        const table = new DataTable({
            columns: [
                { key: 'constraint_type', label: 'Τύπος', render: v => `<span class="constraint-badge ${v}">${v === 'hard' ? 'Σκληρός' : 'Μαλακός'}</span>` },
                { key: 'name', label: 'Περιορισμός' },
                { key: 'rule', label: 'Κανόνας', render: v => this._renderRuleSummary(v) },
                { key: 'category', label: 'Κατηγορία', render: v => ({ teacher: 'Καθηγητής', class: 'Τάξη', subject: 'Μάθημα', room: 'Αίθουσα', general: 'Γενικό' }[v] || v) },
                { key: 'weight', label: 'Βάρος', render: (v, item) => item.constraint_type === 'soft' ? `${v}%` : '—' },
                { key: 'is_active', label: 'Ενεργός', render: v => v ? '✅' : '❌' },
            ],
            apiService: API.constraints,
            entityName: 'Περιορισμοί',
            formBuilder: (item) => this._buildForm(item),
            formParser: () => this._parseForm(),
            onFormReady: () => this._wireFormEvents(teachers, classes),
        });

        container.innerHTML = `
            <div class="flex-between mb-lg">
                <div></div>
                <button class="btn btn-secondary" id="seed-constraints">⚙️ Φόρτωση Προεπιλεγμένων</button>
            </div>
            <div id="constraints-table"></div>
        `;

        document.getElementById('seed-constraints').addEventListener('click', async () => {
            try {
                await API.constraints.seedDefaults();
                Toast.success('Φορτώθηκαν οι προεπιλεγμένοι περιορισμοί');
                await table.loadData();
            } catch (err) {
                Toast.error(err.message);
            }
        });

        // Stash data so wireFormEvents can find them via closure
        this._teachers = teachers;
        this._classes = classes;

        await table.render(document.getElementById('constraints-table'));
    },

    // ---------- column rendering -------------------------------------------

    _renderRuleSummary(ruleStr) {
        if (!ruleStr) return '<span class="text-muted">—</span>';
        try {
            const r = typeof ruleStr === 'string' ? JSON.parse(ruleStr) : ruleStr;
            const t = r.type;
            const meta = RULE_TYPES[t];
            if (!meta) return `<code>${t || '?'}</code>`;
            const extras = [];
            if (t === 'no_late_day' && r.max_period_index !== undefined) {
                extras.push(`μέχρι ${r.max_period_index + 1}η ώρα`);
            }
            if (t === 'no_late_day' && r.scope && r.scope !== 'all') {
                extras.push(r.scope === 'class' ? `τμήμα ${r.id}` : `καθηγητής ${r.id}`);
            }
            if (t === 'teacher_preferred_days' && Array.isArray(r.days)) {
                extras.push(r.days.map(d => DAY_LABELS[d]?.slice(0, 3)).join(','));
            }
            const tail = extras.length ? ` <span class="text-muted">(${extras.join(', ')})</span>` : '';
            return `${meta.label}${tail}`;
        } catch {
            return `<code>${ruleStr.slice(0, 30)}…</code>`;
        }
    },

    // ---------- form building ----------------------------------------------

    _buildForm(item) {
        const existingRule = this._safeParseRule(item?.rule) || { type: 'min_teacher_gaps' };
        const ruleType = existingRule.type in RULE_TYPES ? existingRule.type : 'custom';

        const ruleTypeOptions = Object.entries(RULE_TYPES).map(([key, meta]) =>
            `<option value="${key}" ${ruleType === key ? 'selected' : ''}>${meta.label}</option>`
        ).join('');

        return `
            <div class="form-group">
                <label class="form-label">Όνομα *</label>
                <input class="form-input" id="f-name" value="${this._esc(item?.name || '')}">
            </div>

            <div class="form-grid">
                <div class="form-group">
                    <label class="form-label">Τύπος *</label>
                    <select class="form-select" id="f-type">
                        <option value="soft" ${item?.constraint_type !== 'hard' ? 'selected' : ''}>Μαλακός (προτίμηση)</option>
                        <option value="hard" ${item?.constraint_type === 'hard' ? 'selected' : ''}>Σκληρός (υποχρεωτικός)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Κατηγορία *</label>
                    <select class="form-select" id="f-category">
                        ${['general', 'teacher', 'class', 'subject', 'room'].map(c =>
                            `<option value="${c}" ${item?.category === c ? 'selected' : ''}>${
                                {general: 'Γενικό', teacher: 'Καθηγητής', class: 'Τάξη', subject: 'Μάθημα', room: 'Αίθουσα'}[c]
                            }</option>`
                        ).join('')}
                    </select>
                </div>
            </div>

            <div class="form-group">
                <label class="form-label">Κανόνας *</label>
                <select class="form-select" id="f-rule-type">
                    ${ruleTypeOptions}
                </select>
                <p class="text-muted" id="f-rule-desc" style="font-size:0.85em; margin-top:0.4rem;">
                    ${this._esc(RULE_TYPES[ruleType].description)}
                </p>
            </div>

            <div id="f-rule-params" class="rule-params-area" style="
                background: var(--surface, #f9fafb);
                padding: 0.75rem 1rem;
                border-radius: 6px;
                border: 1px solid var(--border, #e5e7eb);
                margin-bottom: 1rem;
            "></div>

            <div class="form-group">
                <label class="form-label">Βάρος (0-100, για μαλακούς)</label>
                <input class="weight-slider" id="f-weight" type="range" min="0" max="100"
                       value="${item?.weight ?? 50}" oninput="document.getElementById('f-weight-display').textContent = this.value + '%';">
                <span class="text-muted" id="f-weight-display">${item?.weight ?? 50}%</span>
            </div>

            <div class="form-group">
                <label class="form-label">Ενεργός</label>
                <select class="form-select" id="f-active">
                    <option value="true" ${item?.is_active !== false ? 'selected' : ''}>Ναι</option>
                    <option value="false" ${item?.is_active === false ? 'selected' : ''}>Όχι</option>
                </select>
            </div>

            <input type="hidden" id="f-existing-rule" value='${this._esc(JSON.stringify(existingRule))}'>
        `;
    },

    /**
     * Wire up dynamic behavior: whenever the user picks a different rule
     * type, re-render the params section. Initial render also uses this
     * function so we don't duplicate logic.
     */
    _wireFormEvents(teachers, classes) {
        const ruleSelect = document.getElementById('f-rule-type');
        const descEl = document.getElementById('f-rule-desc');
        const paramsEl = document.getElementById('f-rule-params');
        const existingRuleEl = document.getElementById('f-existing-rule');
        const categorySelect = document.getElementById('f-category');

        if (!ruleSelect || !paramsEl) return;

        const initialRule = this._safeParseRule(existingRuleEl.value) || {};

        const renderParams = (ruleType, prefill) => {
            const meta = RULE_TYPES[ruleType];
            descEl.textContent = meta.description;
            paramsEl.innerHTML = this._renderParamFields(meta.params, prefill || {}, teachers, classes);
            this._wireParamFieldEvents();
        };

        // Initial render
        renderParams(ruleSelect.value, initialRule);

        ruleSelect.addEventListener('change', () => {
            renderParams(ruleSelect.value, {});
            // Auto-set category to the rule's natural fit (don't override
            // if user already picked something different in this session)
            const meta = RULE_TYPES[ruleSelect.value];
            if (meta?.defaultCategory && categorySelect.dataset.userTouched !== 'true') {
                categorySelect.value = meta.defaultCategory;
            }
        });

        categorySelect.addEventListener('change', () => {
            categorySelect.dataset.userTouched = 'true';
        });
    },

    _renderParamFields(paramSpecs, prefill, teachers, classes) {
        if (!paramSpecs.length) {
            return '<p class="text-muted" style="margin:0;">Αυτός ο κανόνας δεν χρειάζεται παραμέτρους — απλά ορίσε το βάρος.</p>';
        }

        return paramSpecs.map(spec => {
            const id = `f-param-${spec.key}`;
            const value = prefill[spec.key] !== undefined ? prefill[spec.key] : spec.default;

            switch (spec.type) {
                case 'number':
                    return `
                        <div class="form-group">
                            <label class="form-label">${spec.label}</label>
                            <input class="form-input" id="${id}" type="number"
                                   min="${spec.min ?? ''}" max="${spec.max ?? ''}"
                                   value="${value ?? ''}">
                        </div>
                    `;
                case 'textarea':
                    return `
                        <div class="form-group">
                            <label class="form-label">${spec.label}</label>
                            <textarea class="form-input" id="${id}" rows="${spec.rows || 3}"
                                      style="font-family: monospace; font-size: 0.9em;">${this._esc(typeof value === 'string' ? value : JSON.stringify(value || {}))}</textarea>
                        </div>
                    `;
                case 'select':
                    return `
                        <div class="form-group">
                            <label class="form-label">${spec.label}</label>
                            <select class="form-select" id="${id}" data-depends-target="${spec.key}">
                                ${spec.options.map(o =>
                                    `<option value="${o.value}" ${o.value === value ? 'selected' : ''}>${o.label}</option>`
                                ).join('')}
                            </select>
                        </div>
                    `;
                case 'select-teacher':
                    return `
                        <div class="form-group">
                            <label class="form-label">${spec.label}</label>
                            <select class="form-select" id="${id}">
                                <option value="">— Επίλεξε καθηγητή —</option>
                                ${teachers.map(t =>
                                    `<option value="${t.id}" ${t.id == value ? 'selected' : ''}>${t.name}</option>`
                                ).join('')}
                            </select>
                        </div>
                    `;
                case 'entity-picker': {
                    // Hidden by default; shown when scope != 'all'
                    const visible = (prefill.scope && prefill.scope !== 'all');
                    return `
                        <div class="form-group" id="${id}-wrapper" style="display: ${visible ? 'block' : 'none'};">
                            <label class="form-label">${spec.label}</label>
                            <select class="form-select" id="${id}">
                                <option value="">— Διάλεξε —</option>
                                <optgroup label="Τμήματα">
                                    ${classes.map(c => `<option data-kind="class" value="${c.id}" ${c.id == value && prefill.scope === 'class' ? 'selected' : ''}>${c.name}</option>`).join('')}
                                </optgroup>
                                <optgroup label="Καθηγητές">
                                    ${teachers.map(t => `<option data-kind="teacher" value="${t.id}" ${t.id == value && prefill.scope === 'teacher' ? 'selected' : ''}>${t.name}</option>`).join('')}
                                </optgroup>
                            </select>
                        </div>
                    `;
                }
                case 'days-checkbox': {
                    const arr = Array.isArray(value) ? value : [];
                    return `
                        <div class="form-group">
                            <label class="form-label">${spec.label}</label>
                            <div id="${id}" style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                                ${DAY_LABELS.slice(0, 7).map((day, idx) => `
                                    <label style="display:flex; align-items:center; gap:0.3rem; padding:0.3rem 0.6rem; border:1px solid var(--border,#e5e7eb); border-radius:4px; cursor:pointer;">
                                        <input type="checkbox" class="param-day-cb" value="${idx}" ${arr.includes(idx) ? 'checked' : ''}>
                                        ${day}
                                    </label>
                                `).join('')}
                            </div>
                        </div>
                    `;
                }
                default:
                    return `<div class="form-group"><label>${spec.label}</label><input class="form-input" id="${id}" value="${value ?? ''}"></div>`;
            }
        }).join('');
    },

    _wireParamFieldEvents() {
        // Show/hide entity-picker when scope changes
        const scopeSelect = document.getElementById('f-param-scope');
        const idWrapper = document.getElementById('f-param-id-wrapper');
        if (scopeSelect && idWrapper) {
            scopeSelect.addEventListener('change', () => {
                idWrapper.style.display = scopeSelect.value === 'all' ? 'none' : 'block';
            });
        }
    },

    // ---------- form parsing -----------------------------------------------

    _parseForm() {
        const ruleType = document.getElementById('f-rule-type').value;
        const rule = this._buildRuleFromForm(ruleType);
        return {
            name: document.getElementById('f-name').value.trim(),
            constraint_type: document.getElementById('f-type').value,
            category: document.getElementById('f-category').value,
            weight: parseInt(document.getElementById('f-weight').value) || 50,
            rule: JSON.stringify(rule),
            is_active: document.getElementById('f-active').value === 'true',
            entity_id: null,
            entity_type: null,
        };
    },

    _buildRuleFromForm(ruleType) {
        const meta = RULE_TYPES[ruleType];
        if (!meta) return { type: ruleType };

        // Custom passthrough — raw JSON textarea
        if (ruleType === 'custom') {
            const raw = document.getElementById('f-param-__raw_json__')?.value?.trim() || '{}';
            try {
                return JSON.parse(raw);
            } catch {
                return { type: 'custom', __invalid__: raw };
            }
        }

        const out = { type: ruleType };
        for (const spec of meta.params) {
            const id = `f-param-${spec.key}`;
            const el = document.getElementById(id);

            switch (spec.type) {
                case 'number':
                    if (el && el.value !== '') out[spec.key] = parseInt(el.value);
                    break;
                case 'select':
                case 'select-teacher':
                    if (el && el.value) {
                        out[spec.key] = spec.type === 'select-teacher'
                            ? parseInt(el.value)
                            : el.value;
                    }
                    break;
                case 'entity-picker': {
                    const sc = document.getElementById('f-param-scope')?.value;
                    if (sc && sc !== 'all' && el && el.value) {
                        out[spec.key] = parseInt(el.value);
                    }
                    break;
                }
                case 'days-checkbox': {
                    const checked = Array.from(document.querySelectorAll('.param-day-cb:checked'))
                        .map(cb => parseInt(cb.value));
                    out[spec.key] = checked;
                    break;
                }
                default:
                    if (el) out[spec.key] = el.value;
            }
        }
        return out;
    },

    // ---------- helpers ----------------------------------------------------

    _safeParseRule(s) {
        if (!s) return null;
        if (typeof s === 'object') return s;
        try { return JSON.parse(s); } catch { return null; }
    },

    _esc(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },
};
