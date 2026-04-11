/**
 * DataTable Component — Reusable CRUD table with add/edit/delete.
 */
class DataTable {
    constructor({ containerId, columns, apiService, entityName, formBuilder, formParser }) {
        this.container = document.getElementById(containerId) || document.createElement('div');
        this.columns = columns;
        this.api = apiService;
        this.entityName = entityName;
        this.slug = entityName.replace(/[^a-zA-Zα-ωΑ-Ω0-9]/g, '_').toLowerCase();
        this.formBuilder = formBuilder;
        this.formParser = formParser;
        this.customActions = arguments[0].customActions || [];
        this.data = [];
    }

    async render(targetEl) {
        if (targetEl) this.container = targetEl;

        const html = `
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">${this.entityName}</h2>
                    <button class="btn btn-primary" id="dt-add-${this.slug}">
                        ➕ Προσθήκη
                    </button>
                </div>
                <div class="data-table-container" id="dt-table-${this.slug}">
                    <div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>
                </div>
            </div>
        `;

        this.container.innerHTML = html;
        this.container.querySelector(`#dt-add-${this.slug}`).addEventListener('click', () => this.openForm());
        await this.loadData();
    }

    async loadData() {
        try {
            this.data = await this.api.list();
            this.renderTable();
        } catch (err) {
            Toast.error(`Σφάλμα φόρτωσης: ${err.message}`);
        }
    }

    renderTable() {
        const tableContainer = this.container.querySelector(`#dt-table-${this.slug}`);

        if (!this.data || this.data.length === 0) {
            tableContainer.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📭</div>
                    <p class="empty-state-text">Δεν υπάρχουν εγγραφές ακόμα</p>
                    <button class="btn btn-primary" id="dt-empty-add">➕ Προσθήκη</button>
                </div>
            `;
            tableContainer.querySelector('#dt-empty-add')?.addEventListener('click', () => this.openForm());
            return;
        }

        const headerCells = this.columns.map(c => `<th>${c.label}</th>`).join('');

        const rows = this.data.map(item => {
            const cells = this.columns.map(col => {
                let value = item[col.key];
                if (col.render) value = col.render(value, item);
                return `<td>${value ?? ''}</td>`;
            }).join('');

            const customBtns = this.customActions.map(action => {
                return `<button class="btn btn-sm btn-secondary dt-custom" data-action="${action.id}" data-id="${item.id}" title="${action.title}">${action.icon}</button>`;
            }).join(' ');

            return `
                <tr data-id="${item.id}">
                    ${cells}
                    <td class="actions">
                        ${customBtns}
                        <button class="btn btn-sm btn-secondary dt-edit" data-id="${item.id}" title="Επεξεργασία">✏️</button>
                        <button class="btn btn-sm btn-danger dt-delete" data-id="${item.id}" title="Διαγραφή">🗑️</button>
                    </td>
                </tr>
            `;
        }).join('');

        tableContainer.innerHTML = `
            <table class="data-table">
                <thead><tr>${headerCells}<th style="text-align:right">Ενέργειες</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        `;

        // Attach event listeners
        tableContainer.querySelectorAll('.dt-edit').forEach(btn => {
            btn.addEventListener('click', () => this.openForm(parseInt(btn.dataset.id)));
        });
        tableContainer.querySelectorAll('.dt-delete').forEach(btn => {
            btn.addEventListener('click', () => this.confirmDelete(parseInt(btn.dataset.id)));
        });
        tableContainer.querySelectorAll('.dt-custom').forEach(btn => {
            btn.addEventListener('click', () => {
                const actionId = btn.dataset.action;
                const itemId = parseInt(btn.dataset.id);
                const actionDef = this.customActions.find(a => a.id === actionId);
                const item = this.data.find(d => d.id === itemId);
                if (actionDef && actionDef.handler && item) {
                    actionDef.handler(item);
                }
            });
        });
    }

    openForm(editId = null) {
        const item = editId ? this.data.find(d => d.id === editId) : null;
        const title = item ? `Επεξεργασία` : `Νέο`;
        const formHTML = this.formBuilder(item);

        Modal.open(`${title} — ${this.entityName}`, formHTML, async () => {
            try {
                const formData = this.formParser();
                if (editId) {
                    await this.api.update(editId, formData);
                    Toast.success('Η εγγραφή ενημερώθηκε');
                } else {
                    await this.api.create(formData);
                    Toast.success('Η εγγραφή δημιουργήθηκε');
                }
                Modal.close();
                await this.loadData();
            } catch (err) {
                Toast.error(err.message);
            }
        });
    }

    confirmDelete(id) {
        const item = this.data.find(d => d.id === id);
        const name = item?.name || item?.short_name || `#${id}`;

        Modal.open(
            'Επιβεβαίωση Διαγραφής',
            `<p>Είστε σίγουροι ότι θέλετε να διαγράψετε <strong>"${name}"</strong>;</p>
             <p class="text-muted mt-sm">Η ενέργεια αυτή δεν μπορεί να αναιρεθεί.</p>`,
            async () => {
                try {
                    await this.api.delete(id);
                    Toast.success('Η εγγραφή διαγράφηκε');
                    Modal.close();
                    await this.loadData();
                } catch (err) {
                    Toast.error(err.message);
                }
            },
            { saveText: 'Διαγραφή', saveClass: 'btn-danger' },
        );
    }
}
