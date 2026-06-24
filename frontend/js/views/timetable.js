/**
 * Timetable View — Visual grid of generated schedule.
 */
const TimetableView = {
    async render(container) {
        container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>`;

        try {
            const [solutions, periods, settings] = await Promise.all([
                API.solver.listSolutions(),
                API.periods.list(),
                API.settings.get(),
            ]);
            // Honour school_settings.days_per_week — until now this was
            // hardcoded to 5, hiding any slots placed on Σάβ/Κυρ.
            const daysCount = settings.days_per_week || 5;

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
            const [solution, students] = await Promise.all([
                API.solver.getSolution(solutionId),
                API.students.list().catch(() => []),
            ]);

            // Extract unique values for filters
            const classNames = TimetableHelpers.uniqueValues(solution.slots, 'class_name');
            const teacherNames = TimetableHelpers.uniqueValues(solution.slots, 'teacher_name');
            const roomNames = TimetableHelpers.uniqueValues(solution.slots, 'classroom_name');

            // Student dropdown shows "Last First" labels. Each label maps
            // to the set of class_ids the student is enrolled in, so the
            // grid can filter slots whose lesson belongs to those classes.
            const {
                classIdsByLabel: studentByLabel,
                idByLabel: studentIdByLabel,
                sortedNames: studentNames,
            } = TimetableHelpers.buildStudentLabelMaps(students);
            // teacher_name → teacher_id, for the per-teacher export buttons
            const teacherIdByName = TimetableHelpers.teacherIdByName(solution.slots);

            container.innerHTML = `
                <div class="card mb-lg">
                    <img src="img/logo.svg" class="print-logo" style="display:none;" />
                    <div class="card-header print-hide">
                        <h2 class="card-title">📋 ${solution.name}</h2>
                        <div>
                            <button class="btn btn-secondary" id="tt-undo" title="Αναίρεση τελευταίας αλλαγής (Ctrl+Z)" style="margin-right:0.25rem" disabled>↩ Αναίρεση</button>
                            <button class="btn btn-secondary" id="tt-redo" title="Επανάληψη (Ctrl+Y)" style="margin-right:0.5rem" disabled>↪ Επανάληψη</button>
                            <button class="btn btn-secondary" id="tt-substitute" title="Βρες αντικαταστάτη για καθηγητή που λείπει" style="margin-right:0.5rem">👤 Αντικατάσταση</button>
                            <button class="btn btn-warning" id="tt-regen" title="Κράτα τα κλειδωμένα μαθήματα και ξανατρέξε τον solver για τα υπόλοιπα" style="margin-right:0.5rem">🔒 Lock & Regenerate</button>
                            <button class="btn btn-secondary" id="tt-compare" title="Σύγκρινε με άλλη λύση" style="margin-right:0.5rem">📊 Σύγκριση</button>
                            <button class="btn btn-secondary" id="tt-print" title="Εκτύπωση: με επιλεγμένο καθηγητή/μαθητή ανοίγει καθαρή σελίδα εκτύπωσης" style="margin-right:0.25rem">🖨️ Εκτύπωση</button>
                            <button class="btn btn-secondary" id="tt-ics" title="Εξαγωγή .ics για Google/Apple Calendar (διάλεξε πρώτα καθηγητή ή μαθητή στο φίλτρο)" style="margin-right:0.5rem">📆 ICS</button>
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
                                <option value="student">Μαθητή</option>
                                <option value="overview_teacher">Συνολική: Καθηγητές × Ώρες</option>
                                <option value="overview_class">Συνολική: Τμήματα × Ώρες</option>
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
            TimetableGrid.render('timetable-grid-view', solution.slots, periods, daysCount,'class', firstFilter, solutionId);
            this._renderParkingLot('parking-lot-container', solution.slots, solutionId);

            // Resolve the current view/filter to export query params, or
            // null when the selection isn't a single teacher/student.
            const exportParams = () => TimetableHelpers.resolveExportParams(
                document.getElementById('tt-view-type').value,
                document.getElementById('tt-filter').value,
                solutionId, teacherIdByName, studentIdByLabel,
            );

            // Event: Print — dedicated print page for a single teacher's or
            // student's programme, plain window.print() otherwise.
            document.getElementById('tt-print').addEventListener('click', () => {
                const params = exportParams();
                if (params) {
                    window.open(`/api/exports/print?${params}`, '_blank');
                } else {
                    window.print();
                }
            });

            // Event: ICS export (needs a specific teacher or student)
            document.getElementById('tt-ics').addEventListener('click', () => {
                const params = exportParams();
                if (!params) {
                    Toast.info('Διάλεξε "Προβολή ανά Καθηγητή ή Μαθητή" και συγκεκριμένο όνομα στο φίλτρο πρώτα.');
                    return;
                }
                window.open(`/api/exports/ics?${params}`, '_blank');
            });

            // Event: Compare με άλλη λύση
            document.getElementById('tt-compare').addEventListener('click', () => {
                CompareModal.open(solutions, solutionId);
            });

            // Event: Substitute teacher mode
            document.getElementById('tt-substitute').addEventListener('click', () => {
                SubstituteModal.open(solutionId, periods, daysCount);
            });

            // Event: Lock & Regenerate
            document.getElementById('tt-regen').addEventListener('click', () => {
                const lockedCount = TimetableHelpers.countLockedSlots(solution.slots);
                if (lockedCount === 0) {
                    Toast.error('Δεν έχει κλειδωθεί κανένα μάθημα. Πάτησε το 🔒 σε όσα θες να διατηρήσεις πρώτα.');
                    return;
                }
                // Proper modal instead of prompt()/confirm() — the old
                // confirm's "OK = strict / Cancel = permissive" mapping was
                // easy to get backwards.
                const body = `
                    <p>Νέα έκδοση βασισμένη σε <b>${lockedCount}</b> κλειδωμένα μαθήματα.</p>
                    <div class="form-group">
                        <label class="form-label">Όνομα νέας λύσης</label>
                        <input class="form-input" id="regen-name" value="${this._esc(solution.name)} v2">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Τρόπος</label>
                        <label style="display:block"><input type="radio" name="regen-mode" value="strict" checked> Αυστηρός — όλα τα μαθήματα πρέπει να μπουν</label>
                        <label style="display:block"><input type="radio" name="regen-mode" value="permissive"> Επιτρεπτικός — βάζει ό,τι μπορεί + parking lot</label>
                    </div>`;
                Modal.open('🔒 Lock & Regenerate', body, async () => {
                    const newName = document.getElementById('regen-name').value.trim();
                    if (!newName) { Toast.error('Δώσε όνομα.'); return; }
                    const mode = document.querySelector('input[name="regen-mode"]:checked').value;
                    Modal.close();
                    Toast.success('🧠 Solver εργάζεται στο παρασκήνιο…');
                    try {
                        const started = await API.solver.regenerateWithLocks(solutionId, {
                            name: newName, max_time_seconds: 120, mode,
                        });
                        const result = await TimetableInteractions.pollSolve(started.solution_id, 120);
                        if (result.status === 'optimal' || result.status === 'feasible') {
                            Toast.success(`✅ ${result.message}`);
                            App._currentSolutionId = result.solution_id;
                            await this.render(container);
                        } else {
                            Toast.error(result.message);
                        }
                    } catch (err) {
                        Toast.error(`Regenerate απέτυχε: ${err.message}`);
                    }
                }, { saveText: '🚀 Εκτέλεση', saveClass: 'btn-warning' });
            });

            // Slots passed to the grid. For "student" view we pre-filter
            // to only the slots whose class the selected student attends;
            // the grid itself doesn't know about students. "all" shows
            // every slot across every class the students collectively
            // touch — not super useful but consistent with other views.
            const slotsForView = (viewType, filterValue) => {
                if (viewType !== 'student' || !filterValue || filterValue === 'all') {
                    return solution.slots;
                }
                const allowedClassIds = studentByLabel.get(filterValue);
                if (!allowedClassIds || allowedClassIds.size === 0) {
                    return [];
                }
                return solution.slots.filter(s => allowedClassIds.has(s.class_id));
            };

            // Dispatch to the right renderer. The two "overview" view types
            // show ALL days at once (entity × day×hour), so they ignore the
            // entity filter; the regular views use it.
            const renderGrid = (viewType, filterValue) => {
                if (viewType && viewType.startsWith('overview')) {
                    const axis = viewType === 'overview_class' ? 'class' : 'teacher';
                    TimetableGrid.renderOverview(
                        'timetable-grid-view', solution.slots, periods,
                        daysCount, axis, solutionId,
                    );
                } else {
                    TimetableGrid.render(
                        'timetable-grid-view', slotsForView(viewType, filterValue),
                        periods, daysCount, viewType, filterValue, solutionId,
                    );
                }
            };

            // Event: View type change
            document.getElementById('tt-view-type').addEventListener('change', (e) => {
                const filterSelect = document.getElementById('tt-filter');
                const filterGroup = filterSelect.closest('.form-group');
                const filterLabel = filterGroup?.querySelector('.form-label');
                const vt = e.target.value;
                App._ttViewType = vt;  // persist across full re-renders

                if (vt.startsWith('overview')) {
                    // Overview shows every day at once → no entity filter needed.
                    if (filterGroup) filterGroup.style.display = 'none';
                    renderGrid(vt, null);
                    return;
                }

                if (filterGroup) filterGroup.style.display = '';
                if (filterLabel) filterLabel.textContent = 'Φίλτρο';
                let options = [];
                if (vt === 'class') options = classNames;
                else if (vt === 'teacher') options = teacherNames;
                else if (vt === 'student') options = studentNames;
                else options = roomNames;

                filterSelect.innerHTML = `<option value="all">-- Προβολή Όλων --</option>` +
                                         options.map(n => `<option value="${this._esc(n)}">${this._esc(n)}</option>`).join('');
                renderGrid(vt, 'all');
            });

            // Event: Filter change
            document.getElementById('tt-filter').addEventListener('change', (e) => {
                const viewType = document.getElementById('tt-view-type').value;
                renderGrid(viewType, e.target.value);
            });

            // Restore the persisted view type across full re-renders (solution
            // change, undo/redo, regenerate) so the user isn't silently bounced
            // out of e.g. the συνολική overview back to the weekly class grid.
            if (App._ttViewType && App._ttViewType !== 'class') {
                const vtSelect = document.getElementById('tt-view-type');
                if ([...vtSelect.options].some(o => o.value === App._ttViewType)) {
                    vtSelect.value = App._ttViewType;
                    vtSelect.dispatchEvent(new Event('change'));
                }
            }

            // Event: Solution change
            document.getElementById('tt-solution').addEventListener('change', async (e) => {
                App._currentSolutionId = parseInt(e.target.value);
                await this.render(container);
            });

            // Undo / Redo wiring
            const undoBtn = document.getElementById('tt-undo');
            const redoBtn = document.getElementById('tt-redo');

            const refreshHistoryButtons = async () => {
                try {
                    const summary = await API.solver.historySummary(solutionId);
                    undoBtn.disabled = summary.can_undo === 0;
                    redoBtn.disabled = summary.can_redo === 0;
                    undoBtn.title = summary.can_undo
                        ? `Αναίρεση τελευταίας αλλαγής (${summary.can_undo} διαθέσιμες) · Ctrl+Z`
                        : 'Καμία αλλαγή για αναίρεση';
                    redoBtn.title = summary.can_redo
                        ? `Επανάληψη (${summary.can_redo} διαθέσιμες) · Ctrl+Y`
                        : 'Καμία επανάληψη';
                } catch (err) {
                    // Stale solution / network — ignore
                }
            };

            const performUndoRedo = async (op) => {
                try {
                    const res = op === 'undo'
                        ? await API.solver.undo(solutionId)
                        : await API.solver.redo(solutionId);
                    Toast.success(res.message);
                    await this.render(container);
                } catch (err) {
                    Toast.error(err.message);
                }
            };

            undoBtn.addEventListener('click', () => performUndoRedo('undo'));
            redoBtn.addEventListener('click', () => performUndoRedo('redo'));
            this._historyKeyHandler = (e) => {
                if (!(e.ctrlKey || e.metaKey)) return;
                if (e.key === 'z' || e.key === 'Z') {
                    e.preventDefault();
                    if (!undoBtn.disabled) performUndoRedo('undo');
                } else if (e.key === 'y' || e.key === 'Y') {
                    e.preventDefault();
                    if (!redoBtn.disabled) performUndoRedo('redo');
                }
            };
            // Replace any previous binding on re-render
            if (this._activeKeyHandler) {
                document.removeEventListener('keydown', this._activeKeyHandler);
            }
            this._activeKeyHandler = this._historyKeyHandler;
            document.addEventListener('keydown', this._activeKeyHandler);

            await refreshHistoryButtons();

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
        container.innerHTML = unplaced.length
            ? TimetableHelpers.buildParkingLotHtml(unplaced)
            : '';
    },

    _esc(s) {
        return TimetableHelpers.esc(s);
    },

};
