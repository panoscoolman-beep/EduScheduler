/**
 * Timetable Grid Component — Renders weekly schedule grid.
 */
const TimetableGrid = {
    DAY_NAMES: ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'],

    render(containerId, slots, periods, daysCount = 5, viewType = 'class', filterValue = null) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const teachingPeriods = periods.filter(p => !p.is_break);
        const days = this.DAY_NAMES.slice(0, daysCount);

        // Build grid lookup: [dayIndex][periodId] -> slot data
        const grid = {};
        const filteredSlots = filterValue
            ? slots.filter(s => {
                if (viewType === 'class') return s.class_short === filterValue || s.class_name === filterValue;
                if (viewType === 'teacher') return s.teacher_short === filterValue || s.teacher_name === filterValue;
                if (viewType === 'room') return s.classroom_name === filterValue;
                return true;
            })
            : slots;

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

                if (slotsHere.length === 0) {
                    return '<td></td>';
                }

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
                             style="background:${bgLight}; color:${textColor};"
                             title="${slot.subject_name} — ${slot.teacher_name} — ${slot.classroom_name}">
                            <span class="subject-name" style="color:${bgColor}">${line1 || ''}</span>
                            <span class="teacher-name">${line2 || ''}</span>
                            <span class="room-name">${line3 || ''}</span>
                        </div>
                    `;
                }).join('');

                return `<td>${cards}</td>`;
            }).join('');

            return `<tr>${periodCell}${dayCells}</tr>`;
        }).join('');

        container.innerHTML = `
            <div class="timetable-grid-container">
                <table class="timetable-grid">
                    <thead><tr><th>Ώρα</th>${dayHeaders}</tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    },

    _hexToRgba(hex, alpha) {
        if (!hex) return `rgba(59, 130, 246, ${alpha})`;
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    },
};
