/**
 * EduScheduler — Main Application Controller
 * Handles SPA-style navigation and view lifecycle.
 *
 * Κάθε σελίδα έχει δική της διεύθυνση (#timetable, #today, …), ώστε το
 * «Πίσω» του κινητού/browser να γυρίζει στην προηγούμενη σελίδα αντί να
 * βγαίνει από την εφαρμογή, και να μπαίνει σε σελιδοδείκτη.
 */
const App = {
    _currentView: 'dashboard',
    _currentSolutionId: null,
    _renderToken: 0,
    _terms: [],

    views: {
        dashboard: { title: 'Πίνακας Ελέγχου', renderer: DashboardView },
        terms: { title: 'Σενάρια Ωραρίου', renderer: TermsView },
        periods: { title: 'Ώρες / Περίοδοι', renderer: PeriodsView },
        teachers: { title: 'Καθηγητές', renderer: TeachersView },
        subjects: { title: 'Μαθήματα', renderer: SubjectsView },
        students: { title: 'Μαθητές', renderer: StudentsView },
        classes: { title: 'Τμήματα', renderer: ClassesView },
        classrooms: { title: 'Αίθουσες', renderer: ClassroomsView },
        lessons: { title: 'Μαθήματα-Κάρτες', renderer: LessonsView },
        constraints: { title: 'Περιορισμοί', renderer: ConstraintsView },
        generate: { title: 'Δημιουργία Ωρολογίου', renderer: GenerateView },
        timetable: { title: 'Ωρολόγιο Πρόγραμμα', renderer: TimetableView },
        today: { title: 'Σήμερα', renderer: TodayView },
        settings: { title: 'Ρυθμίσεις', renderer: SettingsView },
    },

    // Μενού «Περισσότερα» του κινητού — ίδιες ομάδες με την πλαϊνή μπάρα.
    MENU_GROUPS: [
        { title: 'Πρόγραμμα', items: [
            ['lessons', '🃏', 'Μαθήματα-Κάρτες'], ['generate', '🧠', 'Δημιουργία'],
            ['terms', '🗂️', 'Σενάρια'], ['constraints', '📏', 'Περιορισμοί'],
        ] },
        { title: 'Δεδομένα', items: [
            ['teachers', '👨‍🏫', 'Καθηγητές'], ['classes', '🏫', 'Τμήματα'],
            ['classrooms', '🚪', 'Αίθουσες'], ['subjects', '📖', 'Μαθήματα'], ['periods', '🕐', 'Ώρες'],
        ] },
        { title: 'Σύστημα', items: [
            ['dashboard', '📊', 'Πίνακας Ελέγχου'], ['settings', '🛠️', 'Ρυθμίσεις'], ['@appearance', '🎨', 'Εμφάνιση'],
        ] },
    ],
    BOTTOM_VIEWS: ['today', 'timetable', 'students'],

    // Σήμα «Χρειάζεται προσοχή» στα «Περισσότερα» (κινητό) και στον «Πίνακα Ελέγχου» (πλαϊνή).
    ATTENTION_STALE_MS: 60 * 1000,       // στην πλοήγηση ξαναμετρά μόνο αν πέρασε τόσο
    ATTENTION_EVERY_MS: 5 * 60 * 1000,   // και κάθε τόσο έτσι κι αλλιώς
    _attention: { at: 0, count: 0, busy: false, again: false },

    init() {
        VersionCheck.start();
        Modal.init();
        this._bindNavigation();
        this._bindMenuToggle();
        this._bindTermSelector();
        this._buildMoreSheet();
        this.refreshTermSelector();
        window.addEventListener('popstate', () => this._onPopState());
        // …/#today → κατευθείαν στο «Σήμερα» (σελιδοδείκτης κινητού / εγκατεστημένη εφαρμογή).
        this.navigateTo(this.viewFromHash(window.location.hash) || 'dashboard', { history: 'replace' });
        setInterval(() => this.refreshAttention({ force: true }), this.ATTENTION_EVERY_MS);
    },

    /** Γράφει το σήμα (0 = κρυφό) — ό,τι μετρά ο Πίνακας Ελέγχου στο «Χρειάζεται προσοχή». */
    setAttentionCount(n) {
        this._attention.at = Date.now();
        this._attention.count = n;
        const what = n === 1 ? '1 θέμα χρειάζεται προσοχή' : `${n} θέματα χρειάζονται προσοχή`;
        [['bn-more-badge', 'bn-more', 'Περισσότερα'], ['nav-attn-badge', 'nav-dashboard', 'Πίνακας Ελέγχου']]
            .forEach(([badgeId, itemId, name]) => {
                const badge = document.getElementById(badgeId);
                const item = document.getElementById(itemId);
                if (badge) { badge.textContent = n > 0 ? String(n) : ''; badge.hidden = !(n > 0); }
                if (item) {
                    if (n > 0) item.setAttribute('aria-label', `${name} — ${what}`);
                    else item.removeAttribute('aria-label');
                }
            });
    },

    /**
     * Ξαναμετρά το σήμα στο παρασκήνιο — ποτέ δεν καθυστερεί την πλοήγηση. Στον
     * Πίνακα Ελέγχου το μετρά η ίδια η σελίδα. force: κάτι άλλαξε (δημοσίευση,
     * εισαγωγή από CRM, λύση) ή πέρασε η ώρα.
     */
    refreshAttention({ force = false } = {}) {
        const a = this._attention;
        if (!force && (this._currentView === 'dashboard' || Date.now() - a.at < this.ATTENTION_STALE_MS)) return;
        if (a.busy) { a.again = a.again || force; return; }
        a.busy = true;
        DashboardView.attentionCount()
            .then(n => this.setAttentionCount(n))
            .catch(() => { /* χωρίς δίκτυο: μένει το προηγούμενο σήμα */ })
            .finally(() => {
                a.busy = false;
                if (a.again) { a.again = false; this.refreshAttention({ force: true }); }
            });
    },

    /** «#timetable» → 'timetable' (μόνο γνωστές σελίδες). */
    viewFromHash(hash) {
        let v = String(hash || '').replace(/^#\/?/, '');
        try { v = decodeURIComponent(v); } catch (_) { /* άκυρο % */ }
        return Object.prototype.hasOwnProperty.call(this.views, v) ? v : null;
    },

    _onPopState() {
        if (typeof BackGuard !== 'undefined' && BackGuard.handlePop()) return;
        const v = this.viewFromHash(window.location.hash) || 'dashboard';
        if (v !== this._currentView) this.navigateTo(v, { history: 'none' });
    },

    _bindTermSelector() {
        const sel = document.getElementById('term-selector');
        if (!sel) return;
        sel.addEventListener('change', () => {
            const id = parseInt(sel.value);
            const current = this._terms.find(t => t.is_active);
            // Επιστροφή στο ενεργό μέχρι να επιβεβαιωθεί η αλλαγή.
            if (current) sel.value = String(current.id);
            if (id && (!current || id !== current.id)) this.requestTermChange(id);
        });
    },

    /**
     * Αλλαγή ενεργού σεναρίου — με επιβεβαίωση: αλλάζει ό,τι βλέπουν ΟΛΕΣ οι
     * σελίδες (και σε άλλες συσκευές), όχι μόνο αυτή.
     */
    requestTermChange(termId) {
        const target = this._terms.find(t => t.id === termId);
        const current = this._terms.find(t => t.is_active);
        if (!target) return;
        const esc = DataTable.esc;
        Modal.open('🗂️ Αλλαγή σεναρίου', `
            <p>Να γίνει ενεργό το «<b>${esc(target.name)}</b>»${current ? ` αντί για το «${esc(current.name)}»` : ''};</p>
            <p class="text-muted" style="font-size:0.85rem; margin-top:0.5rem">
                Όλες οι σελίδες (Ωρολόγιο, Σήμερα, Κάρτες…) θα δείχνουν το νέο σενάριο,
                και σε άλλες συσκευές. Τίποτα δεν σβήνεται — αλλάζεις ξανά όποτε θες.
            </p>`,
        async () => {
            try {
                await API.terms.activate(termId);
                Modal.close();
                Toast.success(`Ενεργό σενάριο: «${esc(target.name)}»`);
                await this.refreshTermSelector();
                this.navigateTo(this._currentView, { history: 'none' });  // re-render στο νέο σενάριο
            } catch (err) {
                Toast.error(esc(err.message));
                await this.refreshTermSelector();
            }
        }, { saveText: 'Αλλαγή σεναρίου', confirmDiscard: false });
    },

    /** Repopulate the top-bar scenario selector from the backend. */
    async refreshTermSelector() {
        const sel = document.getElementById('term-selector');
        if (!sel) return;
        const wrap = sel.closest('.topbar-term');
        try {
            const terms = await API.terms.list();
            this._terms = terms || [];
            sel.innerHTML = this._terms
                .map(t => `<option value="${t.id}" ${t.is_active ? 'selected' : ''}>${(t.name || '').replace(/</g, '&lt;')}</option>`)
                .join('');
            sel.style.display = this._terms.length ? '' : 'none';
            if (wrap) wrap.style.display = this._terms.length ? '' : 'none';
        } catch (err) {
            this._terms = [];
            sel.style.display = 'none';  // backend without terms (pre-migration) → hide gracefully
            if (wrap) wrap.style.display = 'none';
        }
        this._renderMoreSheetTerm();
    },

    navigateTo(viewName, { history: mode = 'push' } = {}) {
        const view = this.views[viewName];
        if (!view) return;

        // Ένα ανοιχτό παράθυρο/μενού δεν έχει νόημα πάνω από νέα σελίδα.
        this.closeMoreSheet({ silent: true });
        if (typeof Modal !== 'undefined' && Modal.isOpen && Modal.isOpen()) Modal.close();

        // Εκκρεμής ενέργεια άλλης σελίδας (π.χ. ο χρήστης έφυγε πριν φορτώσει) — πετιέται.
        if (this._pending && this._pending.view !== viewName) this._pending = null;
        this._currentView = viewName;
        if (mode !== 'none') this._writeHistory(viewName, mode);

        // Update active nav item (πλαϊνή μπάρα + κάτω μπάρα)
        document.querySelectorAll('.nav-item[data-view]').forEach(item => {
            item.classList.toggle('active', item.dataset.view === viewName);
            if (item.dataset.view === viewName) item.setAttribute('aria-current', 'page');
            else item.removeAttribute('aria-current');
        });
        document.querySelectorAll('.bottom-nav-item[data-nav]').forEach(item => {
            const on = item.dataset.nav === viewName;
            item.classList.toggle('active', on);
            if (on) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current');
        });
        document.getElementById('bn-more')?.classList.toggle('active', !this.BOTTOM_VIEWS.includes(viewName));
        document.body.dataset.view = viewName;

        // Update page title
        document.getElementById('page-title').textContent = view.title;

        // Render view
        const contentArea = document.getElementById('content-area');
        contentArea.innerHTML = '<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>';
        contentArea.scrollTop = 0;

        // Close mobile sidebar
        document.getElementById('sidebar').classList.remove('open');

        // Render with slight delay for transition feel. Σφάλμα που δεν πιάνει η
        // ίδια η σελίδα (π.χ. αποτυχία φόρτωσης) → μήνυμα και «Δοκίμασε ξανά»
        // αντί για ατελείωτο «Φόρτωση...».
        const token = ++this._renderToken;
        requestAnimationFrame(() => {
            Promise.resolve()
                .then(() => view.renderer.render(contentArea))
                .catch(err => {
                    if (token !== this._renderToken || this._currentView !== viewName) return;
                    this.renderError(contentArea, err, () => this.navigateTo(viewName, { history: 'none' }));
                });
        });
        this.refreshAttention();
    },

    /**
     * Πήγαινε σε σελίδα και κάνε εκεί μια ενέργεια όταν φορτώσει (π.χ. από τον
     * Πίνακα Ελέγχου: «📢 Δημοσίευση» → Ωρολόγιο + παράθυρο δημοσίευσης).
     */
    openPending(viewName, action, solutionId = null) {
        this._pending = { view: viewName, action, solutionId };
        this.navigateTo(viewName);
    },

    /** Το πρόγραμμα που ζήτησε η εκκρεμής ενέργεια (χωρίς να την καταναλώσει). */
    pendingSolution(viewName) {
        const p = this._pending;
        return (p && p.view === viewName && p.solutionId != null) ? p.solutionId : null;
    },

    /** Η σελίδα ρωτά αν έχει ενέργεια να κάνει (μία φορά). */
    takePending(viewName) {
        const p = this._pending;
        if (!p || p.view !== viewName) return null;
        this._pending = null;
        return p.action;
    },

    _writeHistory(viewName, mode) {
        const hash = '#' + viewName;
        const url = window.location.pathname + window.location.search + hash;
        const replaceMarker = typeof BackGuard !== 'undefined' && BackGuard.takeMarker();
        try {
            if (replaceMarker && window.location.hash === hash) {
                // Ίδια σελίδα από το μενού: η εγγραφή του μενού απλώς φεύγει — αλλιώς
                // το επόμενο «Πίσω» θα «έμενε» στην ίδια σελίδα.
                BackGuard.dropMarker();
            } else if (mode === 'replace' || replaceMarker) {
                window.history.replaceState({ view: viewName }, '', url);
            } else if (window.location.hash !== hash) {
                window.history.pushState({ view: viewName }, '', url);
            }
        } catch (_) { /* π.χ. sandboxed iframe — η σελίδα αλλάζει έτσι κι αλλιώς */ }
    },

    /** Κοινή οθόνη σφάλματος με «Δοκίμασε ξανά». */
    renderError(container, err, retry) {
        const msg = DataTable.esc((err && err.message) || 'Άγνωστο σφάλμα');
        container.innerHTML = `
            <div class="empty-state" role="alert">
                <div class="empty-state-icon">⚠️</div>
                <p class="empty-state-text">Δεν φορτώθηκε η σελίδα</p>
                <p class="text-muted" style="margin-bottom:1rem">${msg}</p>
                <button class="btn btn-primary" data-retry>↻ Δοκίμασε ξανά</button>
            </div>`;
        container.querySelector('[data-retry]')?.addEventListener('click', retry);
    },

    _bindNavigation() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                if (item.dataset.action === 'appearance') { this.openAppearance(); return; }
                const viewName = item.dataset.view;
                if (viewName) this.navigateTo(viewName);
            });
        });
        document.querySelectorAll('.bottom-nav-item[data-nav]').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                this.navigateTo(item.dataset.nav);
            });
        });
        document.getElementById('bn-more')?.addEventListener('click', () => {
            if (this.isMoreSheetOpen()) this.closeMoreSheet();
            else this.openMoreSheet();
        });
    },

    _bindMenuToggle() {
        document.getElementById('menu-toggle').addEventListener('click', () => {
            document.getElementById('sidebar').classList.toggle('open');
        });
    },

    // ─── Μενού «Περισσότερα» (κινητό) ─────────────────────────────────
    _buildMoreSheet() {
        const sheet = document.getElementById('more-sheet');
        if (!sheet) return;
        const esc = DataTable.esc;
        const tile = ([view, icon, label]) => view.startsWith('@')
            ? `<button type="button" class="sheet-tile" data-action="${view.slice(1)}"><span class="sheet-tile-icon" aria-hidden="true">${icon}</span><span>${esc(label)}</span></button>`
            : `<a href="#${view}" class="sheet-tile" data-sheet-view="${view}"><span class="sheet-tile-icon" aria-hidden="true">${icon}</span><span>${esc(label)}</span></a>`;
        sheet.innerHTML = `
            <div class="sheet-handle" aria-hidden="true"></div>
            <div class="sheet-header">
                <h2 class="sheet-title" id="more-sheet-title">Μενού</h2>
                <button type="button" class="btn btn-ghost btn-icon" data-sheet-close aria-label="Κλείσιμο">✕</button>
            </div>
            <div class="sheet-term" id="more-sheet-term"></div>
            ${this.MENU_GROUPS.map(g => `
                <section class="sheet-group">
                    <h3 class="sheet-group-title">${esc(g.title)}</h3>
                    <div class="sheet-grid">${g.items.map(tile).join('')}</div>
                </section>`).join('')}`;
        sheet.addEventListener('click', (e) => {
            if (e.target.closest('[data-sheet-close]')) { this.closeMoreSheet(); return; }
            const viewLink = e.target.closest('[data-sheet-view]');
            if (viewLink) { e.preventDefault(); this.navigateTo(viewLink.dataset.sheetView); return; }
            const action = e.target.closest('[data-action]')?.dataset.action;
            if (action === 'appearance') { this.closeMoreSheet({ silent: true }); this.openAppearance(); return; }
            const termBtn = e.target.closest('[data-term-id]');
            if (termBtn) {
                const id = Number(termBtn.dataset.termId);
                this.closeMoreSheet({ silent: true });
                this.requestTermChange(id);
            }
        });
        document.getElementById('more-sheet-backdrop')?.addEventListener('click', () => this.closeMoreSheet());
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isMoreSheetOpen() && !(Modal.isOpen && Modal.isOpen())) this.closeMoreSheet();
        });
    },

    /** Σενάρια μέσα στο μενού: το ενεργό με ✓, τα άλλα αλλάζουν με επιβεβαίωση. */
    _renderMoreSheetTerm() {
        const box = document.getElementById('more-sheet-term');
        if (!box) return;
        const esc = DataTable.esc;
        if (!this._terms.length) { box.innerHTML = ''; return; }
        const active = this._terms.find(t => t.is_active);
        const others = this._terms.filter(t => !t.is_active);
        box.innerHTML = `
            <div class="sheet-term-row">
                <span class="text-muted">🗂️ Σενάριο</span>
                <b>${esc(active ? active.name : '—')}</b>
            </div>
            ${others.length ? `<details class="sheet-term-other">
                <summary>Αλλαγή σεναρίου…</summary>
                <div class="sheet-term-list">${others.map(t =>
                    `<button type="button" class="btn btn-secondary" data-term-id="${t.id}">${esc(t.name)}</button>`).join('')}</div>
            </details>` : ''}`;
    },

    isMoreSheetOpen() {
        const sheet = document.getElementById('more-sheet');
        return Boolean(sheet && !sheet.hidden);
    },

    openMoreSheet() {
        const sheet = document.getElementById('more-sheet');
        const backdrop = document.getElementById('more-sheet-backdrop');
        if (!sheet || this.isMoreSheetOpen()) return;
        sheet.querySelectorAll('[data-sheet-view]').forEach(a =>
            a.classList.toggle('active', a.dataset.sheetView === this._currentView));
        sheet.hidden = false;
        if (backdrop) backdrop.hidden = false;
        requestAnimationFrame(() => {
            sheet.classList.add('open');
            backdrop?.classList.add('open');
        });
        document.getElementById('bn-more')?.setAttribute('aria-expanded', 'true');
        if (typeof BackGuard !== 'undefined') BackGuard.open('more', () => { this.closeMoreSheet({ fromBack: true }); return true; });
        sheet.querySelector('[data-sheet-close]')?.focus();
    },

    /** silent: κλείσιμο επειδή ακολουθεί πλοήγηση/παράθυρο (χωρίς animation). */
    closeMoreSheet({ silent = false, fromBack = false } = {}) {
        const sheet = document.getElementById('more-sheet');
        const backdrop = document.getElementById('more-sheet-backdrop');
        if (!sheet || !this.isMoreSheetOpen()) return;
        sheet.classList.remove('open');
        backdrop?.classList.remove('open');
        const hide = () => { sheet.hidden = true; if (backdrop) backdrop.hidden = true; };
        if (silent) hide(); else setTimeout(hide, 200);
        document.getElementById('bn-more')?.setAttribute('aria-expanded', 'false');
        if (!fromBack && typeof BackGuard !== 'undefined') BackGuard.closed('more');
    },

    // ─── 🎨 Εμφάνιση ανά συσκευή ─────────────────────────────────────
    openAppearance() {
        const current = Appearance.load();
        const esc = DataTable.esc;
        const swatches = Appearance.ACCENTS.map(a => `
            <button type="button" class="swatch${a.id === current.accent ? ' is-on' : ''}" data-accent="${a.id}"
                    aria-pressed="${a.id === current.accent}" title="${esc(a.label)}">
                <span class="swatch-dot" style="background:${a.swatch}"></span>
                <span class="swatch-label">${esc(a.label)}</span>
            </button>`).join('');
        const sizes = Appearance.SIZES.map(s => `
            <button type="button" class="seg-btn${s.id === current.size ? ' is-on' : ''}" data-size="${s.id}"
                    aria-pressed="${s.id === current.size}">${esc(s.label)}</button>`).join('');
        Modal.open('🎨 Εμφάνιση', `
            <p class="text-muted" style="font-size:0.85rem; margin-bottom:1rem">
                Μόνο για αυτή τη συσκευή — όπως η 🎨 Εμφάνιση του CRM.
            </p>
            <div class="form-group">
                <span class="form-label">Χρώμα</span>
                <div class="swatch-grid" id="ap-accents">${swatches}</div>
            </div>
            <div class="form-group">
                <span class="form-label">Μέγεθος γραμμάτων</span>
                <div class="seg" id="ap-sizes" role="group" aria-label="Μέγεθος γραμμάτων">${sizes}</div>
            </div>
            <div class="appearance-preview">
                <button type="button" class="btn btn-primary" tabindex="-1">📢 Δημοσίευση</button>
                <span class="status-chip ok">✓ Εφικτό</span>
                <span class="text-muted" style="font-size:0.85rem">Έτσι θα φαίνονται τα κουμπιά.</span>
            </div>`,
        () => Modal.close(), { saveText: 'Έτοιμο', confirmDiscard: false, cancelText: 'Κλείσιμο' });
        const body = document.getElementById('modal-body');
        const pick = (attr, value) => {
            const next = Appearance.save({ ...Appearance.load(), [attr]: value });
            Appearance.apply(next);
            body.querySelectorAll(`[data-${attr}]`).forEach(b => {
                const on = b.dataset[attr] === value;
                b.classList.toggle('is-on', on);
                b.setAttribute('aria-pressed', String(on));
            });
        };
        body.querySelector('#ap-accents').addEventListener('click', (e) => {
            const b = e.target.closest('[data-accent]');
            if (b) pick('accent', b.dataset.accent);
        });
        body.querySelector('#ap-sizes').addEventListener('click', (e) => {
            const b = e.target.closest('[data-size]');
            if (b) pick('size', b.dataset.size);
        });
    },
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => App.init());
