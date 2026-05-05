/**
 * Availability Modal — Interactive Grid for marking Time-Offs
 */
const AvailabilityModal = {
    DAY_NAMES: ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'],

    async open(entityType, item) {
        // entityType is 'teachers' or 'students'
        const title = `Πρόγραμμα / Κωλύματα: ${item.name || item.first_name + ' ' + item.last_name}`;
        
        // Show loading in Modal
        Modal.open(title, '<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>');

        try {
            // Load required data
            const [periods, settings, availabilities] = await Promise.all([
                API.periods.list(),
                API.settings.get(),
                entityType === 'teachers' 
                    ? API.teachers.getAvailability(item.id)
                    : API.students.getAvailability(item.id)
            ]);

            const teachingPeriods = periods.filter(p => !p.is_break);
            const daysCount = settings.days_per_week || 5;

            // Build matrix of unavailabilities [day_of_week][period_id] -> boolean
            const unavailMatrix = {};
            if (availabilities) {
                availabilities.forEach(a => {
                    if (a.status === 'unavailable') {
                        if (!unavailMatrix[a.day_of_week]) unavailMatrix[a.day_of_week] = {};
                        unavailMatrix[a.day_of_week][a.period_id] = true;
                    }
                });
            }

            // Build Grid HTML
            const days = this.DAY_NAMES.slice(0, daysCount);
            const headerCells = days.map(d => `<th>${d}</th>`).join('');
            
            const rows = teachingPeriods.map(period => {
                const dayCells = days.map((_, dayIdx) => {
                    const isUnavail = unavailMatrix[dayIdx] && unavailMatrix[dayIdx][period.id];
                    const className = isUnavail ? 'avail-cell unavail' : 'avail-cell avail';
                    const icon = isUnavail ? '❌' : '✅';
                    
                    return `
                        <td class="${className}" data-day="${dayIdx}" data-period="${period.id}">
                            ${icon}
                        </td>
                    `;
                }).join('');

                return `
                    <tr>
                        <td class="period-cell">
                            ${period.short_name}
                            <span class="period-time">${period.start_time}-${period.end_time}</span>
                        </td>
                        ${dayCells}
                    </tr>
                `;
            }).join('');

            const html = `
                <p style="margin-bottom: 1rem; color: var(--text-muted);">
                    Κάντε κλικ στα κελιά για να σημειώσετε τις ώρες που <strong>ΔΕΝ ΜΠΟΡΕΙ</strong> (❌) να εργαστεί/έχει μάθημα.
                </p>
                <div class="timetable-grid-container">
                    <style>
                        .avail-cell { text-align: center; cursor: pointer; transition: 0.2s; font-size: 1.2rem; user-select: none; }
                        .avail-cell:hover { filter: brightness(0.9); }
                        .avail-cell.avail { background: rgba(34, 197, 94, 0.1); border: 2px solid transparent;}
                        .avail-cell.unavail { background: rgba(239, 68, 68, 0.15); border: 2px solid rgba(239, 68, 68, 0.5); }
                    </style>
                    <table class="timetable-grid" id="avail-table">
                        <thead><tr><th>Ώρα</th>${headerCells}</tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            `;

            Modal.open(title, html, async () => {
                // Save action
                try {
                    const cells = document.querySelectorAll('.avail-cell.unavail');
                    const payload = { availabilities: [] };
                    
                    cells.forEach(cell => {
                        payload.availabilities.push({
                            day_of_week: parseInt(cell.dataset.day),
                            period_id: parseInt(cell.dataset.period),
                            status: 'unavailable'
                        });
                    });

                    if (entityType === 'teachers') {
                        await API.teachers.updateAvailability(item.id, payload);
                    } else {
                        await API.students.updateAvailability(item.id, payload);
                    }

                    Toast.success('Οι διαθεσιμότητες ενημερώθηκαν επιτυχώς.');
                    Modal.close();
                } catch (err) {
                    Toast.error('Αποτυχία: ' + err.message);
                }
            });

            // Attach listeners to cells
            document.querySelectorAll('.avail-cell').forEach(cell => {
                cell.addEventListener('click', (e) => {
                    const td = e.currentTarget;
                    if (td.classList.contains('avail')) {
                        td.classList.replace('avail', 'unavail');
                        td.innerHTML = '❌';
                    } else {
                        td.classList.replace('unavail', 'avail');
                        td.innerHTML = '✅';
                    }
                });
            });

        } catch(err) {
            Modal.open(title, `<div class="alert alert-error">Σφάλμα: ${err.message}</div>`);
            console.error(err);
        }
    }
};
