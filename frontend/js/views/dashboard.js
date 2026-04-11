/**
 * Dashboard View — Overview statistics and quick actions.
 */
const DashboardView = {
    async render(container) {
        container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>`;

        try {
            const [teachers, subjects, classes, classrooms, lessons, solutions, students] = await Promise.all([
                API.teachers.list(),
                API.subjects.list(),
                API.classes.list(),
                API.classrooms.list(),
                API.lessons.list(),
                API.solver.listSolutions(),
                API.request('/students/')
            ]);

            const latestSolution = solutions?.[0];

            container.innerHTML = `
                <div class="stats-grid">
                    <div class="stat-card" data-navigate="teachers">
                        <div class="stat-icon blue">👨‍🏫</div>
                        <div class="stat-info">
                            <div class="stat-value">${teachers.length}</div>
                            <div class="stat-label">Καθηγητές</div>
                        </div>
                    </div>
                    <div class="stat-card" data-navigate="students">
                        <div class="stat-icon emerald">🎓</div>
                        <div class="stat-info">
                            <div class="stat-value">${students.length}</div>
                            <div class="stat-label">Μαθητές</div>
                        </div>
                    </div>
                    <div class="stat-card" data-navigate="classes">
                        <div class="stat-icon emerald">🏫</div>
                        <div class="stat-info">
                            <div class="stat-value">${classes.length}</div>
                            <div class="stat-label">Τμήματα</div>
                        </div>
                    </div>
                    <div class="stat-card" data-navigate="subjects">
                        <div class="stat-icon violet">📖</div>
                        <div class="stat-info">
                            <div class="stat-value">${subjects.length}</div>
                            <div class="stat-label">Μαθήματα</div>
                        </div>
                    </div>
                    <div class="stat-card" data-navigate="classrooms">
                        <div class="stat-icon amber">🚪</div>
                        <div class="stat-info">
                            <div class="stat-value">${classrooms.length}</div>
                            <div class="stat-label">Αίθουσες</div>
                        </div>
                    </div>
                    <div class="stat-card" data-navigate="lessons">
                        <div class="stat-icon cyan">🃏</div>
                        <div class="stat-info">
                            <div class="stat-value">${lessons.length}</div>
                            <div class="stat-label">Μαθήματα-Κάρτες</div>
                        </div>
                    </div>
                    <div class="stat-card" data-navigate="timetable">
                        <div class="stat-icon rose">📋</div>
                        <div class="stat-info">
                            <div class="stat-value">${solutions.length}</div>
                            <div class="stat-label">Προγράμματα</div>
                        </div>
                    </div>
                </div>

                <div class="card mb-lg">
                    <div class="card-header">
                        <h2 class="card-title">🚀 Γρήγορη Εκκίνηση</h2>
                    </div>
                    <div class="quick-start-steps" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-top: 1rem;">
                        <div class="card" style="cursor: pointer; background: var(--surface-hover)" onclick="App.navigateTo('settings')">
                            <h3>1. Ρυθμίσεις</h3>
                            <p style="font-size: 0.9em; color: var(--text-secondary)">Βασικές παράμετροι και ωράρια.</p>
                        </div>
                        <div class="card" style="cursor: pointer; background: var(--surface-hover)" onclick="App.navigateTo('teachers')">
                            <h3>2. Καθηγητές & Ωράρια</h3>
                            <p style="font-size: 0.9em; color: var(--text-secondary)">Προσθήκη καθηγητών & διαθεσιμότητας.</p>
                        </div>
                        <div class="card" style="cursor: pointer; background: var(--surface-hover)" onclick="App.navigateTo('students')">
                            <h3>3. Μαθητές</h3>
                            <p style="font-size: 0.9em; color: var(--text-secondary)">Καταχώρηση πελατολογίου (προαιρετικό).</p>
                        </div>
                        <div class="card" style="cursor: pointer; background: var(--surface-hover)" onclick="App.navigateTo('classes')">
                            <h3>4. Τμήματα</h3>
                            <p style="font-size: 0.9em; color: var(--text-secondary)">Δημιουργία τμημάτων και προσθήκη μαθητών για έλεγχο επικαλύψεων (conflict detection).</p>
                        </div>
                        <div class="card" style="cursor: pointer; background: var(--surface-hover)" onclick="App.navigateTo('lessons')">
                            <h3>5. Μαθήματα (Κάρτες)</h3>
                            <p style="font-size: 0.9em; color: var(--text-secondary)">Ανάθεση: "Ο κ. Παπαδόπουλος διδάσκει Άλγεβρα στο Α1".</p>
                        </div>
                        <div class="card" style="cursor: pointer; background: var(--surface-hover)" onclick="App.navigateTo('constraints')">
                            <h3>6. Κανόνες</h3>
                            <p style="font-size: 0.9em; color: var(--text-secondary)">Συνθήκες πχ. "Κανένα κενό για τους καθηγητές".</p>
                        </div>
                        <div class="card highlight" style="cursor: pointer;" onclick="App.navigateTo('generate')">
                            <h3>7. Δημιουργία!</h3>
                            <p style="font-size: 0.9em; opacity: 0.9;">Εκκίνηση Αλγορίθμου Τεχνητής Νοημοσύνης.</p>
                        </div>
                    </div>
                </div>

                ${latestSolution ? \`
                <div class="card">
                    <div class="card-header">
                        <h2 class="card-title">📋 Τελευταίο Πρόγραμμα</h2>
                        <span class="constraint-badge ${latestSolution.status === 'optimal' ? 'soft' : 'hard'}">
                            ${latestSolution.status === 'optimal' ? 'Βέλτιστο' : latestSolution.status}
                        </span>
                    </div>
                    <p style="color: var(--text-secondary);">
                        <strong>${latestSolution.name}</strong> — 
                        ${latestSolution.created_at ? new Date(latestSolution.created_at).toLocaleString('el-GR') : ''}
                    </p>
                    <button class="btn btn-primary mt-md" id="view-latest">📋 Προβολή</button>
                </div>
                \` : ''}
            `;

            // Navigation from stat cards
            container.querySelectorAll('[data-navigate]').forEach(card => {
                card.addEventListener('click', () => {
                    App.navigateTo(card.dataset.navigate);
                });
            });

            // View latest timetable
            container.querySelector('#view-latest')?.addEventListener('click', () => {
                App.navigateTo('timetable');
            });

        } catch (err) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">⚠️</div>
                    <p class="empty-state-text">Σφάλμα σύνδεσης με τον server</p>
                    <p class="text-muted">${err.message}</p>
                </div>
            `;
        }
    },
};
