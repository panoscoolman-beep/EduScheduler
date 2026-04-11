/**
 * Students View — CRUD for tutoring center students.
 */
const StudentsView = {
    async render(container) {
        const table = new DataTable({
            columns: [
                { key: 'last_name', label: 'Επώνυμο' },
                { key: 'first_name', label: 'Όνομα' },
                { key: 'email', label: 'Email', render: v => v ? `${v}` : '—' },
                { key: 'phone', label: 'Τηλέφωνο', render: v => v ? `${v}` : '—' },
                { key: 'max_days_per_week', label: 'Max Ημέρες/Εβδ', render: v => v || '—' },
            ],
            apiService: API.students,
            entityName: 'Μαθητές',
            customActions: [
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
                max_days_per_week: parseInt(document.getElementById('f-max_days').value) || null,
            }),
        });

        container.innerHTML = '<div id="students-table"></div>';
        await table.render(document.getElementById('students-table'));
    },
};
