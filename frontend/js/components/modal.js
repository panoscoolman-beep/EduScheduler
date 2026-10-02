/**
 * Modal Component — Generic modal dialog.
 */
const Modal = {
    _onSave: null,
    // Προστασία από διπλό κλικ στο «Αποθήκευση»: όσο τρέχει η ενέργεια του
    // παραθύρου το κουμπί είναι απενεργό. Το _token αλλάζει σε κάθε open(),
    // ώστε ένα παράθυρο που ανοίγει ΜΕΣΑ από την ενέργεια (π.χ. επιβεβαίωση
    // «force», πρόοδος email) να ξεκινά πάντα με ενεργό κουμπί.
    _token: 0,
    _busy: false,

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
            if (cancelBtn) cancelBtn.textContent = options.cancelText || 'Ακύρωση';
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
        if (saveBtn) saveBtn.disabled = false;
        overlay.classList.add('active');
        document.body.style.overflow = 'hidden';

        // Focus first input
        setTimeout(() => {
            const firstInput = document.querySelector('#modal-body input, #modal-body select');
            if (firstInput) firstInput.focus();
        }, 200);
    },

    close() {
        document.getElementById('modal-overlay').classList.remove('active');
        document.body.style.overflow = '';
        this._onSave = null;
    },

    async _handleSave() {
        if (!this._onSave || this._busy) return;   // ήδη σε εξέλιξη — αγνόησε το 2ο κλικ
        const token = this._token;
        const saveBtn = document.getElementById('modal-save');
        this._busy = true;
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
        document.getElementById('modal-close').addEventListener('click', () => this.close());
        document.getElementById('modal-cancel').addEventListener('click', () => this.close());
        document.getElementById('modal-save').addEventListener('click', () => this._handleSave());
        document.getElementById('modal-overlay').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) this.close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this.close();
        });
    },
};
