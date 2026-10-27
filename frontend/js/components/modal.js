/**
 * Modal Component — Generic modal dialog.
 *
 * Στο κινητό εμφανίζεται ως «φύλλο» από κάτω (CSS) και κλείνει με το «Πίσω»
 * (BackGuard). Φόρμα με αλλαγές ΔΕΝ χάνεται σιωπηλά με πάτημα έξω, Esc ή
 * «Πίσω»: ρωτά «Να κλείσει χωρίς αποθήκευση;». Τα ρητά «Ακύρωση» / ✕
 * κλείνουν κατευθείαν, όπως πάντα.
 */
const Modal = {
    _onSave: null,
    // Προστασία από διπλό κλικ στο «Αποθήκευση»: όσο τρέχει η ενέργεια του
    // παραθύρου το κουμπί είναι απενεργό. Το _token αλλάζει σε κάθε open(),
    // ώστε ένα παράθυρο που ανοίγει ΜΕΣΑ από την ενέργεια (π.χ. επιβεβαίωση
    // «force», πρόοδος email) να ξεκινά πάντα με ενεργό κουμπί.
    _token: 0,
    _busy: false,
    // Προστασία φόρμας: _guard = το παράθυρο έχει ενέργεια αποθήκευσης·
    // _dirty = ο χρήστης άλλαξε κάποιο πεδίο από τότε που άνοιξε.
    _guard: false,
    _dirty: false,

    open(title, bodyHTML, onSave, options = {}) {
        const overlay = document.getElementById('modal-overlay');
        const modalEl = document.getElementById('modal');
        document.getElementById('modal-title').textContent = title;
        document.getElementById('modal-body').innerHTML = bodyHTML;

        const saveBtn = document.getElementById('modal-save');
        const cancelBtn = document.getElementById('modal-cancel');
        const footer = saveBtn?.parentElement;

        if (options.hideFooter && footer) {
            footer.style.display = 'none';
        } else if (footer) {
            footer.style.display = '';
            saveBtn.textContent = options.saveText || 'Αποθήκευση';
            saveBtn.className = `btn ${options.saveClass || 'btn-primary'}`;
            if (cancelBtn) {
                cancelBtn.textContent = options.cancelText || 'Ακύρωση';
                // Πληροφοριακό παράθυρο με μόνο «Κλείσιμο»: όχι και «Ακύρωση» δίπλα.
                cancelBtn.hidden = Boolean(options.hideCancel
                    || ((options.saveClass === 'btn-secondary') && options.saveText === 'Κλείσιμο'));
            }
        }

        if (options.wide || options.hideFooter) {
            // Wide modal also when we hide the default footer (bulk import etc.)
            modalEl.style.width = 'min(95vw, 800px)';
        } else {
            modalEl.style.width = 'min(90vw, 560px)';
        }

        this._onSave = onSave;
        this._token += 1;
        this._busy = false;
        this._dirty = false;
        // Μόνο παράθυρα που αποθηκεύουν κάτι: όχι τα «Κλείσιμο»/πληροφοριακά.
        this._guard = typeof onSave === 'function' && !options.hideFooter
            && options.confirmDiscard !== false
            && (options.saveClass || 'btn-primary') !== 'btn-secondary';
        this._hideDiscard();
        if (saveBtn) saveBtn.disabled = false;
        const wasOpen = overlay.classList.contains('active');
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';
        if (!wasOpen && typeof BackGuard !== 'undefined') {
            BackGuard.open('modal', (source) => this.requestClose(source));
        }

        // Focus first input (όχι στο κινητό: θα άνοιγε το πληκτρολόγιο και θα
        // έκρυβε τη μισή φόρμα πριν τη δει ο χρήστης).
        setTimeout(() => {
            if (!overlay.classList.contains('active')) return;
            if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) return;
            const firstInput = document.querySelector('#modal-body input, #modal-body select');
            if (firstInput) firstInput.focus();
        }, 200);
    },

    isOpen() {
        return document.getElementById('modal-overlay')?.classList.contains('active') || false;
    },

    close() {
        const overlay = document.getElementById('modal-overlay');
        const wasOpen = overlay.classList.contains('active');
        overlay.classList.remove('active');
        document.body.style.overflow = '';
        this._onSave = null;
        this._dirty = false;
        this._hideDiscard();
        if (wasOpen && typeof BackGuard !== 'undefined') BackGuard.closed('modal');
    },

    /**
     * Κλείσιμο από πάτημα έξω / Esc / «Πίσω». Με αλλαγές σε φόρμα: πρώτα
     * ερώτηση (false = δεν έκλεισε). Τα κουμπιά «Ακύρωση»/✕ καλούν close().
     */
    requestClose(source = 'outside') {
        if (!this.isOpen()) return true;
        if (this._guard && this._dirty && !this._busy) {
            this._showDiscard();
            return false;
        }
        this.close();
        return true;
    },

    _showDiscard() {
        const bar = document.getElementById('modal-discard');
        if (!bar) return;
        bar.hidden = false;
        bar.querySelector('[data-discard="keep"]')?.focus();
    },

    _hideDiscard() {
        const bar = document.getElementById('modal-discard');
        if (bar) bar.hidden = true;
    },

    async _handleSave() {
        if (!this._onSave || this._busy) return;   // ήδη σε εξέλιξη — αγνόησε το 2ο κλικ
        const token = this._token;
        const saveBtn = document.getElementById('modal-save');
        this._busy = true;
        this._hideDiscard();
        if (saveBtn) saveBtn.disabled = true;
        try {
            await this._onSave();
        } finally {
            // Μόνο αν είναι ακόμα το ΙΔΙΟ παράθυρο (σε σφάλμα ξαναενεργοποιείται
            // για νέα προσπάθεια)· ένα νέο παράθυρο έχει ήδη δικό του κουμπί.
            if (this._token === token) {
                this._busy = false;
                if (saveBtn) saveBtn.disabled = false;
            }
        }
    },

    init() {
        const modalEl = document.getElementById('modal');
        // Μπάρα «Να κλείσει χωρίς αποθήκευση;» μέσα στο παράθυρο (όχι 2ο παράθυρο:
        // η φόρμα μένει όπως είναι από κάτω).
        if (modalEl && !document.getElementById('modal-discard')) {
            const bar = document.createElement('div');
            bar.id = 'modal-discard';
            bar.className = 'modal-discard';
            bar.hidden = true;
            bar.setAttribute('role', 'alertdialog');
            bar.setAttribute('aria-label', 'Μη αποθηκευμένες αλλαγές');
            bar.innerHTML = `
                <span>Έχεις αλλαγές που δεν αποθηκεύτηκαν. Να κλείσει χωρίς αποθήκευση;</span>
                <div class="modal-discard-actions">
                    <button type="button" class="btn btn-secondary btn-sm" data-discard="keep">Συνέχεια επεξεργασίας</button>
                    <button type="button" class="btn btn-danger btn-sm" data-discard="drop">Κλείσιμο χωρίς αποθήκευση</button>
                </div>`;
            modalEl.appendChild(bar);
            bar.addEventListener('click', (e) => {
                const act = e.target.closest('[data-discard]')?.dataset.discard;
                if (act === 'keep') this._hideDiscard();
                else if (act === 'drop') this.close();
            });
        }
        const body = document.getElementById('modal-body');
        const markDirty = (e) => {
            if (e.target && e.target.closest && e.target.closest('[data-no-dirty]')) return;
            this._dirty = true;
        };
        body.addEventListener('input', markDirty);
        body.addEventListener('change', markDirty);

        document.getElementById('modal-close').addEventListener('click', () => this.close());
        document.getElementById('modal-cancel').addEventListener('click', () => this.close());
        document.getElementById('modal-save').addEventListener('click', () => this._handleSave());
        document.getElementById('modal-overlay').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) this.requestClose('outside');
        });
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape' || !this.isOpen()) return;
            const bar = document.getElementById('modal-discard');
            if (bar && !bar.hidden) { this._hideDiscard(); return; }
            this.requestClose('esc');
        });
    },
};
