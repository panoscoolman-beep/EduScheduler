/**
 * Timetable View — Visual grid of generated schedule.
 */
const TimetableView = {
    async render(container) {
        container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>`;

        try {
            const [solutions, periods, settings] = await Promise.all([
                // Με τα αρχειοθετημένα: μπαίνουν σε ξεχωριστή ομάδα ώστε να επαναφέρονται.
                API.solver.listSolutions(true),
                API.periods.list(),
                API.settings.get(),
            ]);
            // Honour school_settings.days_per_week — until now this was
            // hardcoded to 5, hiding any slots placed on Σάβ/Κυρ.
            const daysCount = settings.days_per_week || 5;
            // Ωράριο λειτουργίας: κρύβει ώρες εκτός (όχι όσες έχουν μάθημα) και
            // γίνεται η προεπιλογή του παραθύρου των «Ελεύθερων Αιθουσών».
            const hasWindow = settings.visible_from || settings.visible_to
                || settings.saturday_from || settings.saturday_to;
            const schoolWindow = hasWindow ? {
                from: settings.visible_from || '', to: settings.visible_to || '',
                saturday: { from: settings.saturday_from || '', to: settings.saturday_to || '' },
            } : null;
            TimetableGrid.operatingWindow = schoolWindow;
            this._schoolWindow = schoolWindow;

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
            const solutionId = TimetableHelpers.defaultSolutionId(
                solutions, App._currentSolutionId);
            const archiveBtn = TimetableHelpers.archiveButtonState(solutions, solutionId);
            const [solution, students, lessons] = await Promise.all([
                API.solver.getSolution(solutionId),
                API.students.list().catch(() => []),
                // Τροφοδοτεί την Παλέτα Μαθημάτων (ppw + μαθήματα χωρίς slots).
                API.lessons.list().catch(() => []),
            ]);
            this._lessons = lessons;

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
                            <button class="btn btn-secondary" id="tt-redo" title="Επανάληψη (Ctrl+Y)" style="margin-right:0.25rem" disabled>↪ Επανάληψη</button>
                            <button class="btn btn-secondary" id="tt-history" title="Οι τελευταίες αλλαγές — αναίρεση μέχρι κάποιο σημείο" style="margin-right:0.5rem">🕘 Ιστορικό</button>
                            <button class="btn btn-secondary" id="tt-substitute" title="Βρες αντικαταστάτη για καθηγητή που λείπει" style="margin-right:0.25rem">👤 Αντικατάσταση</button>
                            <button class="btn btn-secondary" id="tt-empty" title="Όλες οι ώρες ενός καθηγητή ή τμήματος στην Παλέτα — επαναφέρονται με ένα κλικ" style="margin-right:0.5rem">🅿️ Άδειασμα</button>
                            <button class="btn btn-warning" id="tt-regen" title="Κράτα τα κλειδωμένα μαθήματα και ξανατρέξε τον solver για τα υπόλοιπα" style="margin-right:0.25rem">🔒 Lock & Regenerate</button>
                            <button class="btn btn-secondary" id="tt-fill" title="Κράτα ΟΛΑ όσα έχεις βάλει και άφησε τον solver να τοποθετήσει τις ώρες της Παλέτας — σε νέο πρόγραμμα" style="margin-right:0.5rem">🧩 Γέμισε τα κενά</button>
                            <button class="btn btn-secondary" id="tt-compare" title="Σύγκρινε με άλλη λύση" style="margin-right:0.25rem">📊 Σύγκριση</button>
                            <button class="btn btn-secondary" id="tt-diff" title="Slot-level διαφορές με άλλη λύση: τι μετακινήθηκε, τι μπήκε/βγήκε" style="margin-right:0.25rem">🔀 Τι άλλαξε;</button>
                            <button class="btn btn-secondary" id="tt-violations" title="Γιατί αυτό το score; Κενά καθηγητών, αργές ώρες, φόρτος" style="margin-right:0.5rem">⚖️ Ποιότητα</button>
                            <button class="btn btn-secondary" id="tt-bulk-export" title="Όλα τα προγράμματα μαζί: εκτύπωση με μία σελίδα ανά καθηγητή/τμήμα, ή Excel" style="margin-right:0.25rem">📦 Μαζική εξαγωγή</button>
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
                                <option value="free_rooms">Ελεύθερες Αίθουσες</option>
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
                            <div style="display:flex; gap:4px; align-items:center;">
                                <select class="form-select" id="tt-solution">
                                    ${TimetableHelpers.buildSolutionOptionsHtml(solutions, solutionId)}
                                </select>
                                <button class="btn btn-secondary btn-sm" id="tt-rename"
                                        title="Μετονομασία προγράμματος">✏️</button>
                                <button class="btn btn-secondary btn-sm" id="tt-archive"
                                        title="${archiveBtn.title}">${archiveBtn.icon}</button>
                            </div>
                        </div>
                    </div>

                    <div id="timetable-grid-view"></div>
                </div>

                <div id="parking-lot-container"></div>
            `;

            // Initial render
            const firstFilter = 'all';
            TimetableGrid.render('timetable-grid-view', solution.slots, periods, daysCount,'class', firstFilter, solutionId);
            this._renderLessonPalette('parking-lot-container', solution.slots, solutionId, periods);

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
                    const withLabel = TimetableHelpers.withPrintClassLabel(
                        params, TimetableHelpers.printClassLabelPref());
                    window.open(`/api/exports/print?${withLabel}`, '_blank');
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

            // Event: Slot-level diff με άλλη λύση
            document.getElementById('tt-diff').addEventListener('click', () => {
                InsightsModal.openDiff(solutions, solutionId);
            });

            // Event: Αναφορά παραβιάσεων soft constraints
            document.getElementById('tt-violations').addEventListener('click', () => {
                InsightsModal.openViolations(solutionId);
            });

            // Event: Μαζική εκτύπωση / Excel
            document.getElementById('tt-bulk-export').addEventListener('click', () => {
                InsightsModal.openBulkExport(solutionId);
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

            // 🧩 Γέμισε τα κενά: όλα τα τοποθετημένα σταθερά, ο solver βάζει ό,τι
            // χωράει από την Παλέτα, σε ΝΕΟ πρόγραμμα (το τρέχον δεν αλλάζει).
            document.getElementById('tt-fill').addEventListener('click', () =>
                this._openFillGaps(solutionId, solution, container));

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
                if (viewType === 'free_rooms') {
                    const mount = document.getElementById('timetable-grid-view');
                    mount.innerHTML = '<p>Φόρτωση αιθουσών…</p>';
                    // Χωρίς cache: η λίστα αιθουσών είναι μικρή και έτσι νέες/
                    // διαγραμμένες αίθουσες φαίνονται αμέσως. Guard: αν ο χρήστης
                    // άλλαξε view όσο φορτώναμε, μην πατήσουμε το άλλο grid.
                    API.classrooms.list()
                        .then(rooms => {
                            if (document.getElementById('tt-view-type')?.value !== 'free_rooms') return;
                            // Γέμισε το φίλτρο με τις αίθουσες (μία φορά ανά
                            // φόρτωση) ώστε να μπορεί να διαλέξει συγκεκριμένη.
                            const sel = document.getElementById('tt-filter');
                            if (sel && sel.dataset.mode !== 'rooms') {
                                sel.dataset.mode = 'rooms';
                                sel.innerHTML = '<option value="all">Όλες οι αίθουσες</option>'
                                    + rooms.map(r => `<option value="${TimetableHelpers.esc(r.name)}">${TimetableHelpers.esc(r.name)}</option>`).join('');
                                sel.value = filterValue || 'all';
                            }
                            mount.innerHTML = TimetableHelpers.buildFreeRoomsHtml(
                                solution.slots, periods, daysCount, rooms,
                                filterValue || (sel ? sel.value : 'all'),
                                TimetableView.freeRoomsWindow(),
                            );
                        })
                        .catch(err => Toast.error(`Αδύνατη η φόρτωση αιθουσών: ${err.message}`));
                    return;
                }
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

            // Ξαναζωγράφισε το grid στην ΤΡΕΧΟΥΣΑ προβολή/φίλτρο — το
            // χρειάζεται το «Βρες μου θέση» για να εμφανίσει την κάρτα
            // που μόλις τοποθετήθηκε χωρίς πλήρες view re-render.
            this._rerenderGrid = () => {
                const vt = document.getElementById('tt-view-type')?.value || 'class';
                const fv = document.getElementById('tt-filter')?.value || 'all';
                renderGrid(vt, vt.startsWith('overview') ? null : fv);
            };

            // Event: View type change
            document.getElementById('tt-view-type').addEventListener('change', (e) => {
                const filterSelect = document.getElementById('tt-filter');
                const filterGroup = filterSelect.closest('.form-group');
                const filterLabel = filterGroup?.querySelector('.form-label');
                const vt = e.target.value;
                App._ttViewType = vt;  // persist across full re-renders

                const parkingLot = document.getElementById('parking-lot-container');
                if (vt.startsWith('overview')) {
                    // Overview shows every day at once → no entity filter needed.
                    // Hide the parking lot too: dropping an unplaced (entity-less)
                    // card into an overview row would land it in the wrong row.
                    if (filterGroup) filterGroup.style.display = 'none';
                    if (parkingLot) parkingLot.style.display = 'none';
                    renderGrid(vt, null);
                    return;
                }
                if (vt === 'free_rooms') {
                    // Το φίλτρο εδώ είναι ΑΙΘΟΥΣΑ («πότε είναι ελεύθερη η Χ;»)
                    // — γεμίζει από τον renderer που φέρνει τις αίθουσες.
                    if (filterGroup) filterGroup.style.display = '';
                    if (filterLabel) filterLabel.textContent = 'Αίθουσα';
                    if (parkingLot) parkingLot.style.display = 'none';
                    filterSelect.dataset.mode = '';       // force refill
                    renderGrid(vt, 'all');
                    return;
                }

                if (filterGroup) filterGroup.style.display = '';
                if (parkingLot) parkingLot.style.display = '';
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

            // Event: ✏️ rename the selected programme (name only)
            document.getElementById('tt-rename').addEventListener('click', () =>
                this._openRenameSolution(solutionId));

            // Event: 📦 αρχειοθέτηση / ♻️ επαναφορά του επιλεγμένου προγράμματος
            document.getElementById('tt-archive').addEventListener('click', () =>
                this._toggleArchiveSolution(solutionId, solutions, container));

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

            // Bug fix: μετά από χειροκίνητη αλλαγή (drop/swap/unplace/lock)
            // τα κουμπιά Undo/Redo έμεναν στην αρχική τους κατάσταση — αν η
            // προβολή ξεκινούσε χωρίς ιστορικό, το Ctrl+Z έμενε νεκρό μέχρι
            // το επόμενο πλήρες re-render. Το TimetableGrid ειδοποιεί εδώ.
            this._refreshHistoryButtons = refreshHistoryButtons;

            undoBtn.addEventListener('click', () => performUndoRedo('undo'));
            document.getElementById('tt-history').addEventListener('click', () =>
                this._openHistory(solutionId, container));
            document.getElementById('tt-empty').addEventListener('click', () =>
                this._openBulkUnplace(solutionId, solution.slots, container));
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
     * Render the «Παλέτα Μαθημάτων» below the grid: ΟΛΑ τα μαθήματα του
     * σεναρίου ως compact κάρτες με μετρητή υπολειπόμενων ωρών, φίλτρα και
     * αναζήτηση. Οι κάρτες με διαθέσιμες ώρες σέρνονται στο πλέγμα (ίδιο
     * drop-flow με το παλιό parking lot — μία ώρα ανά drop).
     */
    _renderLessonPalette(containerId, allSlots, solutionId, periods = null) {
        const container = document.getElementById(containerId);
        if (!container) return;
        this._paletteCtx = {
            containerId, slots: allSlots, solutionId,
            // Τα periods χρειάζονται στο modal του «Βρες μου θέση» για
            // ετικέτες ωρών· στο refresh κρατάμε τα ήδη γνωστά.
            periods: periods || (this._paletteCtx ? this._paletteCtx.periods : []),
        };
        const ui = this._paletteUi || (this._paletteUi = {
            collapsed: this._readPref('eds-palette-collapsed') === '1',
            search: '', fClass: '', fTeacher: '', fSubject: '',
        });
        const palette = TimetableHelpers.buildLessonPalette(allSlots, this._lessons || []);
        container.innerHTML = TimetableHelpers.buildLessonPaletteHtml(palette, ui);
        if (!container.innerHTML.trim()) return;

        const wire = (id, key, ev) => {
            const el = container.querySelector('#' + id);
            if (el) el.addEventListener(ev, () => {
                ui[key] = el.value;
                this.applyPaletteFilters();
            });
        };
        wire('palette-search', 'search', 'input');
        wire('palette-f-class', 'fClass', 'change');
        wire('palette-f-teacher', 'fTeacher', 'change');
        wire('palette-f-subject', 'fSubject', 'change');
        this.applyPaletteFilters();
        this._wirePaletteDropZone(container);
    },

    /**
     * Η Παλέτα ως drop zone: σέρνεις τοποθετημένη κάρτα από το πλέγμα και
     * την αφήνεις εδώ → η ώρα αφαιρείται από το πρόγραμμα (unplace).
     * Delegation στο σταθερό container (επιβιώνει τα re-renders)· οι
     * κάρτες της ίδιας της Παλέτας αγνοούνται.
     */
    _wirePaletteDropZone(container) {
        if (container._unplaceWired) return;
        container._unplaceWired = true;
        const panel = () => container.querySelector('.lesson-palette');
        const draggingPlacedCard = () =>
            TimetableGrid._dragSlotId && !TimetableGrid._dragIsParking;

        container.addEventListener('dragover', (e) => {
            if (!draggingPlacedCard()) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            panel()?.classList.add('palette-drop-ready');
        });
        container.addEventListener('dragleave', (e) => {
            if (!container.contains(e.relatedTarget)) {
                panel()?.classList.remove('palette-drop-ready');
            }
        });
        container.addEventListener('drop', (e) => {
            panel()?.classList.remove('palette-drop-ready');
            if (!draggingPlacedCard()) return;
            e.preventDefault();
            TimetableGrid.unplaceSlot(TimetableGrid._dragSlotId);
        });
    },

    /** Show/hide palette cards to match the current search + filters. */
    applyPaletteFilters() {
        const ui = this._paletteUi || {};
        const q = (ui.search || '').trim().toLowerCase();
        let visible = 0;
        document.querySelectorAll('.lesson-palette .palette-card').forEach(c => {
            const ok = (!ui.fClass || c.dataset.fclass === ui.fClass)
                && (!ui.fTeacher || c.dataset.fteacher === ui.fTeacher)
                && (!ui.fSubject || c.dataset.fsubject === ui.fSubject)
                && (!q || (c.dataset.search || '').includes(q));
            c.style.display = ok ? '' : 'none';
            if (ok) visible += 1;
        });
        const msg = document.querySelector('.lesson-palette .palette-empty-msg');
        if (msg) msg.style.display = visible ? 'none' : '';
    },

    /**
     * ✏️ Μετονομασία του τρέχοντος προγράμματος. Αλλάζει ΜΟΝΟ το όνομα (ώρες,
     * κλειδώματα, ιστορικό μένουν ίδια)· ενημερώνει το dropdown επί τόπου,
     * χωρίς πλήρες re-render. Η τιμή μπαίνει στο input μέσω DOM (όχι μέσα σε
     * attribute) ώστε εισαγωγικά στο όνομα να μη σπάνε το HTML.
     */
    /**
     * 📦 Αρχειοθέτηση / ♻️ επαναφορά προγράμματος. ΔΕΝ σβήνεται τίποτα: το
     * αρχειοθετημένο βγαίνει απλώς από τη λίστα και σταματά να «κρατά» ώρες
     * (το «🔍 Τι επηρεάζει;» δεν το μετρά πια).
     */
    _toggleArchiveSolution(solutionId, solutions, container) {
        const state = TimetableHelpers.archiveButtonState(solutions, solutionId);
        if (state.archived) {
            this._applyArchive(solutionId, false, container);
            return;
        }
        const solution = (solutions || []).find(s => s.id === solutionId) || {};
        Modal.open('📦 Αρχειοθέτηση προγράμματος', `
            <p>Το «<b>${this._esc(solution.name || '')}</b>» θα βγει από τη λίστα προγραμμάτων.</p>
            <ul class="text-muted" style="font-size:0.85rem; margin:0.5rem 0 0 1.1rem">
                <li>Δεν σβήνεται τίποτα — ώρες, κλειδώματα και ιστορικό μένουν ακέραια.</li>
                <li>Σταματά να «κρατά» ώρες: η Παλέτα και ο έλεγχος 🔍 δεν το μετρούν πια.</li>
                <li>Επαναφέρεται όποτε θες από την ομάδα «📦 Αρχειοθετημένα».</li>
            </ul>`,
            () => this._applyArchive(solutionId, true, container),
            { saveText: '📦 Αρχειοθέτηση' });
    },

    async _applyArchive(solutionId, archived, container) {
        try {
            const res = archived
                ? await API.solver.archiveSolution(solutionId)
                : await API.solver.unarchiveSolution(solutionId);
            Modal.close();
            Toast.success(res.message || 'Έγινε');
            // Μετά την αρχειοθέτηση ανοίγει το νεότερο ενεργό πρόγραμμα.
            if (archived && App._currentSolutionId === solutionId) App._currentSolutionId = null;
            await this.render(container);
        } catch (err) {
            Toast.error('Δεν έγινε: ' + this._esc(err.message));
        }
    },

    /**
     * 🅿️ Άδειασμα καθηγητή/τμήματος: όλες οι τοποθετημένες ώρες (εκτός 🔒)
     * στην Παλέτα. Μετά: κουμπί «↩️ Επαναφορά όλων» (undo-to του 1ου βήματος).
     */
    _openBulkUnplace(solutionId, slots, container) {
        const targets = TimetableHelpers.bulkUnplaceTargets(slots);
        const options = (kind) => targets[kind].map(t =>
            `<option value="${t.id}">${this._esc(t.name)} (${t.movable + t.locked} ώρες)</option>`).join('');
        Modal.open('🅿️ Άδειασμα καθηγητή ή τμήματος', `
            <div class="form-grid">
                <div class="form-group">
                    <label class="form-label">Τι αδειάζει</label>
                    <select class="form-select" id="bu-kind">
                        <option value="teacher">Καθηγητής</option>
                        <option value="class">Τμήμα</option>
                    </select>
                </div>
                <div class="form-group">
                    <label class="form-label">Ποιος / ποιο</label>
                    <select class="form-select" id="bu-target"></select>
                </div>
            </div>
            <p class="text-muted" id="bu-summary" style="font-size:0.9rem"></p>`,
        async () => {
            const kind = document.getElementById('bu-kind').value;
            const id = Number(document.getElementById('bu-target').value);
            if (!id) return;
            try {
                const res = await API.solver.unplaceBulk(solutionId,
                    kind === 'teacher' ? { teacher_id: id } : { class_id: id });
                Modal.close();
                await this.render(container);
                this._offerBulkRestore(solutionId, res, container);
            } catch (err) {
                Toast.error(err.message);
            }
        }, { saveText: '🅿️ Άδειασμα' });
        const kindSel = document.getElementById('bu-kind');
        const targetSel = document.getElementById('bu-target');
        const summary = document.getElementById('bu-summary');
        const refresh = () => {
            const kind = kindSel.value;
            const t = targets[kind].find(x => String(x.id) === targetSel.value);
            summary.textContent = TimetableHelpers.bulkUnplaceSummary(t);
        };
        const fill = () => { targetSel.innerHTML = options(kindSel.value); refresh(); };
        kindSel.addEventListener('change', fill);
        targetSel.addEventListener('change', refresh);
        fill();
    },

    /** Μετά το άδειασμα: επαναφορά ΟΛΩΝ με ένα κλικ (αναστρέψιμη κι αυτή). */
    _offerBulkRestore(solutionId, res, container) {
        if (!res.first_entry_id) {
            Toast.info(res.message);
            return;
        }
        Modal.open('✅ Έγινε', `<p>${this._esc(res.message)}</p>
            <p class="text-muted" style="font-size:0.85rem">Άλλαξες γνώμη; Επανέρχονται όλες ακριβώς όπου ήταν.</p>`,
        async () => {
            try {
                const back = await API.solver.undoTo(solutionId, res.first_entry_id);
                Toast.success(back.message);
                Modal.close();
                await this.render(container);
            } catch (err) {
                Toast.error(err.message);
            }
        }, { saveText: '↩️ Επαναφορά όλων' });
    },

    _openFillGaps(solutionId, solution, container) {
        const { placed, palette } = TimetableHelpers.fillGapsCounts(solution.slots);
        if (!palette) {
            Toast.info('Η Παλέτα είναι άδεια — δεν υπάρχουν κενά να γεμίσουν.');
            return;
        }
        Modal.open('🧩 Γέμισε τα κενά', `
            <p>Οι <b>${placed}</b> ώρες που έχεις ήδη βάλει μένουν <b>ακριβώς ίδιες</b>. Ο solver
               προσπαθεί να τοποθετήσει τις <b>${palette}</b> ώρες της Παλέτας στα κενά· ό,τι δεν
               χωράει μένει στην Παλέτα.</p>
            <p class="text-muted" style="font-size:0.85rem">Το αποτέλεσμα βγαίνει ως <b>νέο πρόγραμμα</b> —
               το τρέχον δεν αλλάζει. Σύγκρινέ τα με «📊 Σύγκριση» και κράτα όποιο θες.</p>
            <div class="form-group">
                <label class="form-label">Όνομα νέου προγράμματος</label>
                <input class="form-input" id="fill-name" value="${this._esc(solution.name)} (συμπλήρωση)">
            </div>`,
        async () => {
            const name = document.getElementById('fill-name').value.trim();
            if (!name) { Toast.error('Δώσε όνομα.'); return; }
            Modal.close();
            Toast.success('🧠 Ο solver γεμίζει τα κενά στο παρασκήνιο…');
            try {
                const started = await API.solver.regenerateWithLocks(solutionId, {
                    name, max_time_seconds: 120, mode: 'permissive', lock_all_placed: true,
                });
                const result = await TimetableInteractions.pollSolve(started.solution_id, 120);
                if (result.status === 'optimal' || result.status === 'feasible') {
                    Toast.success(`✅ Έτοιμο το «${name}» — σύγκρινέ το με το αρχικό.`);
                    App._currentSolutionId = result.solution_id;
                    await this.render(container);
                } else {
                    Toast.error(result.message);
                }
            } catch (err) {
                Toast.error(`Δεν έγινε: ${err.message}`);
            }
        }, { saveText: '🧩 Εκτέλεση' });
    },

    /** 🕘 Ιστορικό αλλαγών με «αναίρεση μέχρι εδώ». */
    async _openHistory(solutionId, container) {
        Modal.open('🕘 Ιστορικό αλλαγών',
            '<div class="loading-spinner"><div class="spinner"></div></div>',
            null, { hideFooter: true, wide: true });
        let history;
        try {
            history = await API.solver.history(solutionId);
        } catch (err) {
            Toast.error(err.message);
            return;
        }
        const body = document.getElementById('modal-body');
        if (!body) return;
        body.innerHTML = TimetableHelpers.buildHistoryHtml(history);
        body.querySelectorAll('.hist-undo-to').forEach(btn => btn.addEventListener('click', async () => {
            try {
                const res = await API.solver.undoTo(solutionId, Number(btn.dataset.id));
                Toast.success(res.message);
                Modal.close();
                await this.render(container);
            } catch (err) {
                Toast.error(err.message);
            }
        }));
    },

    _openRenameSolution(solutionId) {
        const select = document.getElementById('tt-solution');
        const option = select ? [...select.options].find(o => Number(o.value) === solutionId) : null;
        const current = option ? option.textContent.trim() : '';
        Modal.open('✏️ Μετονομασία προγράμματος', `
            <div class="form-group">
                <label class="form-label">Νέο όνομα</label>
                <input class="form-input" id="f-solution-name" maxlength="200">
            </div>
            <p class="text-muted" style="font-size:0.85rem; margin-top:0.5rem">
                Αλλάζει μόνο το όνομα — οι ώρες, τα κλειδώματα και το ιστορικό μένουν ίδια.
            </p>`,
        async () => {
            const name = document.getElementById('f-solution-name').value.trim();
            if (!name) { Toast.error('Το όνομα δεν μπορεί να είναι κενό.'); return; }
            if (name === current) { Modal.close(); return; }
            try {
                const res = await API.solver.renameSolution(solutionId, name);
                if (option) option.textContent = res.name;
                Toast.success(`Το πρόγραμμα μετονομάστηκε σε «${this._esc(res.name)}»`);
                Modal.close();
            } catch (err) {
                Toast.error('Αποτυχία μετονομασίας: ' + this._esc(err.message));
            }
        }, { saveText: 'Αποθήκευση' });
        const input = document.getElementById('f-solution-name');
        if (input) { input.value = current; input.select && input.select(); }
    },

    /**
     * Χρονικό παράθυρο των «Ελεύθερων Αιθουσών». Default 14:00–22:00 (οι ώρες
     * λειτουργίας του φροντιστηρίου) ώστε να μη γεμίζει το πλέγμα με πρωινά
     * κελιά όπου δεν γίνεται μάθημα και «όλες οι αίθουσες» είναι ελεύθερες.
     * Ο χρήστης το αλλάζει από τους επιλογείς πάνω από το grid.
     */
    FREE_ROOMS_DEFAULT_WINDOW: { from: '14:00', to: '22:00' },

    freeRoomsWindow() {
        const saved = this._readPref('eds-free-rooms-window');
        if (saved === 'all') return { from: '', to: '' };
        if (saved) {
            const [from, to] = saved.split('|');
            if (from || to) return { from: from || '', to: to || '' };
        }
        return { ...(this._schoolWindow || this.FREE_ROOMS_DEFAULT_WINDOW) };
    },

    /** Επιλογή ωρών από τους selects — αποθήκευση + επανασχεδίαση. */
    setFreeRoomsWindow(from, to) {
        this._writePref('eds-free-rooms-window', (from || to) ? `${from || ''}|${to || ''}` : 'all');
        if (this._rerenderGrid) this._rerenderGrid();
    },

    /**
     * localStorage με ασπίδα: σε private mode ή με μπλοκαρισμένα site data
     * το `localStorage` ΠΕΤΑΕΙ — πριν, αυτό έριχνε ΟΛΟ το Ωρολόγιο σε
     * «Σφάλμα». Η προτίμηση είναι απλή ευκολία, όχι δεδομένα.
     */
    _readPref(key) {
        try { return localStorage.getItem(key); } catch (e) { return null; }
    },

    _writePref(key, value) {
        try { localStorage.setItem(key, value); } catch (e) { /* ignore */ }
    },

    /** Collapse/expand the palette; remembered in localStorage. */
    togglePalette() {
        const ui = this._paletteUi;
        if (!ui) return;
        ui.collapsed = !ui.collapsed;
        this._writePref('eds-palette-collapsed', ui.collapsed ? '1' : '0');
        const body = document.getElementById('palette-body');
        const btn = document.getElementById('palette-toggle');
        if (body) body.style.display = ui.collapsed ? 'none' : '';
        if (btn) btn.textContent = ui.collapsed ? '▸ Εμφάνιση' : '▾ Απόκρυψη';
    },

    /**
     * Re-render the palette from the (shared, in-place mutated) slots array.
     * Called by TimetableGrid after a successful/failed parking-card drop so
     * counters and the «next draggable slot» stay fresh — filters intact.
     */
    refreshPalette() {
        const ctx = this._paletteCtx;
        if (!ctx) return;
        this._renderLessonPalette(ctx.containerId, ctx.slots, ctx.solutionId);
    },

    /**
     * «🎯 Βρες μου θέση»: φέρε το placement map για την επόμενη διαθέσιμη
     * ώρα του μαθήματος και δείξε ΟΛΕΣ τις νόμιμες θέσεις ως chips ανά
     * μέρα — κλικ σε chip = τοποθέτηση (ίδιο PUT με το drag & drop).
     */
    async findPlacement(lessonId) {
        const ctx = this._paletteCtx;
        if (!ctx) return;
        const slot = ctx.slots.find(s => s.lesson_id === lessonId && s.is_unplaced);
        if (!slot) {
            Toast.error('Δεν υπάρχει διαθέσιμη ώρα για τοποθέτηση σε αυτό το μάθημα.');
            return;
        }
        try {
            const map = await API.solver.placementMap(ctx.solutionId, slot.id);
            const html = TimetableHelpers.buildPlacementChoicesHtml(map, ctx.periods);
            const title = `🎯 ${slot.subject_name || 'Μάθημα'} — ${slot.class_name || ''}`;
            if (!html) {
                Toast.error('Δεν βρέθηκαν διδακτικές ώρες στο πρόγραμμα.');
                return;
            }
            Modal.open(title, html, () => Modal.close(),
                { saveText: 'Κλείσιμο', saveClass: 'btn-secondary' });
        } catch (err) {
            Toast.error('Αποτυχία αναζήτησης θέσης: ' + err.message);
        }
    },

    /** Chip click από το modal του «Βρες μου θέση» — τοποθέτηση slot. */
    async placeAt(slotId, dayOfWeek, periodId) {
        Modal.close();
        const ctx = this._paletteCtx;
        if (!ctx) return;
        try {
            const res = await API.solver.updateSlot(ctx.solutionId, slotId, {
                day_of_week: dayOfWeek,
                period_id: periodId,
            });
            const rec = ctx.slots.find(s => s.id === slotId);
            if (rec) {
                rec.day_of_week = dayOfWeek;
                rec.period_id = periodId;
                rec.is_unplaced = false;
                rec.unplaced_reason = null;
                if (res && res.slot) {
                    rec.classroom_id = res.slot.classroom_id;
                    if (res.slot.classroom_name) rec.classroom_name = res.slot.classroom_name;
                }
            }
            const dayName = TimetableGrid.DAY_NAMES[dayOfWeek] || '';
            const period = (ctx.periods || []).find(p => p.id === periodId);
            const room = (res && res.slot && res.slot.classroom_name)
                ? ` — αίθουσα ${res.slot.classroom_name}` : '';
            Toast.success(`Τοποθετήθηκε: ${dayName} ${period ? period.short_name : ''}${room}`);
            this.refreshPalette();
            if (this._rerenderGrid) this._rerenderGrid();
            if (this._refreshHistoryButtons) this._refreshHistoryButtons();
        } catch (err) {
            TimetableGrid.reportConflict('Αποτυχία τοποθέτησης: ', err);
        }
    },

    /**
     * «Λείπουν N ώρες»: υλοποίησε τα slots που λείπουν από το μάθημα σε
     * αυτή τη λύση (POST sync-slots) και φρεσκάρισε slots + παλέτα. Το
     * shared slots array ενημερώνεται IN PLACE ώστε grid και παλέτα να
     * βλέπουν την ίδια αλήθεια χωρίς πλήρες re-render του view.
     */
    /**
     * «🔍 Τι επηρεάζει;» για μια κάρτα της Παλέτας: δείχνει πού χρησιμοποιείται
     * το μάθημα ΠΡΙΝ ο χρήστης σβήσει ώρες, και προσφέρει τις δύο ασφαλείς
     * ενέργειες (καθάρισμα Παλέτας / διαγραφή μαθήματος με επιβεβαίωση).
     */
    /** 🧹 Μαζικό καθάρισμα Παλέτας (ίδιοι κανόνες ασφαλείας με το 🔍). */
    openPaletteCleanup() {
        PaletteCleanupModal.open(() => this.reloadAfterLessonChange());
    },

    inspectLesson(lessonId) {
        LessonImpactModal.open(lessonId, () => this.reloadAfterLessonChange());
    },

    /**
     * Ξαναφόρτωσε πρόγραμμα + μαθήματα μετά από αλλαγή ωρών ή διαγραφή. Δεν
     * αρκεί το refreshPalette: η διαγραφή μαθήματος αφαιρεί και τοποθετημένες
     * ώρες, άρα αλλάζει και το πλέγμα.
     */
    async reloadAfterLessonChange() {
        const ctx = this._paletteCtx;
        if (!ctx) return;
        try {
            const [fresh, lessons] = await Promise.all([
                API.solver.getSolution(ctx.solutionId),
                API.lessons.list().catch(() => this._lessons || []),
            ]);
            this._lessons = lessons;
            // Ίδιος πίνακας με αυτόν που κρατά το πλέγμα — ενημέρωση στη θέση του.
            ctx.slots.length = 0;
            Array.prototype.push.apply(ctx.slots, fresh.slots);
            if (this._rerenderGrid) this._rerenderGrid();
            this.refreshPalette();
        } catch (err) {
            Toast.error('Η ανανέωση απέτυχε: ' + err.message);
        }
    },

    async syncLessonSlots(lessonId) {
        const ctx = this._paletteCtx;
        if (!ctx) return;
        try {
            const res = await API.solver.syncLessonSlots(ctx.solutionId, lessonId);
            const fresh = await API.solver.getSolution(ctx.solutionId);
            ctx.slots.length = 0;
            Array.prototype.push.apply(ctx.slots, fresh.slots);
            Toast.success(res.message || 'Οι ώρες προστέθηκαν στην παλέτα');
            this.refreshPalette();
        } catch (err) {
            Toast.error('Αποτυχία συμπλήρωσης ωρών: ' + err.message);
        }
    },

    _esc(s) {
        return TimetableHelpers.esc(s);
    },

};
