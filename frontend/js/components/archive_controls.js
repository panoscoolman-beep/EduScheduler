/**
 * ArchiveControls — 📦 αρχειοθέτηση / ♻️ επαναφορά για Καθηγητές, Τμήματα και
 * Αίθουσες (κοινό για τις τρεις σελίδες-πίνακες).
 *
 * Αρχειοθετημένο = κρυφό από τις λίστες/φόρμες και τον solver, χωρίς να
 * σβηστεί τίποτα (παλιά προγράμματα ακέραια). Ο server αρνείται (409) όταν
 * χρησιμοποιείται στο ενεργό σενάριο και το μήνυμα λέει γιατί.
 *
 * Χρήση σε ένα view:
 *   const ctl = ArchiveControls.create(API.teachers, 'τον καθηγητή');
 *   new DataTable({ apiService: ctl.api, customActions: [..., ctl.action],
 *                   toolbarHtml: ctl.toolbarHtml(), columns: [{ key: 'name', render: ArchiveControls.nameRender }] })
 *   ...μετά το table.render(): ctl.wire(container, table)
 *
 * Dual-mode: pure builders (tests) + wiring.
 */
const ArchiveControls = {
    esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    /** Όνομα + σήμα «αρχειοθετημένο» (escape μέσα). */
    nameRender(value, item) {
        const name = ArchiveControls.esc(value);
        return item && item.archived
            ? `${name} <span class="archived-badge" title="Αρχειοθετημένο">📦 αρχειοθετημένο</span>`
            : name;
    },

    toolbarHtml(checked) {
        return `<label class="archive-toggle" title="Δείξε και τα αρχειοθετημένα για επαναφορά">
                    <input type="checkbox" class="archive-show"${checked ? ' checked' : ''}>
                    📦 Αρχειοθετημένα
                </label>`;
    },

    confirmHtml(item, noun) {
        return `<p>Θα αρχειοθετηθεί ${noun} «<b>${ArchiveControls.esc(item.name)}</b>».</p>
            <ul class="text-muted" style="font-size:0.85rem; margin:0.5rem 0 0 1.1rem">
                <li>Δεν σβήνεται τίποτα — τα παλιά προγράμματα μένουν ακέραια.</li>
                <li>Κρύβεται από λίστες, φόρμες και τον solver.</li>
                <li>Επαναφέρεται από το «📦 Αρχειοθετημένα» πάνω δεξιά.</li>
            </ul>`;
    },

    /** Controller για ένα view: api με include_archived + customAction + wiring. */
    create(baseApi, noun) {
        const state = { show: false, table: null };
        const reload = async () => { if (state.table) await state.table.loadData(); };
        const run = async (call) => {
            try {
                const res = await call();
                Toast.success(res.message || 'Έγινε');
                Modal.close();
                await reload();
            } catch (err) {
                Toast.error(err.message);
            }
        };
        return {
            state,
            api: { ...baseApi, list: () => baseApi.list(state.show) },
            toolbarHtml: () => ArchiveControls.toolbarHtml(state.show),
            action: {
                id: 'archive',
                title: 'Αρχειοθέτηση / επαναφορά',
                icon: '📦',
                handler: (item) => {
                    if (item.archived) {
                        run(() => baseApi.unarchive(item.id));
                        return;
                    }
                    Modal.open('📦 Αρχειοθέτηση', ArchiveControls.confirmHtml(item, noun),
                        () => run(() => baseApi.archive(item.id)), { saveText: '📦 Αρχειοθέτηση' });
                },
            },
            wire(container, table) {
                state.table = table;
                container.querySelector('.archive-show')?.addEventListener('change', async (e) => {
                    state.show = e.target.checked;
                    await reload();
                });
            },
        };
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = ArchiveControls;
}
