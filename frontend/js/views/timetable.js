/**
 * Timetable View — Visual grid of generated schedule.
 */
const TimetableView = {
    async render(container) {
        container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>`;

        try {
            const solutions = await API.solver.listSolutions();
            const periods = await API.periods.list();

            if (!solutions.length) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📋</div>
                        <p class="empty-state-text">Δεν έχει δημιουργηθεί πρόγραμμα ακόμα</p>
                        <button class="btn btn-primary" id="go-generate">🧠 Δημιουργία Τώρα</button>
                    </div>
                `;
                container.querySelector('#go-generate')?.addEventListener('click', () => App.navigateTo('generate'));
                return;
            }

            // Pick solution (latest or specified)
            const solutionId = App._currentSolutionId || solutions[0].id;
            const solution = await API.solver.getSolution(solutionId);

            // Extract unique values for filters
            const classNames = [...new Set(solution.slots.map(s => s.class_name).filter(Boolean))];
            const teacherNames = [...new Set(solution.slots.map(s => s.teacher_name).filter(Boolean))];
            const roomNames = [...new Set(solution.slots.map(s => s.classroom_name).filter(Boolean))];

            container.innerHTML = `
                <div class="card mb-lg">
                    <img src="img/logo.svg" class="print-logo" style="display:none;" />
                    <div class="card-header print-hide">
                        <h2 class="card-title">📋 ${solution.name}</h2>
                        <div>
                            <button class="btn btn-warning" id="tt-regen" title="Κράτα τα κλειδωμένα μαθήματα και ξανατρέξε τον solver για τα υπόλοιπα" style="margin-right:0.5rem">🔒 Lock & Regenerate</button>
                            <button class="btn btn-secondary" id="tt-print" title="Εκτύπωση Προγράμματος" style="margin-right:0.5rem">🖨️ Εκτύπωση</button>
                            <span class="constraint-badge ${solution.status === 'optimal' ? 'soft' : 'hard'}">
                                ${solution.status === 'optimal' ? 'Βέλτιστο' : solution.status}
                            </span>
                        </div>
                    </div>

                    <div class="timetable-controls">
                        <div class="form-group" style="margin:0; min-width: 150px;">
                            <label class="form-label">Προβολή ανά</label>
                            <select class="form-select" id="tt-view-type">
                                <option value="class">Τάξη</option>
                                <option value="teacher">Καθηγητή</option>
                                <option value="room">Αίθουσα</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin:0; min-width: 200px;">
                            <label class="form-label">Φίλτρο</label>
                            <select class="form-select" id="tt-filter">
                                <option value="all">-- Προβολή Όλων --</option>
                                ${classNames.map(n => `<option value="${n}">${n}</option>`).join('')}
                            </select>
                        </div>
                        <div class="form-group" style="margin:0; min-width: 150px;">
                            <label class="form-label">Πρόγραμμα</label>
                            <select class="form-select" id="tt-solution">
                                ${solutions.map(s => `<option value="${s.id}" ${s.id === solutionId ? 'selected' : ''}>${s.name}</option>`).join('')}
                            </select>
                        </div>
                    </div>

                    <div id="timetable-grid-view"></div>
                </div>

                <div id="parking-lot-container"></div>
            `;

            // Initial render
            const firstFilter = 'all';
            TimetableGrid.render('timetable-grid-view', solution.slots, periods, 5, 'class', firstFilter, solutionId);
            this._renderParkingLot('parking-lot-container', solution.slots, solutionId);

            // Event: Print
            document.getElementById('tt-print').addEventListener('click', () => {
                window.print();
            });

            // Event: Lock & Regenerate
            document.getElementById('tt-regen').addEventListener('click', async () => {
                const lockedCount = solution.slots.filter(s => s.is_locked && !s.is_unplaced).length;
                if (lockedCount === 0) {
                    Toast.error('Δεν έχει κλειδωθεί κανένα μάθημα. Πάτησε το 🔒 σε όσα θες να διατηρήσεις πρώτα.');
                    return;
                }

                const newName = prompt(
                    `Νέα έκδοση προγράμματος βασισμένη σε ${lockedCount} κλειδωμένα μαθήματα.\n` +
                    'Δώσε όνομα για τη νέα λύση:',
                    `${solution.name} v2`
                );
                if (!newName) return;

                const mode = confirm(
                    'Θες strict mode; (OK = strict, Cancel = permissive — βάζει ό,τι μπορεί + parking lot)'
                ) ? 'strict' : 'permissive';

                Toast.success('🧠 Solver εργάζεται…');
                try {
                    const result = await API.solver.regenerateWithLocks(solutionId, {
                        name: newName,
                        max_time_seconds: 120,
                        mode,
                    });
                    if (result.status === 'optimal' || result.status === 'feasible') {
                        Toast.success(
                            `✅ ${result.message} ` +
                            `(${result.placed_count} placed, ${result.unplaced_count} στο parking)`
                        );
                        App._currentSolutionId = result.solution_id;
                        await this.render(container);
                    } else {
                        Toast.error(result.message);
                    }
                } catch (err) {
                    Toast.error(`Regenerate απέτυχε: ${err.message}`);
                }
            });

            // Event: View type change
            document.getElementById('tt-view-type').addEventListener('change', (e) => {
                const filterSelect = document.getElementById('tt-filter');
                let options = [];
                if (e.target.value === 'class') options = classNames;
                else if (e.target.value === 'teacher') options = teacherNames;
                else options = roomNames;

                filterSelect.innerHTML = `<option value="all">-- Προβολή Όλων --</option>` + 
                                         options.map(n => `<option value="${n}">${n}</option>`).join('');
                TimetableGrid.render('timetable-grid-view', solution.slots, periods, 5, e.target.value, 'all', solutionId);
            });

            // Event: Filter change
            document.getElementById('tt-filter').addEventListener('change', (e) => {
                const viewType = document.getElementById('tt-view-type').value;
                TimetableGrid.render('timetable-grid-view', solution.slots, periods, 5, viewType, e.target.value, solutionId);
            });

            // Event: Solution change
            document.getElementById('tt-solution').addEventListener('change', async (e) => {
                App._currentSolutionId = parseInt(e.target.value);
                await this.render(container);
            });

        } catch (err) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <p class="empty-state-text">Σφάλμα: ${err.message}</p>
                </div>
            `;
        }
    },

    /**
     * Render the parking-lot panel below the grid. Lists every slot with
     * is_unplaced=true. Each card is draggable into any grid cell — the
     * drop handler in TimetableGrid will flip is_unplaced to false on
     * the backend and re-render.
     */
    _renderParkingLot(containerId, allSlots, solutionId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const unplaced = allSlots.filter(s => s.is_unplaced);
        if (unplaced.length === 0) {
            container.innerHTML = '';
            return;
        }

        const cards = unplaced.map(slot => {
            const bgColor = slot.subject_color || '#9CA3AF';
            const bgLight = this._hexToRgba(bgColor, 0.15);
            const reasonText = slot.unplaced_reason
                ? ` <span class="text-muted" style="font-size:0.8em">— ${slot.unplaced_reason}</span>`
                : '';
            return `
                <div class="lesson-card parking-card"
                     draggable="true"
                     ondragstart="TimetableGrid.handleDragStart(event, ${slot.id})"
                     ondragend="TimetableGrid.handleDragEnd(event)"
                     onclick="TimetableGrid.showDetails(this)"
                     data-json='${JSON.stringify(slot).replace(/'/g, "&#39;")}'
                     style="background:${bgLight}; cursor: grab; padding: 10px 14px;
                            border-left: 4px solid ${bgColor}; margin-bottom: 6px;
                            border-radius: 6px;"
                     title="Σύρε στο πρόγραμμα για να τοποθετηθεί">
                    <div style="font-weight: 600; color: ${bgColor};">
                        ${slot.subject_name || slot.subject_short || '?'}
                    </div>
                    <div style="font-size: 0.9em; color: var(--text-muted);">
                        ${slot.class_name || slot.class_short || ''}
                        ${slot.teacher_name ? ' • ' + slot.teacher_name : ''}
                    </div>
                    ${reasonText ? `<div style="font-size:0.8em; color:var(--text-muted); margin-top:4px;">${slot.unplaced_reason || ''}</div>` : ''}
                </div>
            `;
        }).join('');

        container.innerHTML = `
            <div class="card mt-lg parking-lot" style="border-left: 4px solid var(--warning, #F59E0B);">
                <div class="card-header">
                    <h2 class="card-title">🅿️ Parking Lot — ${unplaced.length}
                        ${unplaced.length === 1 ? 'ώρα δεν τοποθετήθηκε' : 'ώρες δεν τοποθετήθηκαν'}
                    </h2>
                </div>
                <p class="text-muted" style="margin-bottom: 1rem;">
                    Σύρε ένα μάθημα στο πρόγραμμα για να το τοποθετήσεις χειροκίνητα.
                    Οι περιορισμοί επικυρώνονται κατά το drop — αν συγκρούεται με κάτι, θα δεις σφάλμα.
                </p>
                ${cards}
            </div>
        `;
    },

    _hexToRgba(hex, alpha = 1) {
        const r = parseInt(hex.slice(1, 3), 16);
        const g = parseInt(hex.slice(3, 5), 16);
        const b = parseInt(hex.slice(5, 7), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    },
};
