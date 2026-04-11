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
                    <div class="card-header">
                        <h2 class="card-title">📋 ${solution.name}</h2>
                        <span class="constraint-badge ${solution.status === 'optimal' ? 'soft' : 'hard'}">
                            ${solution.status === 'optimal' ? 'Βέλτιστο' : solution.status}
                        </span>
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
            `;

            // Initial render
            const firstFilter = 'all';
            TimetableGrid.render('timetable-grid-view', solution.slots, periods, 5, 'class', firstFilter, solutionId);

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
};
