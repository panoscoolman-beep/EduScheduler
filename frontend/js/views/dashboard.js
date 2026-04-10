/**
 * Dashboard View — Overview statistics and quick actions.
 */
const DashboardView = {
    async render(container) {
        container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>`;

        try {
            const [teachers, subjects, classes, classrooms, lessons, solutions] = await Promise.all([
                API.teachers.list(),
                API.subjects.list(),
                API.classes.list(),
                API.classrooms.list(),
                API.lessons.list(),
                API.solver.listSolutions(),
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
                    <div class="stat-card" data-navigate="subjects">
                        <div class="stat-icon violet">📖</div>
                        <div class="stat-info">
                            <div class="stat-value">${subjects.length}</div>
                            <div class="stat-label">Μαθήματα</div>
                        </div>
                    </div>
                    <div class="stat-card" data-navigate="classes">
                        <div class="stat-icon emerald">🏫</div>
                        <div class="stat-info">
                            <div class="stat-value">${classes.length}</div>
                            <div class="stat-label">Τάξεις</div>
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
                    <div class="quick-start-steps">
                        <p style="color: var(--text-secondary); margin-bottom: var(--space-md);">
                            Ακολουθήστε αυτά τα βήματα για να δημιουργήσετε το πρώτο σας πρόγραμμα:
                        </p>
                        <ol style="color: var(--text-secondary); padding-left: var(--space-lg); line-height: 2.2;">
                            <li>Ρυθμίστε τις <strong>Ώρες / Περιόδους</strong> 🕐</li>
                            <li>Προσθέστε <strong>Καθηγητές</strong> & τη διαθεσιμότητά τους 👨‍🏫</li>
                            <li>Προσθέστε <strong>Μαθήματα</strong> 📖</li>
                            <li>Προσθέστε <strong>Τάξεις</strong> 🏫</li>
                            <li>Προσθέστε <strong>Αίθουσες</strong> 🚪</li>
                            <li>Δημιουργήστε <strong>Μαθήματα-Κάρτες</strong> (ποιος διδάσκει τι, σε ποια τάξη) 🃏</li>
                            <li>Ρυθμίστε τους <strong>Περιορισμούς</strong> ⚙️</li>
                            <li>Πατήστε <strong>Δημιουργία</strong> 🧠!</li>
                        </ol>
                    </div>
                </div>

                ${latestSolution ? `
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
                ` : ''}
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
