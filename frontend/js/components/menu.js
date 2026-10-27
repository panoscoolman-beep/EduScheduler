/**
 * Αναδυόμενα μενού κουμπιών (π.χ. «Διόρθωση ▾» στο Ωρολόγιο).
 *
 * Markup:
 *   <div class="menu" data-menu>
 *     <button class="btn menu-btn" aria-haspopup="menu" aria-expanded="false">… ▾</button>
 *     <div class="menu-list" role="menu" hidden>
 *       <button class="menu-item" role="menuitem" id="…">…</button>
 *     </div>
 *   </div>
 *
 * Τα στοιχεία του μενού υπάρχουν πάντα στο DOM (με τα ίδια id), οπότε οι
 * listeners και τα tests που τα πατούν απευθείας δουλεύουν όπως πριν.
 * Κλείνει με πάτημα έξω, Esc ή επιλογή.
 *
 * Browser: global Menu. Node: module.exports.
 */
const Menu = {
    _bound: false,

    wire(root) {
        (root || document).querySelectorAll('[data-menu]').forEach(menu => {
            if (menu._menuWired) return;
            menu._menuWired = true;
            const btn = menu.querySelector('.menu-btn');
            const list = menu.querySelector('.menu-list');
            if (!btn || !list) return;
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const open = list.hidden;
                Menu.closeAll(open ? menu : null);
                if (open) Menu._open(menu, btn, list);
                else Menu._close(menu);
            });
            // Επιλογή → κλείσιμο (ο δικός του listener του στοιχείου τρέχει κανονικά).
            list.addEventListener('click', (e) => {
                if (e.target.closest('.menu-item')) Menu._close(menu);
            });
            list.addEventListener('keydown', (e) => Menu._onKey(e, menu, btn, list));
        });
        if (!this._bound) {
            this._bound = true;
            document.addEventListener('click', (e) => {
                if (!e.target.closest || !e.target.closest('[data-menu]')) Menu.closeAll();
            });
            document.addEventListener('keydown', (e) => {
                if (e.key !== 'Escape') return;
                const open = document.querySelector('[data-menu].is-open');
                if (open) {
                    Menu._close(open);
                    open.querySelector('.menu-btn')?.focus();
                }
            });
        }
    },

    closeAll(except = null) {
        document.querySelectorAll('[data-menu].is-open').forEach(m => {
            if (m !== except) Menu._close(m);
        });
    },

    _open(menu, btn, list) {
        list.hidden = false;
        menu.classList.add('is-open');
        btn.setAttribute('aria-expanded', 'true');
        // Μέσα στην οθόνη: αν ξεχειλίζει δεξιά, ευθυγράμμιση στο δεξί άκρο.
        list.classList.remove('align-right');
        const rect = list.getBoundingClientRect ? list.getBoundingClientRect() : null;
        if (rect && rect.right > (window.innerWidth || 0) - 8) list.classList.add('align-right');
        list.querySelector('.menu-item:not([disabled])')?.focus();
    },

    _close(menu) {
        const list = menu.querySelector('.menu-list');
        if (list) list.hidden = true;
        menu.classList.remove('is-open');
        menu.querySelector('.menu-btn')?.setAttribute('aria-expanded', 'false');
    },

    _onKey(e, menu, btn, list) {
        const items = [...list.querySelectorAll('.menu-item:not([disabled])')];
        const i = items.indexOf(document.activeElement);
        if (e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
        else if (e.key === 'Tab') { Menu._close(menu); }
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = Menu;
}
