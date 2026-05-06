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

                <div class="form-group" style="max-width: 400px; margin: 0 auto var(--space-lg);">
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

                <button class="btn btn-success btn-lg" id="gen-start">
                    🚀 Εκκίνηση Δημιουργίας
                </button>

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
        this._loadSolutions();
    },

    async _startGeneration() {
        const name = document.getElementById('gen-name').value.trim() || 'Πρόγραμμα';
        const maxTime = parseInt(document.getElementById('gen-time').value) || 120;
        const mode = document.getElementById('gen-mode').value || 'strict';

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
            const result = await API.solver.generate({
                name, max_time_seconds: maxTime, mode,
            });

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
