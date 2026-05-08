/**
 * Generate View — Launch solver and see results.
 */
const GenerateView = {
    async render(container) {
        container.innerHTML = `
            <div class="card solver-panel">
                <div class="solver-icon">🧠</div>
                <h2 style="font-size: var(--font-size-2xl); margin-bottom: var(--space-sm);">
                    Δημιουργία Ωρολογίου
                </h2>
                <p class="text-muted mb-lg">
                    Ο solver θα αναλύσει τα δεδομένα σας και θα δημιουργήσει
                    αυτόματα το βέλτιστο ωρολόγιο πρόγραμμα.
                </p>

                <div class="form-group" style="max-width: 400px; margin: 0 auto var(--space-md);">
                    <label class="form-label">Όνομα Προγράμματος</label>
                    <input class="form-input" id="gen-name" value="Πρόγραμμα ${new Date().toLocaleDateString('el-GR')}">
                </div>

                <div class="form-group" style="max-width: 400px; margin: 0 auto var(--space-md);">
                    <label class="form-label">Μέγιστος Χρόνος (δευτερόλεπτα)</label>
                    <input class="form-input" id="gen-time" type="number" min="10" max="600" value="120">
                </div>

                <div class="form-group" style="max-width: 400px; margin: 0 auto var(--space-md);">
                    <label class="form-label">Λειτουργία</label>
                    <select class="form-select" id="gen-mode">
                        <option value="strict" selected>Strict — όλα ή τίποτα</option>
                        <option value="permissive">Permissive — βάλε όσα μπορείς</option>
                    </select>
                    <p class="text-muted" style="font-size: 0.85em; margin-top: 0.5rem; text-align: left;">
                        <b>Strict</b>: αν δεν χωράνε όλες οι ώρες → INFEASIBLE.<br>
                        <b>Permissive</b>: τοποθετεί ό,τι χωράει· τα υπόλοιπα πάνε στο
                        🅿️ Parking Lot (κάτω από το πρόγραμμα) και τα τοποθετείς χειροκίνητα με drag.
                    </p>
                </div>

                <div class="form-group" style="max-width: 400px; margin: 0 auto var(--space-lg);">
                    <label class="form-label">Warm start (προαιρετικό)</label>
                    <select class="form-select" id="gen-warmstart">
                        <option value="">— Καμία (πλήρης αναζήτηση) —</option>
                    </select>
                    <p class="text-muted" style="font-size: 0.85em; margin-top: 0.5rem; text-align: left;">
                        Δίνει στον solver την προηγούμενη λύση σαν <b>πρόταση</b>
                        (όχι περιορισμός). Βοηθάει όταν έχεις κάνει λίγες αλλαγές
                        και θες γρηγορότερο αποτέλεσμα.
                    </p>
                </div>

                <div style="display:flex; gap:var(--space-sm); justify-content:center; flex-wrap:wrap;">
                    <button class="btn btn-secondary btn-lg" id="gen-feasibility">
                        🔍 Έλεγχος Εφικτότητας
                    </button>
                    <button class="btn btn-success btn-lg" id="gen-start">
                        🚀 Εκκίνηση Δημιουργίας
                    </button>
                </div>

                <div class="hidden" id="gen-feasibility-result" style="margin-top:var(--space-md); text-align:left; max-width:600px; margin-left:auto; margin-right:auto;"></div>

                <div class="solver-status hidden" id="gen-status">
                    <div class="progress-bar-track">
                        <div class="progress-bar-fill" id="gen-progress" style="width: 0%"></div>
                    </div>
                    <p class="text-muted mt-sm" id="gen-message">Αναμονή...</p>
                </div>

                <div class="solver-stats hidden" id="gen-stats"></div>
            </div>

            <div class="card mt-lg">
                <div class="card-header">
                    <h2 class="card-title">📋 Ιστορικό Λύσεων</h2>
                </div>
                <div id="solutions-list">
                    <div class="loading-spinner"><div class="spinner"></div></div>
                </div>
            </div>
        `;

        document.getElementById('gen-start').addEventListener('click', () => this._startGeneration());
        document.getElementById('gen-feasibility').addEventListener('click', () => this._runFeasibilityCheck());
        this._loadSolutions();
    },

    async _runFeasibilityCheck() {
        const btn = document.getElementById('gen-feasibility');
        const resultDiv = document.getElementById('gen-feasibility-result');

        btn.disabled = true;
        btn.textContent = '⏳ Έλεγχος...';
        resultDiv.classList.add('hidden');

        try {
            const report = await API.solver.feasibilityCheck();

            const verdict = report.feasible
                ? '<span style="color:var(--success,#10B981)">✅ Εφικτό</span>'
                : '<span style="color:var(--danger,#EF4444)">❌ Μη Εφικτό</span>';

            const stats = report.stats || {};
            const loadPct = stats.load_factor != null
                ? Math.round(stats.load_factor * 100)
                : '—';

            const errorsHtml = report.errors.length
                ? `<div style="margin-top:var(--space-sm);">
                       <b>Σφάλματα (${report.errors.length}):</b>
                       <ul style="margin:0.4em 0 0 1.4em; color:var(--danger,#EF4444);">
                           ${report.errors.map(e => `<li>${this._escape(e)}</li>`).join('')}
                       </ul>
                   </div>`
                : '';

            const warningsHtml = report.warnings.length
                ? `<div style="margin-top:var(--space-sm);">
                       <b>Προειδοποιήσεις (${report.warnings.length}):</b>
                       <ul style="margin:0.4em 0 0 1.4em; color:var(--warning,#F59E0B);">
                           ${report.warnings.map(w => `<li>${this._escape(w)}</li>`).join('')}
                       </ul>
                   </div>`
                : '';

            resultDiv.innerHTML = `
                <div class="card" style="padding:var(--space-md);">
                    <div style="font-size:1.1em; margin-bottom:var(--space-sm);">${verdict}</div>
                    <div style="font-size:0.9em; color:var(--text-muted, #6B7280);">
                        Φόρτος: <b>${stats.total_periods_needed ?? '—'} / ${stats.total_slots_available ?? '—'}</b> slots
                        (${loadPct}%) • ${stats.total_lessons ?? 0} μαθήματα,
                        ${stats.total_teachers ?? 0} καθηγητές, ${stats.total_classes ?? 0} τάξεις
                    </div>
                    ${errorsHtml}
                    ${warningsHtml}
                    ${report.feasible && !report.warnings.length
                        ? '<p style="color:var(--success,#10B981); margin-top:var(--space-sm);">Όλα τα checks πέρασαν — μπορείς να τρέξεις τον solver.</p>'
                        : ''}
                </div>
            `;
            resultDiv.classList.remove('hidden');

            if (report.feasible) {
                Toast.success('Το πρόβλημα φαίνεται εφικτό');
            } else {
                Toast.error(`${report.errors.length} σφάλματα — ο solver θα αποτύχει`);
            }
        } catch (err) {
            Toast.error(err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = '🔍 Έλεγχος Εφικτότητας';
        }
    },

    _escape(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    },

    _populateWarmStartOptions(solutions) {
        const sel = document.getElementById('gen-warmstart');
        if (!sel) return;
        const previous = sel.value;
        const usable = solutions.filter(s =>
            s.status === 'optimal' || s.status === 'feasible'
        );
        sel.innerHTML = '<option value="">— Καμία (πλήρης αναζήτηση) —</option>'
            + usable.map(s => {
                const date = s.created_at
                    ? new Date(s.created_at).toLocaleString('el-GR')
                    : '—';
                return `<option value="${s.id}">${this._escape(s.name)} (${date})</option>`;
            }).join('');
        // Preserve user's previous selection if still present
        if (previous && usable.some(s => String(s.id) === previous)) {
            sel.value = previous;
        }
    },

    async _startGeneration() {
        const name = document.getElementById('gen-name').value.trim() || 'Πρόγραμμα';
        const maxTime = parseInt(document.getElementById('gen-time').value) || 120;
        const mode = document.getElementById('gen-mode').value || 'strict';
        const warmStartRaw = document.getElementById('gen-warmstart')?.value;
        const warmStartId = warmStartRaw ? parseInt(warmStartRaw) : null;

        const startBtn = document.getElementById('gen-start');
        const statusDiv = document.getElementById('gen-status');
        const statsDiv = document.getElementById('gen-stats');

        startBtn.disabled = true;
        startBtn.textContent = '⏳ Δημιουργία σε εξέλιξη...';
        statusDiv.classList.remove('hidden');
        statsDiv.classList.add('hidden');

        // Animate progress bar
        const progress = document.getElementById('gen-progress');
        const message = document.getElementById('gen-message');
        let width = 0;
        const progressInterval = setInterval(() => {
            width = Math.min(width + Math.random() * 3, 90);
            progress.style.width = `${width}%`;
        }, 500);

        message.textContent = `Ο solver εργάζεται (${mode} mode)...`;

        try {
            const payload = { name, max_time_seconds: maxTime, mode };
            if (warmStartId) payload.warm_start_from_solution_id = warmStartId;
            const result = await API.solver.generate(payload);

            clearInterval(progressInterval);
            progress.style.width = '100%';

            if (result.status === 'optimal' || result.status === 'feasible') {
                message.textContent = result.message;
                if (result.unplaced_count > 0) {
                    Toast.info(result.message);
                } else {
                    Toast.success(result.message);
                }

                statsDiv.classList.remove('hidden');
                const placed = result.placed_count || 0;
                const unplaced = result.unplaced_count || 0;
                statsDiv.innerHTML = `
                    <div class="solver-stat">
                        <div class="value">${result.status === 'optimal' ? '✅' : '⚡'}</div>
                        <div class="label">Κατάσταση</div>
                    </div>
                    <div class="solver-stat">
                        <div class="value">${placed}</div>
                        <div class="label">Τοποθετήθηκαν</div>
                    </div>
                    <div class="solver-stat" style="${unplaced > 0 ? 'color: var(--warning, #F59E0B);' : ''}">
                        <div class="value">${unplaced}</div>
                        <div class="label">${unplaced > 0 ? '🅿️ Στο Parking Lot' : 'Στο Parking Lot'}</div>
                    </div>
                    <div class="solver-stat">
                        <div class="value">${result.score?.toFixed(0) || '0'}</div>
                        <div class="label">Σκορ</div>
                    </div>
                `;
            } else {
                message.textContent = result.message;
                Toast.error(result.message);
            }
        } catch (err) {
            clearInterval(progressInterval);
            message.textContent = `Σφάλμα: ${err.message}`;
            Toast.error(err.message);
        }

        startBtn.disabled = false;
        startBtn.textContent = '🚀 Εκκίνηση Δημιουργίας';
        this._loadSolutions();
    },

    async _loadSolutions() {
        const listEl = document.getElementById('solutions-list');
        try {
            const solutions = await API.solver.listSolutions();
            this._populateWarmStartOptions(solutions);
            if (!solutions.length) {
                listEl.innerHTML = '<p class="text-muted text-center">Δεν υπάρχουν λύσεις ακόμα</p>';
                return;
            }

            listEl.innerHTML = `
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Όνομα</th>
                            <th>Κατάσταση</th>
                            <th>Σκορ</th>
                            <th>Ημερομηνία</th>
                            <th style="text-align:right">Ενέργειες</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${solutions.map(s => `
                            <tr>
                                <td>${s.name}</td>
                                <td><span class="constraint-badge ${s.status === 'optimal' ? 'soft' : 'hard'}">${s.status}</span></td>
                                <td>${s.score?.toFixed(0) || '—'}</td>
                                <td>${s.created_at ? new Date(s.created_at).toLocaleString('el-GR') : '—'}</td>
                                <td class="actions">
                                    <button class="btn btn-sm btn-primary view-sol" data-id="${s.id}">📋 Προβολή</button>
                                    <button class="btn btn-sm btn-danger del-sol" data-id="${s.id}">🗑️</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;

            listEl.querySelectorAll('.view-sol').forEach(btn => {
                btn.addEventListener('click', () => {
                    App._currentSolutionId = parseInt(btn.dataset.id);
                    App.navigateTo('timetable');
                });
            });

            listEl.querySelectorAll('.del-sol').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        await API.solver.deleteSolution(parseInt(btn.dataset.id));
                        Toast.success('Η λύση διαγράφηκε');
                        this._loadSolutions();
                    } catch (err) {
                        Toast.error(err.message);
                    }
                });
            });
        } catch (err) {
            listEl.innerHTML = `<p class="text-muted">Σφάλμα: ${err.message}</p>`;
        }
    },
};
