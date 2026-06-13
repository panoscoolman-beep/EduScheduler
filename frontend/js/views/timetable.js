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
            document.getElementById('tt-compare').addEventListener('click', async () => {
                this._openCompareModal(solutions, solutionId);
            });

            // Event: Substitute teacher mode
            document.getElementById('tt-substitute').addEventListener('click', () => {
                this._openSubstituteModal(solutionId, periods, daysCount);
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
                        const result = await this._pollSolve(started.solution_id, 120);
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

            // Event: View type change
            document.getElementById('tt-view-type').addEventListener('change', (e) => {
                const filterSelect = document.getElementById('tt-filter');
                const vt = e.target.value;
                let options = [];
                if (vt === 'class') options = classNames;
                else if (vt === 'teacher') options = teacherNames;
                else if (vt === 'student') options = studentNames;
                else options = roomNames;

                filterSelect.innerHTML = `<option value="all">-- Προβολή Όλων --</option>` +
                                         options.map(n => `<option value="${this._esc(n)}">${this._esc(n)}</option>`).join('');
                TimetableGrid.render('timetable-grid-view', slotsForView(vt, 'all'), periods, daysCount, vt, 'all', solutionId);
            });

            // Event: Filter change
            document.getElementById('tt-filter').addEventListener('change', (e) => {
                const viewType = document.getElementById('tt-view-type').value;
                TimetableGrid.render('timetable-grid-view', slotsForView(viewType, e.target.value), periods, daysCount, viewType, e.target.value, solutionId);
            });

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
                     data-slot-id="${slot.id}"
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

    _esc(s) {
        return TimetableHelpers.esc(s);
    },

    /**
     * Poll /solver/status until the run leaves 'generating'. Used by
     * Lock & Regenerate now that it runs in the background like /generate.
     */
    async _pollSolve(solutionId, maxTimeSeconds) {
        const deadline = Date.now() + (maxTimeSeconds + 60) * 1000;
        while (Date.now() < deadline) {
            await new Promise(r => setTimeout(r, 3000));
            try {
                const status = await API.solver.status(solutionId);
                if (status.status !== 'generating') return status;
            } catch (e) {
                // transient hiccup — keep polling, the run continues server-side
            }
        }
        return { status: 'error', message: 'Η αναδημιουργία αργεί — δες τη λίστα λύσεων σε λίγο.' };
    },

    /**
     * Open a modal that lets the user pick a second (or third) solution
     * to compare against the current one. Shows a side-by-side metrics
     * grid with the winner per row highlighted.
     */
    _openCompareModal(solutions, currentId) {
        const others = solutions.filter(s => s.id !== currentId);
        if (others.length === 0) {
            Toast.error('Χρειάζονται ≥2 solutions για σύγκριση. Δημιούργησε άλλο πρώτα.');
            return;
        }

        const optionsHtml = others.map(s =>
            `<label style="display:flex; align-items:center; gap:0.5rem; padding:0.4rem 0;">
                <input type="checkbox" class="cmp-pick" value="${s.id}">
                <span><strong>${s.name}</strong>
                <span class="text-muted" style="font-size:0.85em">— ${s.status}, score=${s.score?.toFixed(0) || '—'}</span></span>
            </label>`
        ).join('');

        Modal.open(
            '📊 Σύγκριση Λύσεων',
            `
            <p class="text-muted" style="margin-bottom:1rem;">
                Η τρέχουσα λύση συμπεριλαμβάνεται αυτόματα. Επίλεξε
                ≥1 ακόμα για side-by-side metrics.
            </p>
            <div style="margin-bottom:1rem;">${optionsHtml}</div>
            <div style="text-align:right;">
                <button class="btn btn-primary" id="cmp-run">📊 Σύγκρινε</button>
            </div>
            <div id="cmp-result" style="margin-top:1.5rem;"></div>
            `,
            null,
            { hideFooter: true }
        );

        document.getElementById('cmp-run').addEventListener('click', async () => {
            const picked = Array.from(document.querySelectorAll('.cmp-pick:checked'))
                .map(cb => parseInt(cb.value));
            if (picked.length === 0) {
                Toast.error('Επίλεξε τουλάχιστον μία λύση να συγκρίνεις');
                return;
            }
            const ids = [currentId, ...picked];
            try {
                const result = await API.solver.compare(ids);
                this._renderCompareResult(result, document.getElementById('cmp-result'));
            } catch (err) {
                Toast.error(err.message);
            }
        });
    },

    /**
     * Find substitute teachers / reschedule slots for a teacher who's
     * absent on a given day. Shows the affected slots with two columns
     * each: candidate substitutes and reschedule options. Read-only —
     * the user applies the choice through the existing drag-drop UI.
     */
    async _openSubstituteModal(solutionId, periods, daysCount) {
        let teachers;
        try {
            teachers = await API.teachers.list();
        } catch (err) {
            Toast.error(`Αποτυχία φόρτωσης καθηγητών: ${err.message}`);
            return;
        }

        const dayNames = ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη',
                          'Παρασκευή', 'Σάββατο', 'Κυριακή'];
        const teacherOptions = teachers.map(t =>
            `<option value="${t.id}">${this._esc(t.name)}</option>`
        ).join('');
        const dayOptions = Array.from({length: daysCount}, (_, i) =>
            `<option value="${i}">${dayNames[i]}</option>`
        ).join('');

        Modal.open(
            '👤 Αντικατάσταση Καθηγητή',
            `
            <p class="text-muted" style="margin-bottom:1rem;">
                Επίλεξε τον καθηγητή που λείπει και τη μέρα. Θα δούμε
                τα μαθήματα που επηρεάζονται και προτάσεις για κάθε ένα.
            </p>
            <div style="display:flex; gap:1rem; margin-bottom:1rem; flex-wrap:wrap;">
                <div class="form-group" style="flex:1; min-width:200px; margin:0;">
                    <label class="form-label">Καθηγητής</label>
                    <select class="form-select" id="sub-teacher">${teacherOptions}</select>
                </div>
                <div class="form-group" style="flex:1; min-width:150px; margin:0;">
                    <label class="form-label">Μέρα</label>
                    <select class="form-select" id="sub-day">${dayOptions}</select>
                </div>
            </div>
            <div style="text-align:right;">
                <button class="btn btn-primary" id="sub-find">🔍 Βρες προτάσεις</button>
            </div>
            <div id="sub-result" style="margin-top:1.5rem;"></div>
            `,
            null,
            { hideFooter: true }
        );

        document.getElementById('sub-find').addEventListener('click', async () => {
            const teacherId = parseInt(document.getElementById('sub-teacher').value);
            const dayOfWeek = parseInt(document.getElementById('sub-day').value);
            const resultEl = document.getElementById('sub-result');
            resultEl.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';
            try {
                const data = await API.solver.substituteSuggestions(
                    solutionId, teacherId, dayOfWeek);
                this._renderSubstituteResult(data, resultEl, dayNames[dayOfWeek]);
            } catch (err) {
                resultEl.innerHTML = `<p class="text-muted">Σφάλμα: ${this._esc(err.message)}</p>`;
            }
        });
    },

    _renderSubstituteResult(data, mountEl, dayLabel) {
        mountEl.innerHTML = TimetableHelpers.buildSubstituteResultHtml(data, dayLabel);
    },

    _renderCompareResult(result, mountEl) {
        mountEl.innerHTML = TimetableHelpers.buildCompareResultHtml(result);
    },
};
