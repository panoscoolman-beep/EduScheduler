/**
 * Timetable Grid Component — Renders weekly schedule grid.
 */
const TimetableGrid = {
    DAY_NAMES: ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'],

    render(containerId, slots, periods, daysCount = 5, viewType = 'class', filterValue = null, solutionId = null) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const teachingPeriods = periods.filter(p => !p.is_break);
        const days = this.DAY_NAMES.slice(0, daysCount);

        // Build grid lookup: [dayIndex][periodId] -> slot data.
        // Parking-lot rows (is_unplaced=true, day_of_week=null) are
        // rendered separately by the timetable view, never on the grid.
        const grid = {};
        const placedSlots = slots.filter(s => !s.is_unplaced);
        const filteredSlots = (filterValue && filterValue !== 'all')
            ? placedSlots.filter(s => {
                if (viewType === 'class') return s.class_short === filterValue || s.class_name === filterValue;
                if (viewType === 'teacher') return s.teacher_short === filterValue || s.teacher_name === filterValue;
                if (viewType === 'room') return s.classroom_name === filterValue;
                return true;
            })
            : placedSlots;

        for (const slot of filteredSlots) {
            const key = `${slot.day_of_week}_${slot.period_id}`;
            if (!grid[key]) grid[key] = [];
            grid[key].push(slot);
        }

        // Build header
        const dayHeaders = days.map(d => `<th>${d}</th>`).join('');

        // Build rows
        const rows = teachingPeriods.map(period => {
            const periodCell = `
                <td class="period-cell">
                    ${period.short_name}
                    <span class="period-time">${period.start_time}-${period.end_time}</span>
                </td>
            `;

            const dayCells = days.map((_, dayIdx) => {
                const key = `${dayIdx}_${period.id}`;
                const slotsHere = grid[key] || [];

                const cards = slotsHere.map(slot => {
                    const bgColor = slot.subject_color || '#3B82F6';
                    const bgLight = this._hexToRgba(bgColor, 0.15);
                    const textColor = this._hexToRgba(bgColor, 0.9);

                    let line1, line2, line3;
                    if (viewType === 'class') {
                        line1 = slot.subject_short || slot.subject_name;
                        line2 = slot.teacher_short || slot.teacher_name;
                        line3 = slot.classroom_name;
                    } else if (viewType === 'teacher') {
                        line1 = slot.subject_short || slot.subject_name;
                        line2 = slot.class_short || slot.class_name;
                        line3 = slot.classroom_name;
                    } else {
                        line1 = slot.subject_short || slot.subject_name;
                        line2 = slot.class_short || slot.class_name;
                        line3 = slot.teacher_short;
                    }

                    return `
                        <div class="lesson-card"
                             draggable="true" 
                             ondragstart="TimetableGrid.handleDragStart(event, ${slot.id})"
                             ondragend="TimetableGrid.handleDragEnd(event)"
                             onclick="TimetableGrid.showDetails(this)"
                             data-json='${JSON.stringify(slot).replace(/'/g, "&#39;")}'
                             style="background:${bgLight}; color:${textColor}; cursor: grab; margin-bottom: 4px;"
                             title="Κλικ για Πληροφορίες">
                            <span class="subject-name" style="color:${bgColor}">${line1 || ''}</span>
                            <span class="teacher-name">${line2 || ''}</span>
                            <span class="room-name">${line3 || ''}</span>
                        </div>
                    `;
                }).join('');

                return `<td class="droppable-cell" 
                            data-day="${dayIdx}" 
                            data-period="${period.id}"
                            ondragover="TimetableGrid.handleDragOver(event)"
                            ondragenter="TimetableGrid.handleDragEnter(event)"
                            ondragleave="TimetableGrid.handleDragLeave(event)"
                            ondrop="TimetableGrid.handleDrop(event, ${solutionId})">
                            ${cards}
                        </td>`;
            }).join('');

            return `<tr>${periodCell}${dayCells}</tr>`;
        }).join('');

        container.innerHTML = `
            <div class="timetable-grid-container">
                <style>
                    .droppable-cell.drag-over { background: var(--surface-hover); border: 2px dashed var(--primary); }
                    .lesson-card.dragging { opacity: 0.4; transform: scale(0.95); }
                </style>
                <table class="timetable-grid" style="min-width: 800px;">
                    <thead><tr><th>Ώρα</th>${dayHeaders}</tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    },

    showDetails(el) {
        const slot = JSON.parse(el.dataset.json);
        const days = ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'];
        const content = `
            <div style="font-size:1.1rem; padding-bottom: 1rem;">
                <p style="margin-bottom:0.5rem">📚 <strong>Μάθημα:</strong> ${slot.subject_name || slot.subject_short || '-'}</p>
                <p style="margin-bottom:0.5rem">👨‍🏫 <strong>Καθηγητής:</strong> ${slot.teacher_name || slot.teacher_short || '-'}</p>
                <p style="margin-bottom:0.5rem">🎓 <strong>Τάξη:</strong> ${slot.class_name || slot.class_short || '-'}</p>
                <p style="margin-bottom:0.5rem">🏫 <strong>Αίθουσα:</strong> ${slot.classroom_name || '-'}</p>
                <p style="margin-bottom:0.5rem">📅 <strong>Ημέρα:</strong> ${days[slot.day_of_week]}</p>
            </div>
        `;
        Modal.open("Πληροφορίες Μαθήματος", content, () => Modal.close(), { saveText: "Κλείσιμο", saveClass: "btn-secondary" });
    },

    handleDragStart(event, slotId) {
        event.dataTransfer.setData('text/plain', slotId);
        event.dataTransfer.effectAllowed = 'move';
        event.target.classList.add('dragging');
    },

    handleDragEnd(event) {
        event.target.classList.remove('dragging');
        document.querySelectorAll('.droppable-cell').forEach(c => c.classList.remove('drag-over'));
    },

    handleDragOver(event) {
        event.preventDefault(); 
        event.dataTransfer.dropEffect = 'move';
    },

    handleDragEnter(event) {
        event.preventDefault();
        let target = event.target;
        while (target && !target.classList.contains('droppable-cell')) target = target.parentElement;
        if (target) target.classList.add('drag-over');
    },

    handleDragLeave(event) {
        let target = event.target;
        while (target && !target.classList.contains('droppable-cell')) target = target.parentElement;
        if (target) target.classList.remove('drag-over');
    },

    async handleDrop(event, solutionId) {
        event.preventDefault();
        const slotIdStr = event.dataTransfer.getData('text/plain');
        if (!slotIdStr || !solutionId) return;

        const slotId = parseInt(slotIdStr);
        let target = event.target;
        while (target && !target.classList.contains('droppable-cell')) {
            target = target.parentElement;
        }
        
        if (target) target.classList.remove('drag-over');
        if (!target) return;

        const newDay = parseInt(target.dataset.day);
        const newPeriod = parseInt(target.dataset.period);

        try {
            await API.solver.updateSlot(solutionId, slotId, {
                day_of_week: newDay,
                period_id: newPeriod
            });
            Toast.success('Η κάρτα μετακινήθηκε επιτυχώς!');
            // Re-render the timetable by invoking the app router
            App.navigateTo('timetable'); 
        } catch (err) {
            Toast.error('Αποτυχία: ' + err.message);
        }
    },

    _hexToRgba(hex, alpha) {
        if (!hex) return `rgba(59, 130, 246, ${alpha})`;
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    },
};
