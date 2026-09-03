/**
 * StudentPicker — επιλογέας πολλών εγγραφών με αναζήτηση + checkboxes + chips.
 *
 * Αντικαθιστά το native <select multiple> (Ctrl+Click) στη φόρμα Τμήματος:
 *   - live αναζήτηση χωρίς τόνους/πεζά-κεφαλαία («παπα» βρίσκει «Παπαδόπουλος»)
 *   - checkbox ανά γραμμή, chips των επιλεγμένων με ✕, «μόνο επιλεγμένοι»
 *   - badges ανά γραμμή (π.χ. σε ποια ΑΛΛΑ τμήματα είναι ήδη ο μαθητής)
 *
 * Γενικός: δουλεύει και ανάποδα (Μαθητής → Τμήματα) — τα items, το label και
 * τα badges δίνονται από τον caller. Οι builders είναι pure (testable με
 * node --test)· το mount() δένει τα events και κρατά το state σε Set.
 *
 * Dual-mode: classic-script global στον browser, module.exports στο Node.
 */
const StudentPicker = {
    _state: null,

    /** Αφαίρεση τόνων/διαλυτικών + πεζά + τελικό ς→σ, για ελληνική αναζήτηση. */
    normalizeGr(s) {
        return String(s ?? '')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .toLowerCase()
            .replace(/ς/g, 'σ')
            .trim();
    },

    esc(s) {
        return String(s ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    },

    studentLabel(s) {
        return `${s.last_name || ''} ${s.first_name || ''}`.trim();
    },

    /**
     * Φίλτρο + ταξινόμηση. Pure. Κάθε λέξη της αναζήτησης πρέπει να
     * ταιριάζει κάπου στο label («νικ παπ» → Παπαδόπουλος Νίκος).
     */
    filterItems(items, { search = '', selectedIds = new Set(), onlySelected = false, labelOf }) {
        const label = labelOf || this.studentLabel;
        const words = this.normalizeGr(search).split(/\s+/).filter(Boolean);
        return (items || [])
            .filter(it => !onlySelected || selectedIds.has(it.id))
            .filter(it => {
                if (!words.length) return true;
                const hay = this.normalizeGr(label(it));
                return words.every(w => hay.includes(w));
            })
            .slice()
            .sort((a, b) => label(a).localeCompare(label(b), 'el'));
    },

    /** Chips των επιλεγμένων (με ✕). Pure. */
    buildChipsHtml(items, selectedIds, labelOf) {
        const label = labelOf || this.studentLabel;
        const chosen = (items || []).filter(it => selectedIds.has(it.id))
            .sort((a, b) => label(a).localeCompare(label(b), 'el'));
        if (!chosen.length) {
            return '<span class="sp-empty">Κανένας επιλεγμένος ακόμα — τσέκαρε από τη λίστα.</span>';
        }
        return chosen.map(it => `
            <span class="sp-chip" data-id="${it.id}">
                ${this.esc(label(it))}
                <button type="button" class="sp-chip-x" data-id="${it.id}"
                        title="Αφαίρεση" aria-label="Αφαίρεση ${this.esc(label(it))}">✕</button>
            </span>`).join('');
    },

    /** Λίστα γραμμών με checkbox + badges. Pure. */
    buildListHtml(items, { selectedIds, labelOf, badgesOf, search = '', onlySelected = false }) {
        const label = labelOf || this.studentLabel;
        const visible = this.filterItems(items, { search, selectedIds, onlySelected, labelOf: label });
        if (!visible.length) {
            return `<div class="sp-empty">${
                search ? 'Κανένα αποτέλεσμα για «' + this.esc(search) + '».' : 'Δεν υπάρχουν εγγραφές.'
            }</div>`;
        }
        return visible.map(it => {
            const badges = (badgesOf ? badgesOf(it) : [])
                .map(b => `<span class="sp-badge" title="${this.esc(b.title || '')}">${this.esc(b.text)}</span>`)
                .join('');
            const checked = selectedIds.has(it.id) ? ' checked' : '';
            return `
            <label class="sp-row${checked ? ' is-selected' : ''}" data-id="${it.id}">
                <input type="checkbox" class="sp-check" data-id="${it.id}"${checked}>
                <span class="sp-name">${this.esc(label(it))}</span>
                <span class="sp-badges">${badges}</span>
            </label>`;
        }).join('');
    },

    /** Ο σκελετός (toolbar + chips + list). Pure. */
    buildHtml({ placeholder = '🔍 Αναζήτηση…', noun = 'επιλεγμένοι' } = {}) {
        return `
        <div class="student-picker">
            <div class="sp-toolbar">
                <input type="text" class="form-input sp-search" placeholder="${this.esc(placeholder)}"
                       autocomplete="off">
                <label class="sp-only">
                    <input type="checkbox" class="sp-only-selected"> μόνο επιλεγμένοι
                </label>
                <span class="sp-count"><b>0</b> ${this.esc(noun)}</span>
            </div>
            <div class="sp-chips"></div>
            <div class="sp-list"></div>
        </div>`;
    },

    /**
     * Δέσε τον επιλογέα σε ένα container.
     * opts: { items, selectedIds:[], labelOf, badgesOf, placeholder, noun, onChange }
     */
    mount(container, opts) {
        const el = typeof container === 'string' ? document.getElementById(container) : container;
        if (!el) return null;
        const state = {
            el,
            items: opts.items || [],
            selected: new Set((opts.selectedIds || []).map(Number)),
            labelOf: opts.labelOf || this.studentLabel,
            badgesOf: opts.badgesOf || null,
            noun: opts.noun || 'επιλεγμένοι',
            onChange: opts.onChange || null,
            search: '',
            onlySelected: false,
        };
        this._state = state;
        el.innerHTML = this.buildHtml({ placeholder: opts.placeholder, noun: state.noun });

        const searchEl = el.querySelector('.sp-search');
        searchEl.addEventListener('input', () => {
            state.search = searchEl.value;
            this._renderList();
        });
        // Enter στην αναζήτηση: αν βλέπεις ακριβώς ΕΝΑ αποτέλεσμα, τσέκαρέ το.
        searchEl.addEventListener('keydown', (e) => {
            if (e.key !== 'Enter') return;
            e.preventDefault();
            const visible = this.filterItems(state.items, state_filter(state));
            if (visible.length === 1) {
                this.toggle(visible[0].id, true);
                searchEl.value = '';
                state.search = '';
                this._renderList();
            }
        });
        el.querySelector('.sp-only-selected').addEventListener('change', (e) => {
            state.onlySelected = !!e.target.checked;
            this._renderList();
        });
        el.querySelector('.sp-list').addEventListener('change', (e) => {
            const cb = e.target.closest('.sp-check');
            if (cb) this.toggle(parseInt(cb.dataset.id), cb.checked);
        });
        el.querySelector('.sp-chips').addEventListener('click', (e) => {
            const x = e.target.closest('.sp-chip-x');
            if (x) this.toggle(parseInt(x.dataset.id), false);
        });

        function state_filter(st) {
            return { search: st.search, selectedIds: st.selected,
                     onlySelected: st.onlySelected, labelOf: st.labelOf };
        }

        this._renderChips();
        this._renderList();
        return state;
    },

    toggle(id, on) {
        const st = this._state;
        if (!st) return;
        if (on) st.selected.add(id); else st.selected.delete(id);
        this._renderChips();
        // Μόνο η συγκεκριμένη γραμμή — όχι όλη η λίστα (κρατά scroll/focus).
        const row = st.el.querySelector(`.sp-row[data-id="${id}"]`);
        if (row) {
            row.classList.toggle('is-selected', on);
            const cb = row.querySelector('.sp-check');
            if (cb) cb.checked = on;
            if (st.onlySelected && !on) row.remove();
        }
        if (st.onChange) st.onChange(this.getSelected());
    },

    _renderChips() {
        const st = this._state;
        st.el.querySelector('.sp-chips').innerHTML =
            this.buildChipsHtml(st.items, st.selected, st.labelOf);
        st.el.querySelector('.sp-count').innerHTML =
            `<b>${st.selected.size}</b> ${this.esc(st.noun)}`;
    },

    _renderList() {
        const st = this._state;
        st.el.querySelector('.sp-list').innerHTML = this.buildListHtml(st.items, {
            selectedIds: st.selected, labelOf: st.labelOf, badgesOf: st.badgesOf,
            search: st.search, onlySelected: st.onlySelected,
        });
    },

    /** Τα επιλεγμένα ids (ταξινομημένα) — ό,τι στέλνει η φόρμα. */
    getSelected() {
        return this._state ? [...this._state.selected].sort((a, b) => a - b) : [];
    },

    /**
     * Badges για τη φόρμα Τμήματος: σε ποια ΑΛΛΑ τμήματα είναι ο μαθητής.
     * Pure — classesById: Map(id → class), currentClassId εξαιρείται.
     */
    otherClassBadges(student, classesById, currentClassId) {
        return (student.class_ids || [])
            .filter(cid => cid !== currentClassId)
            .map(cid => classesById.get(cid))
            .filter(Boolean)
            .map(c => ({ text: c.short_name, title: `Είναι ήδη στο ${c.name}` }));
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = StudentPicker;
}
