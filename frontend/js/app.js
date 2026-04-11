/**
 * EduScheduler — Main Application Controller
 * Handles SPA-style navigation and view lifecycle.
 */
const App = {
    _currentView: 'dashboard',
    _currentSolutionId: null,

    views: {
        dashboard: { title: 'Πίνακας Ελέγχου', renderer: DashboardView },
        periods: { title: 'Ώρες / Περίοδοι', renderer: PeriodsView },
        teachers: { title: 'Καθηγητές', renderer: TeachersView },
        subjects: { title: 'Μαθήματα', renderer: SubjectsView },
        students: { title: 'Μαθητές', renderer: StudentsView },
        classes: { title: 'Τάξεις', renderer: ClassesView },
        classrooms: { title: 'Αίθουσες', renderer: ClassroomsView },
        lessons: { title: 'Μαθήματα-Κάρτες', renderer: LessonsView },
        constraints: { title: 'Περιορισμοί', renderer: ConstraintsView },
        generate: { title: 'Δημιουργία Ωρολογίου', renderer: GenerateView },
        timetable: { title: 'Ωρολόγιο Πρόγραμμα', renderer: TimetableView },
        settings: { title: 'Ρυθμίσεις', renderer: SettingsView },
    },

    init() {
        Modal.init();
        this._bindNavigation();
        this._bindMenuToggle();
        this.navigateTo('dashboard');
    },

    navigateTo(viewName) {
        const view = this.views[viewName];
        if (!view) return;

        this._currentView = viewName;

        // Update active nav item
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.view === viewName);
        });

        // Update page title
        document.getElementById('page-title').textContent = view.title;

        // Render view
        const contentArea = document.getElementById('content-area');
        contentArea.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>';

        // Close mobile sidebar
        document.getElementById('sidebar').classList.remove('open');

        // Render with slight delay for transition feel
        requestAnimationFrame(() => {
            view.renderer.render(contentArea);
        });
    },

    _bindNavigation() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const viewName = item.dataset.view;
                if (viewName) this.navigateTo(viewName);
            });
        });
    },

    _bindMenuToggle() {
        document.getElementById('menu-toggle').addEventListener('click', () => {
            document.getElementById('sidebar').classList.toggle('open');
        });
    },
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => App.init());
