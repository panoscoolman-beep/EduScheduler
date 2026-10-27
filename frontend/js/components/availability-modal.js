/**
 * Availability Modal — Interactive Grid for marking Time-Offs
 */
const AvailabilityModal = {
    DAY_NAMES: ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'],

    async open(entityType, item) {
        // entityType is 'teachers' or 'students'
        const title = `Πρόγραμμα / Κωλύματα: ${item.name || item.first_name + ' ' + item.last_name}`;
        
        // Show loading in Modal
        Modal.open(title, '<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>',
            null, { hideFooter: true });
        // Αν στο μεταξύ έκλεισε ή άνοιξε άλλο παράθυρο, το πλέγμα δεν ξανανοίγει μόνο του.
        const token = Modal._token;
        const stillMine = () => Modal._token === token && Modal.isOpen();

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
            // Κωλύματα σε μέρες/ώρες που το πλέγμα δεν δείχνει (π.χ. Σάββατο όταν
            // η εβδομάδα έγινε 5 ημερών, ώρα που έγινε διάλειμμα): ξαναστέλνονται
            // ως έχουν στην αποθήκευση, αλλιώς ο server (που αντικαθιστά όλα) τα έσβηνε.
            const shownPeriodIds = new Set(teachingPeriods.map(p => p.id));
            const knownPeriodIds = new Set(periods.map(p => p.id));
            const hiddenRows = (availabilities || []).filter(a =>
                knownPeriodIds.has(a.period_id)
                && (a.day_of_week >= daysCount || !shownPeriodIds.has(a.period_id)));

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
                ${hiddenRows.length ? `
                <p class="text-muted" id="avail-hidden-note" style="margin-top: 0.5rem; font-size: 0.85rem;">
                    Διατηρούνται ${hiddenRows.length} κωλύματα σε ημέρες/ώρες που δεν εμφανίζονται.
                </p>` : ''}
            `;

            if (!stillMine()) return;
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
                    // Όσα δεν φαίνονται στο πλέγμα: πίσω όπως ήταν (δεν συμπίπτουν με κελιά).
                    hiddenRows.forEach(a => {
                        payload.availabilities.push({
                            day_of_week: a.day_of_week,
                            period_id: a.period_id,
                            status: a.status
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
                    Toast.error('Αποτυχία: ' + DataTable.esc(err.message));
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
                    // Τα κελιά δεν είναι πεδία φόρμας: ενημέρωσε το Modal ότι υπάρχουν
                    // αλλαγές, ώστε πάτημα έξω / Esc / «Πίσω» να ρωτούν πριν κλείσουν.
                    td.dispatchEvent(new Event('change', { bubbles: true }));
                });
            });

        } catch(err) {
            console.error(err);
            if (!stillMine()) return;
            Modal.open(title, `<div class="alert alert-error">Σφάλμα: ${DataTable.esc(err.message)}</div>`,
                null, { hideFooter: true });
        }
    }
};
