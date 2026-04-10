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
            `;

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
};
