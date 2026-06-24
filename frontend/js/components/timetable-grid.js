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
                    } else if (viewType === 'student') {
                        // Student: priority is subject + which class
                        // it's with + which room. Teacher takes a back
                        // seat since a student usually knows them from
                        // the class.
                        line1 = slot.subject_short || slot.subject_name;
                        line2 = slot.class_short || slot.class_name;
                        line3 = slot.classroom_name;
                    } else {
                        line1 = slot.subject_short || slot.subject_name;
                        line2 = slot.class_short || slot.class_name;
                        line3 = slot.teacher_short;
                    }

                    const lockBorder = slot.is_locked
                        ? `box-shadow: inset 0 0 0 2px ${bgColor};`
                        : '';
                    const lockIcon = slot.is_locked ? '🔒' : '🔓';
                    const lockTitle = slot.is_locked
                        ? 'Κλικ για ξεκλείδωμα'
                        : 'Κλικ για κλείδωμα — θα διατηρηθεί στο επόμενο regenerate';

                    return `
                        <div class="lesson-card ${slot.is_locked ? 'locked' : ''}"
                             data-slot-id="${slot.id}"
                             draggable="${slot.is_locked ? 'false' : 'true'}"
                             ondragstart="TimetableGrid.handleDragStart(event, ${slot.id})"
                             ondragend="TimetableGrid.handleDragEnd(event)"
                             onclick="TimetableGrid.showDetails(this)"
                             data-json='${JSON.stringify(slot).replace(/'/g, "&#39;")}'
                             style="background:${bgLight}; color:${textColor}; cursor: grab; margin-bottom: 4px; position: relative; padding-right: 32px; ${lockBorder}"
                             title="Κλικ για Πληροφορίες">
                            <button class="lesson-lock-btn"
                                    data-slot-id="${slot.id}"
                                    onmousedown="event.stopPropagation();"
                                    ondragstart="event.stopPropagation(); event.preventDefault();"
                                    onclick="event.stopPropagation(); TimetableGrid.toggleLock(${slot.id}, ${solutionId})"
                                    title="${lockTitle}">
                                ${lockIcon}
                            </button>
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

        // Compact mode = "Προβολή Όλων". Τότε κάθε cell μπορεί να έχει
        // 5+ cards (όλες τις τάξεις/καθηγητές/αίθουσες ταυτόχρονα), και
        // το full-size card layout στοιβάζει όλα κάθετα — τα κουτάκια
        // μεγαλώνουν, η οθόνη γίνεται unreadable. Με την class
        // `compact-grid` το CSS μικραίνει padding/font-size και αφήνει
        // τα cards να πέφτουν δίπλα-δίπλα μέσω flex-wrap.
        const isCompact = !filterValue || filterValue === 'all';
        const tableClass = isCompact
            ? 'timetable-grid compact-grid'
            : 'timetable-grid';

        container.innerHTML = `
            <div class="timetable-grid-container">
                <style>
                    .droppable-cell.drag-over { background: var(--surface-hover); border: 2px dashed var(--primary); }
                    .lesson-card.dragging { opacity: 0.4; transform: scale(0.95); }
                </style>
                <table class="${tableClass}" style="min-width: 800px;">
                    <thead><tr><th>Ώρα</th>${dayHeaders}</tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    },

    /**
     * Overview / "Συνολική προβολή" — a whole-week bird's-eye snapshot:
     *   rows  = teachers (axis='teacher') OR classes (axis='class')
     *   cols  = ALL days × teaching periods (Δευτέρα 1..N, Τρίτη 1..N, …)
     *   cell  = what that teacher/class has that day+hour
     *
     * The first column (entity names) is FROZEN: it stays put during
     * horizontal scroll (position:sticky left). The day/hour headers stay
     * put during vertical scroll (position:sticky top). Read-only — cards
     * are clickable for details, not draggable.
     */
    renderOverview(containerId, slots, periods, daysCount = 5, axis = 'teacher', solutionId = null) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const SEP = '\x1f'; // unit separator — safe composite-key delimiter
        const esc = (s) => String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        // JSON embedded in a single-quoted attribute: escape & and < (which the
        // HTML parser would otherwise decode on read-back) plus the quote.
        const attrJson = (o) => JSON.stringify(o)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/'/g, '&#39;');
        const teachingPeriods = periods.filter(p => !p.is_break);
        const days = this.DAY_NAMES.slice(0, daysCount);
        const placed = slots.filter(s => !s.is_unplaced);

        const rowKeyOf = (s) => axis === 'teacher'
            ? (s.teacher_name || s.teacher_short || '—')
            : (s.class_name || s.class_short || '—');

        // Row entities from ALL placed slots so every teacher/class shows up
        // even on days/hours where it has nothing.
        const rowLabels = [...new Set(placed.map(rowKeyOf))]
            .sort((a, b) => a.localeCompare(b, 'el'));

        // lookup[rowLabel SEP day SEP periodId] -> slots
        const lookup = {};
        for (const s of placed) {
            const key = rowKeyOf(s) + SEP + s.day_of_week + SEP + s.period_id;
            if (!lookup[key]) lookup[key] = [];
            lookup[key].push(s);
        }

        const axisLabel = axis === 'teacher' ? 'Καθηγητής' : 'Τμήμα';
        const nHours = teachingPeriods.length;

        // Header row 1: a frozen corner + one day label spanning its hours.
        const dayHeader = days.map(d =>
            `<th class="ov-day" scope="colgroup" colspan="${nHours}">${esc(d)}</th>`).join('');

        // Header row 2: the hour labels, repeated per day.
        const hourHeader = days.map(() =>
            teachingPeriods.map((p, pi) =>
                `<th class="ov-hour${pi === 0 ? ' ov-day-start' : ''}" scope="col" title="${esc(p.start_time)}-${esc(p.end_time)}">${esc(p.short_name)}</th>`
            ).join('')
        ).join('');

        const rows = rowLabels.map(rk => {
            const cells = days.map((_, dayIdx) =>
                teachingPeriods.map((p, pi) => {
                    const here = lookup[rk + SEP + dayIdx + SEP + p.id] || [];
                    const cards = here.map(slot => {
                        const bg = slot.subject_color || '#3B82F6';
                        const bgLight = this._hexToRgba(bg, 0.18);
                        const line1 = slot.subject_short || slot.subject_name || '';
                        const line2 = axis === 'teacher'
                            ? (slot.class_short || slot.class_name || '')
                            : (slot.teacher_short || slot.teacher_name || '');
                        return `<div class="ov-card"
                                     onclick="TimetableGrid.showDetails(this)"
                                     data-json='${attrJson(slot)}'
                                     style="background:${bgLight};"
                                     title="Κλικ για Πληροφορίες">
                                    <span class="l1" style="color:${bg}">${esc(line1)}</span>
                                    <span class="l2">${esc(line2)}</span>
                                </div>`;
                    }).join('');
                    return `<td class="ov-cell${pi === 0 ? ' ov-day-start' : ''}">${cards}</td>`;
                }).join('')
            ).join('');
            return `<tr><th class="ov-firstcol" scope="row" title="${esc(rk)}">${esc(rk)}</th>${cells}</tr>`;
        }).join('');

        const emptyNote = rowLabels.length
            ? ''
            : `<p class="empty-state-text" style="padding:1rem">Δεν υπάρχουν τοποθετημένα μαθήματα.</p>`;

        container.innerHTML = `
            <div class="ov-wrap">
                <style>
                    .ov-wrap { overflow: auto; max-height: 78vh; border: 1px solid var(--border-default, rgba(148,163,184,0.2)); border-radius: var(--radius-md, 10px); }
                    .ov-table { border-collapse: separate; border-spacing: 0; width: max-content; font-size: 0.72rem; color: var(--text-primary, #F1F5F9); }
                    .ov-table th, .ov-table td { border-right: 1px solid var(--border-default, rgba(148,163,184,0.2)); border-bottom: 1px solid var(--border-default, rgba(148,163,184,0.2)); padding: 2px 5px; text-align: center; vertical-align: top; white-space: nowrap; }
                    .ov-table thead th { position: sticky; z-index: 2; background: var(--surface-2, #334155); color: var(--text-primary, #F1F5F9); }
                    .ov-table thead tr.ov-days th { top: 0; }
                    .ov-table thead tr.ov-hours th { top: var(--ov-h1, 24px); }
                    .ov-table .ov-day { font-weight: 700; }
                    .ov-table .ov-hour { font-weight: 600; color: var(--text-secondary, #94A3B8); min-width: 56px; }
                    .ov-table .ov-day-start { border-left: 2px solid var(--border-strong, rgba(148,163,184,0.35)); }
                    .ov-table th.ov-firstcol, .ov-table td.ov-firstcol { position: sticky; left: 0; z-index: 1; background: var(--surface-1, #1E293B); color: var(--text-primary, #F1F5F9); font-weight: 600; text-align: left; border-right: 2px solid var(--border-strong, rgba(148,163,184,0.35)); max-width: 170px; overflow: hidden; text-overflow: ellipsis; }
                    .ov-table thead .ov-corner { position: sticky; left: 0; top: 0; z-index: 5; background: var(--surface-2, #334155); color: var(--text-primary, #F1F5F9); text-align: left; border-right: 2px solid var(--border-strong, rgba(148,163,184,0.35)); max-width: 170px; overflow: hidden; text-overflow: ellipsis; }
                    .ov-table td.ov-cell { min-width: 56px; }
                    .ov-card { border-radius: 3px; padding: 1px 4px; margin-bottom: 2px; line-height: 1.18; cursor: pointer; text-align: left; }
                    .ov-card .l1 { font-weight: 700; display: block; }
                    .ov-card .l2 { display: block; opacity: .85; color: var(--text-secondary, #94A3B8); }
                    @media print {
                        .ov-wrap { overflow: visible !important; max-height: none !important; border: none; }
                        .ov-table { width: 100% !important; color: #000; }
                        .ov-table thead th, .ov-table th.ov-firstcol, .ov-table td.ov-firstcol, .ov-table .ov-corner { position: static !important; color: #000 !important; background: #fff !important; }
                        .ov-table th, .ov-table td { border-color: #999 !important; }
                        .ov-card .l2 { color: #333 !important; }
                        .ov-table tr { page-break-inside: avoid; }
                    }
                </style>
                <table class="ov-table">
                    <thead>
                        <tr class="ov-days"><th class="ov-corner" rowspan="2">${esc(axisLabel)}</th>${dayHeader}</tr>
                        <tr class="ov-hours">${hourHeader}</tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
                ${emptyNote}
            </div>
        `;

        // Pin the 2nd header row exactly below the 1st (drift-proof vs the
        // fragile hardcoded offset): measure the rendered day-row height.
        const wrap = container.querySelector('.ov-wrap');
        const daysRow = container.querySelector('thead tr.ov-days');
        if (wrap && daysRow && daysRow.offsetHeight) {
            wrap.style.setProperty('--ov-h1', daysRow.offsetHeight + 'px');
        }
    },

    showDetails(el) {
        let slot;
        try {
            slot = JSON.parse(el.dataset.json);
        } catch (err) {
            Toast.error('Δεν διαβάστηκαν τα στοιχεία του μαθήματος');
            return;
        }
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

    /**
     * Drag-drop handler with optimistic UI update.
     *
     * Old behavior: every drop triggered App.navigateTo('timetable')
     * which fully re-rendered the view — clobbering the user's
     * filter/view-type selects and forcing them back to defaults
     * ("ανά τάξη / Προβολή Όλων"). Mid-edit, that's deeply annoying.
     *
     * New behavior: move the card in the DOM immediately, fire the
     * API call, and only roll back if the call fails. The user's
     * filter selects, scroll position, and modal state stay intact.
     *
     * Two source cases:
     *   (a) Card lives in a grid cell      → simple appendChild
     *   (b) Card lives in the parking lot  → also appendChild, plus
     *       strip the parking-card class and let the parent view know
     *       the lot count changed (header label refresh).
     */
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

        const sourceCard = document.querySelector(
            `.lesson-card[data-slot-id="${slotId}"]`
        );
        if (!sourceCard) {
            Toast.error('Δεν βρέθηκε το card στο DOM');
            return;
        }

        // Don't drop a card on the same cell it was already in
        if (sourceCard.parentElement === target) return;

        const originalParent = sourceCard.parentElement;
        const originalNextSibling = sourceCard.nextSibling;
        const wasParkingCard = sourceCard.classList.contains('parking-card');

        let slotData;
        try {
            slotData = JSON.parse(sourceCard.dataset.json);
        } catch (e) {
            Toast.error('Σφάλμα ανάγνωσης δεδομένων card');
            return;
        }
        const prev = {
            day_of_week: slotData.day_of_week,
            period_id: slotData.period_id,
            is_unplaced: slotData.is_unplaced,
        };

        // 1) Optimistic move
        target.appendChild(sourceCard);
        slotData.day_of_week = newDay;
        slotData.period_id = newPeriod;
        if (wasParkingCard) {
            slotData.is_unplaced = false;
            sourceCard.classList.remove('parking-card');
            // The parking-lot inline styling (border-left, padding, background)
            // came from _renderParkingLot. Reset to grid-card defaults so it
            // visually matches its new neighbours.
            sourceCard.style.borderLeft = '';
            sourceCard.style.padding = '';
            sourceCard.style.borderRadius = '';
        }
        sourceCard.dataset.json = JSON.stringify(slotData).replace(/'/g, '&#39;');

        // 2) API call
        try {
            await API.solver.updateSlot(solutionId, slotId, {
                day_of_week: newDay,
                period_id: newPeriod,
            });
            Toast.success('Η κάρτα μετακινήθηκε επιτυχώς!');
            if (wasParkingCard) {
                this._notifyParkingLotChanged();
            }
        } catch (err) {
            // 3) Rollback the optimistic move
            if (originalNextSibling) {
                originalParent.insertBefore(sourceCard, originalNextSibling);
            } else {
                originalParent.appendChild(sourceCard);
            }
            slotData.day_of_week = prev.day_of_week;
            slotData.period_id = prev.period_id;
            slotData.is_unplaced = prev.is_unplaced;
            if (wasParkingCard) {
                sourceCard.classList.add('parking-card');
            }
            sourceCard.dataset.json = JSON.stringify(slotData).replace(/'/g, '&#39;');
            Toast.error('Αποτυχία: ' + err.message);
        }
    },

    /**
     * Update the parking-lot header label after a card leaves it.
     * Touches only the count text — leaves filter selects, scroll
     * position, and other view state intact.
     */
    _notifyParkingLotChanged() {
        const lot = document.querySelector('.parking-lot');
        if (!lot) return;
        const remaining = lot.querySelectorAll('.parking-card').length;
        const title = lot.querySelector('.card-title');
        if (remaining === 0) {
            // Whole lot is empty — hide the panel
            lot.style.display = 'none';
            return;
        }
        if (title) {
            title.textContent = `🅿️ Parking Lot — ${remaining} ${
                remaining === 1 ? 'ώρα δεν τοποθετήθηκε' : 'ώρες δεν τοποθετήθηκαν'
            }`;
        }
    },

    _hexToRgba(hex, alpha) {
        if (!hex) return `rgba(59, 130, 246, ${alpha})`;
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    },

    /**
     * Toggle the is_locked flag on a single slot.
     *
     * Optimistic UI: flip icon/state in the DOM immediately, then fire
     * the API call in the background. If the call fails we roll the
     * card back. No full view re-render — that's what was making
     * second/third clicks feel unresponsive (every click triggered a
     * full re-fetch of solutions/getSolution which clobbered any
     * in-flight click).
     *
     * The button is also disabled while the request is in flight so
     * double-clicks don't queue two opposite ops.
     */
    async toggleLock(slotId, solutionId) {
        const card = document.querySelector(
            `.lesson-card[data-slot-id="${slotId}"]`
        );
        const btn = card?.querySelector(
            `.lesson-lock-btn[data-slot-id="${slotId}"]`
        );
        if (!card || !btn) {
            Toast.error('Δεν βρέθηκε το slot στο DOM');
            return;
        }
        if (btn.disabled) return;  // already in flight

        // Read current state from the DOM (single source of truth here)
        let slot;
        try {
            slot = JSON.parse(card.dataset.json);
        } catch (err) {
            Toast.error('Δεν διαβάστηκαν τα στοιχεία του slot');
            return;
        }
        const newLockedValue = !slot.is_locked;

        // 1) Optimistic flip
        btn.disabled = true;
        btn.classList.add('busy');
        btn.textContent = newLockedValue ? '🔒' : '🔓';
        btn.title = newLockedValue
            ? 'Κλικ για ξεκλείδωμα'
            : 'Κλικ για κλείδωμα — θα διατηρηθεί στο επόμενο regenerate';
        card.classList.toggle('locked', newLockedValue);
        card.draggable = !newLockedValue;
        slot.is_locked = newLockedValue;
        card.dataset.json = JSON.stringify(slot).replace(/'/g, '&#39;');

        // 2) Fire-and-await API
        try {
            await API.solver.updateSlot(solutionId, slotId, {
                day_of_week: slot.day_of_week,
                period_id: slot.period_id,
                classroom_id: slot.classroom_id,
                is_locked: newLockedValue,
            });
            Toast.success(newLockedValue ? '🔒 Κλειδώθηκε' : '🔓 Ξεκλειδώθηκε');
        } catch (err) {
            // 3) Rollback the optimistic flip
            btn.textContent = newLockedValue ? '🔓' : '🔒';
            card.classList.toggle('locked', !newLockedValue);
            card.draggable = newLockedValue;
            slot.is_locked = !newLockedValue;
            card.dataset.json = JSON.stringify(slot).replace(/'/g, '&#39;');
            Toast.error(`Lock toggle απέτυχε: ${err.message}`);
        } finally {
            btn.disabled = false;
            btn.classList.remove('busy');
        }
    },
};
