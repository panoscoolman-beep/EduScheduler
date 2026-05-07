/**
 * Settings View — School configuration.
 */
const SettingsView = {
    async render(container) {
        container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div></div>`;

        try {
            const settings = await API.settings.get();

            container.innerHTML = `
                <div class="card" style="max-width: 600px;">
                    <div class="card-header">
                        <h2 class="card-title">⚙️ Ρυθμίσεις Σχολείου</h2>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Όνομα Σχολείου / Φροντιστηρίου</label>
                        <input class="form-input" id="s-name" value="${settings.school_name || ''}">
                    </div>
                    <div class="form-grid">
                        <div class="form-group">
                            <label class="form-label">Ημέρες / Εβδομάδα</label>
                            <select class="form-select" id="s-days">
                                <option value="5" ${settings.days_per_week === 5 ? 'selected' : ''}>5 (Δευ-Παρ)</option>
                                <option value="6" ${settings.days_per_week === 6 ? 'selected' : ''}>6 (Δευ-Σάβ)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Σχολικό Έτος</label>
                            <input class="form-input" id="s-year" value="${settings.academic_year || ''}">
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Τύπος Ιδρύματος</label>
                        <select class="form-select" id="s-type">
                            <option value="frontistirio" ${settings.institution_type === 'frontistirio' ? 'selected' : ''}>Φροντιστήριο</option>
                            <option value="school" ${settings.institution_type === 'school' ? 'selected' : ''}>Σχολείο</option>
                        </select>
                    </div>
                    <button class="btn btn-primary mt-md" id="s-save">💾 Αποθήκευση</button>
                </div>

                <div class="card mt-lg" id="templates-card" style="max-width: 600px;">
                    <div class="card-header">
                        <h2 class="card-title">📦 Starter Templates</h2>
                    </div>
                    <p class="text-muted" style="margin-bottom: 1rem;">
                        Φόρτωσε ένα έτοιμο preset για bootstrap νέου περιβάλλοντος —
                        subjects, classes, αίθουσες και βασικοί περιορισμοί. Είναι
                        idempotent: επανειλημμένη φόρτωση δεν δημιουργεί διπλά.
                    </p>
                    <div id="templates-list">
                        <div class="loading-spinner"><div class="spinner"></div></div>
                    </div>
                </div>
            `;

            this._loadTemplates();

            document.getElementById('s-save').addEventListener('click', async () => {
                try {
                    await API.settings.update({
                        school_name: document.getElementById('s-name').value.trim(),
                        days_per_week: parseInt(document.getElementById('s-days').value),
                        academic_year: document.getElementById('s-year').value.trim() || null,
                        institution_type: document.getElementById('s-type').value,
                    });
                    Toast.success('Οι ρυθμίσεις αποθηκεύτηκαν');
                    document.getElementById('school-name').textContent = document.getElementById('s-name').value.trim();
                } catch (err) {
                    Toast.error(err.message);
                }
            });

        } catch (err) {
            container.innerHTML = `<p class="text-muted">Σφάλμα: ${err.message}</p>`;
        }
    },

    async _loadTemplates() {
        const listEl = document.getElementById('templates-list');
        try {
            const templates = await API.settings.listTemplates();
            if (!templates.length) {
                listEl.innerHTML = '<p class="text-muted">Δεν υπάρχουν διαθέσιμα templates.</p>';
                return;
            }
            listEl.innerHTML = templates.map(t => `
                <div style="border: 1px solid var(--border, #e5e7eb); border-radius: 6px;
                            padding: 0.75rem 1rem; margin-bottom: 0.5rem;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong>${t.label}</strong>
                            <div class="text-muted" style="font-size: 0.85em; margin-top: 0.25rem;">
                                ${t.description}
                            </div>
                        </div>
                        <button class="btn btn-sm btn-secondary" data-tmpl-key="${t.key}"
                                onclick="SettingsView._previewAndApply('${t.key}', '${t.label.replace(/'/g, "\\'")}')">
                            📥 Εφαρμογή
                        </button>
                    </div>
                </div>
            `).join('');
        } catch (err) {
            listEl.innerHTML = `<p class="text-muted">Σφάλμα: ${err.message}</p>`;
        }
    },

    async _previewAndApply(key, label) {
        // 2-step: preview first, then confirm
        try {
            const preview = await API.settings.previewTemplate(key);
            if (preview.fatal_error) {
                Toast.error(preview.fatal_error);
                return;
            }
            const c = preview.will_create;
            const s = preview.will_skip;
            const confirmMsg =
                `Φόρτωση template: ${label}\n\n` +
                `Θα δημιουργηθούν:\n` +
                `  • ${c.subjects} subjects\n` +
                `  • ${c.classes} classes\n` +
                `  • ${c.classrooms} classrooms\n` +
                `  • ${c.constraints} constraints\n\n` +
                `Θα παραλειφθούν (ήδη υπάρχουν):\n` +
                `  • ${s.subjects} subjects\n` +
                `  • ${s.classes} classes\n` +
                `  • ${s.classrooms} classrooms\n` +
                `  • ${s.constraints} constraints\n\n` +
                `Συνέχεια;`;
            if (!confirm(confirmMsg)) return;

            const result = await API.settings.applyTemplate(key);
            if (result.fatal_error) {
                Toast.error(result.fatal_error);
                return;
            }
            Toast.success(`✅ Δημιουργήθηκαν ${result.total_created} εγγραφές από το ${label}`);
        } catch (err) {
            Toast.error(err.message);
        }
    },
};
