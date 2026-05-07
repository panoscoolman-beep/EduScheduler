/**
 * Modal Component — Generic modal dialog.
 */
const Modal = {
    _onSave: null,

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
        }

        if (options.wide || options.hideFooter) {
            // Wide modal also when we hide the default footer (bulk import etc.)
            modalEl.style.width = 'min(95vw, 800px)';
        } else {
            modalEl.style.width = 'min(90vw, 560px)';
        }

        this._onSave = onSave;
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

    _handleSave() {
        if (this._onSave) this._onSave();
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
