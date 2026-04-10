/**
 * Constraints View — Manage scheduling constraints.
 */
const ConstraintsView = {
    async render(container) {
        const table = new DataTable({
            columns: [
                { key: 'constraint_type', label: 'Τύπος', render: v => `<span class="constraint-badge ${v}">${v === 'hard' ? 'Σκληρός' : 'Μαλακός'}</span>` },
                { key: 'name', label: 'Περιορισμός' },
                { key: 'category', label: 'Κατηγορία', render: v => ({ teacher: 'Καθηγητής', class: 'Τάξη', subject: 'Μάθημα', room: 'Αίθουσα', general: 'Γενικό' }[v] || v) },
                { key: 'weight', label: 'Βάρος', render: (v, item) => item.constraint_type === 'soft' ? `${v}%` : '—' },
                { key: 'is_active', label: 'Ενεργός', render: v => v ? '✅' : '❌' },
            ],
            apiService: API.constraints,
            entityName: 'Περιορισμοί',
            formBuilder: (item) => `
                <div class="form-group">
                    <label class="form-label">Όνομα *</label>
                    <input class="form-input" id="f-name" value="${item?.name || ''}">
                </div>
                <div class="form-grid">
                    <div class="form-group">
                        <label class="form-label">Τύπος *</label>
                        <select class="form-select" id="f-type">
                            <option value="hard" ${item?.constraint_type === 'hard' ? 'selected' : ''}>Σκληρός (υποχρεωτικός)</option>
                            <option value="soft" ${item?.constraint_type !== 'hard' ? 'selected' : ''}>Μαλακός (προτίμηση)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Κατηγορία *</label>
                        <select class="form-select" id="f-category">
                            <option value="general" ${item?.category === 'general' ? 'selected' : ''}>Γενικό</option>
                            <option value="teacher" ${item?.category === 'teacher' ? 'selected' : ''}>Καθηγητής</option>
                            <option value="class" ${item?.category === 'class' ? 'selected' : ''}>Τάξη</option>
                            <option value="subject" ${item?.category === 'subject' ? 'selected' : ''}>Μάθημα</option>
                            <option value="room" ${item?.category === 'room' ? 'selected' : ''}>Αίθουσα</option>
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Βάρος (0-100, για μαλακούς)</label>
                    <input class="weight-slider" id="f-weight" type="range" min="0" max="100" value="${item?.weight ?? 50}">
                    <span class="text-muted" id="f-weight-display">${item?.weight ?? 50}%</span>
                </div>
                <div class="form-group">
                    <label class="form-label">Κανόνας (JSON)</label>
                    <input class="form-input" id="f-rule" value='${item?.rule || '{"type": "custom"}'}'>
                </div>
                <div class="form-group">
                    <label class="form-label">Ενεργός</label>
                    <select class="form-select" id="f-active">
                        <option value="true" ${item?.is_active !== false ? 'selected' : ''}>Ναι</option>
                        <option value="false" ${item?.is_active === false ? 'selected' : ''}>Όχι</option>
                    </select>
                </div>
            `,
            formParser: () => ({
                name: document.getElementById('f-name').value.trim(),
                constraint_type: document.getElementById('f-type').value,
                category: document.getElementById('f-category').value,
                weight: parseInt(document.getElementById('f-weight').value) || 50,
                rule: document.getElementById('f-rule').value.trim(),
                is_active: document.getElementById('f-active').value === 'true',
                entity_id: null,
                entity_type: null,
            }),
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

        await table.render(document.getElementById('constraints-table'));
    },
};
