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
                            <button class="btn btn-secondary" id="tt-undo" title="Αναίρεση τελευταίας αλλαγής (Ctrl+Z)" style="margin-right:0.25rem" disabled>↩ Αναίρεση</button>
                            <button class="btn btn-secondary" id="tt-redo" title="Επανάληψη (Ctrl+Y)" style="margin-right:0.5rem" disabled>↪ Επανάληψη</button>
                            <button class="btn btn-secondary" id="tt-substitute" title="Βρες αντικαταστάτη για καθηγητή που λείπει" style="margin-right:0.5rem">👤 Αντικατάσταση</button>
                            <button class="btn btn-warning" id="tt-regen" title="Κράτα τα κλειδωμένα μαθήματα και ξανατρέξε τον solver για τα υπόλοιπα" style="margin-right:0.5rem">🔒 Lock & Regenerate</button>
                            <button class="btn btn-secondary" id="tt-compare" title="Σύγκρινε με άλλη λύση" style="margin-right:0.5rem">📊 Σύγκριση</button>
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
            TimetableGrid.render('timetable-grid-view', solution.slots, periods, daysCount,'class', firstFilter, solutionId);
            this._renderParkingLot('parking-lot-container', solution.slots, solutionId);

            // Event: Print
            document.getElementById('tt-print').addEventListener('click', () => {
                window.print();
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
                TimetableGrid.render('timetable-grid-view', solution.slots, periods, daysCount,e.target.value, 'all', solutionId);
            });

            // Event: Filter change
            document.getElementById('tt-filter').addEventListener('change', (e) => {
                const viewType = document.getElementById('tt-view-type').value;
                TimetableGrid.render('timetable-grid-view', solution.slots, periods, daysCount,viewType, e.target.value, solutionId);
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
        return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
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
        if (!data.affected_slots.length) {
            mountEl.innerHTML = `
                <p class="text-muted">
                    Ο καθηγητής δεν έχει προγραμματισμένα μαθήματα την ${dayLabel}.
                    Δεν χρειάζεται αντικατάσταση.
                </p>
            `;
            return;
        }

        const cards = data.affected_slots.map(slot => {
            const candidatesHtml = slot.candidates.length
                ? `<ul style="margin:0.4em 0 0 1.4em; padding:0;">
                       ${slot.candidates.slice(0, 5).map(c => `
                           <li style="margin-bottom:0.3em;">
                               <strong>${this._esc(c.name)}</strong>
                               <span class="text-muted" style="font-size:0.85em;">
                                 (score ${c.score})
                               </span>
                               <div style="font-size:0.85em; color:var(--text-muted);">
                                 ${this._esc(c.reasons.join(', '))}
                               </div>
                           </li>
                       `).join('')}
                   </ul>`
                : '<p class="text-muted" style="font-size:0.9em; margin:0.3em 0;">Κανείς διαθέσιμος αυτή την ώρα.</p>';

            const rescheduleHtml = slot.reschedule_options.length
                ? `<ul style="margin:0.4em 0 0 1.4em; padding:0; max-height:120px; overflow:auto;">
                       ${slot.reschedule_options.slice(0, 8).map(opt => {
                           const dayName = ['Δευ','Τρι','Τετ','Πεμ','Παρ','Σαβ','Κυρ'][opt.day_of_week];
                           return `<li>${dayName} • ${this._esc(opt.period_name || '?')}</li>`;
                       }).join('')}
                   </ul>`
                : '<p class="text-muted" style="font-size:0.9em; margin:0.3em 0;">Καμία ελεύθερη ώρα στην εβδομάδα.</p>';

            return `
                <div class="card" style="margin-bottom:1rem; padding:0.8rem 1rem;">
                    <div style="font-weight:600; margin-bottom:0.5rem;">
                        ${this._esc(slot.subject_name || '?')} —
                        ${this._esc(slot.class_name || '?')} •
                        ${this._esc(slot.period_name || '?')} •
                        ${this._esc(slot.classroom_name || '?')}
                    </div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem;">
                        <div>
                            <strong style="font-size:0.9em;">Αντικαταστάτες:</strong>
                            ${candidatesHtml}
                        </div>
                        <div>
                            <strong style="font-size:0.9em;">Εναλλακτικές ώρες ίδιας εβδομάδας:</strong>
                            ${rescheduleHtml}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        mountEl.innerHTML = `
            <div style="margin-bottom:1rem; padding:0.6rem 0.8rem;
                        background:var(--bg-secondary, #F3F4F6); border-radius:6px;">
                <strong>Σύνολο μαθημάτων που επηρεάζονται:</strong>
                ${data.stats.affected_count}
                — ${data.stats.with_candidates} με διαθέσιμους αντικαταστάτες
            </div>
            ${cards}
        `;
    },

    _renderCompareResult(result, mountEl) {
        if (!result.metrics?.length) {
            mountEl.innerHTML = '<p class="text-muted">Δεν επιστράφηκαν metrics.</p>';
            return;
        }

        const metricLabels = {
            score:               'Σκορ (penalty)',
            placed_count:        '✅ Τοποθετήθηκαν',
            unplaced_count:      '🅿️ Στο parking',
            teacher_gap_total:   'Παράθυρα καθηγητών (σύνολο)',
            workload_stddev:     'Ανισορροπία ωρών (σ)',
            avg_days_per_class:  'Μέσος όρος ημερών/τμήμα',
            max_days_per_class:  'Max ημέρες σε τμήμα',
            late_periods_used:   'Αργές ώρες (μετά τη μέση)',
        };

        const metricKeys = Object.keys(metricLabels);
        const winners = result.winners || {};

        const headerCells = result.metrics.map(m =>
            `<th>${this._esc(m.name)}</th>`
        ).join('');

        const rows = metricKeys.map(key => {
            const cells = result.metrics.map(m => {
                const value = m[key];
                const isWinner = winners[key] === m.solution_id;
                const display = value === null || value === undefined
                    ? '—'
                    : (typeof value === 'number' ? value : String(value));
                return `<td style="${isWinner ? 'background:#D1FAE5; font-weight:600;' : ''}">
                    ${display}${isWinner ? ' ⭐' : ''}
                </td>`;
            }).join('');
            return `<tr><td><strong>${metricLabels[key]}</strong></td>${cells}</tr>`;
        }).join('');

        mountEl.innerHTML = `
            <p class="text-muted" style="font-size:0.85em; margin-bottom:0.5rem;">
                ⭐ = καλύτερη τιμή για κάθε metric (lower is better, εκτός από Τοποθετήθηκαν).
            </p>
            <table class="data-table" style="font-size:0.9em;">
                <thead>
                    <tr><th>Metric</th>${headerCells}</tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    },
};
