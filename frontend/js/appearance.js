/**
 * 🎨 Εμφάνιση ανά συσκευή (όπως στο CRM): χρώμα έμφασης και μέγεθος γραμμάτων.
 *
 * Φορτώνεται στο <head> ΠΡΙΝ από το CSS, ώστε το σωστό χρώμα να φαίνεται από
 * την πρώτη ζωγραφιά (χωρίς «αναβόσβημα» του μπλε). Μένει μόνο σε αυτή τη
 * συσκευή (localStorage)· σε ιδιωτική περιήγηση ισχύουν απλώς τα προεπιλεγμένα.
 *
 * Browser: global Appearance. Node: module.exports για τα tests.
 */
const Appearance = {
    KEY: 'eds.appearance',
    DEFAULTS: { accent: 'blue', size: 'm' },
    // Ίδια χρώματα με το CRM (src/lib/appearance.ts — ACCENT_SWATCH).
    ACCENTS: [
        { id: 'blue', label: 'Μπλε', swatch: '#4a9eff' },
        { id: 'red', label: 'Κόκκινο ΚΟΡΥΦΗ', swatch: '#ee2825' },
        { id: 'green', label: 'Πράσινο', swatch: '#22c38e' },
        { id: 'violet', label: 'Μωβ', swatch: '#9b7bff' },
        { id: 'amber', label: 'Πορτοκαλί', swatch: '#f5a524' },
        { id: 'graphite', label: 'Ασημί', swatch: '#dfe3ea' },
    ],
    SIZES: [
        { id: 's', label: 'Μικρά' },
        { id: 'm', label: 'Κανονικά' },
        { id: 'l', label: 'Μεγάλα' },
        { id: 'xl', label: 'Πολύ μεγάλα' },
    ],

    /** Καθαρίζει ό,τι διαβάστηκε (παλιά/χαλασμένη τιμή → προεπιλογή). */
    normalize(raw) {
        const a = (raw && typeof raw === 'object') ? raw : {};
        const pick = (list, value, fallback) => (list.some(x => x.id === value) ? value : fallback);
        return {
            accent: pick(this.ACCENTS, a.accent, this.DEFAULTS.accent),
            size: pick(this.SIZES, a.size, this.DEFAULTS.size),
        };
    },

    load(storage) {
        try {
            const s = storage || window.localStorage;
            return this.normalize(JSON.parse(s.getItem(this.KEY) || '{}'));
        } catch (_) {
            return { ...this.DEFAULTS };
        }
    },

    save(value, storage) {
        const clean = this.normalize(value);
        try { (storage || window.localStorage).setItem(this.KEY, JSON.stringify(clean)); } catch (_) { /* ιδιωτική περιήγηση */ }
        return clean;
    },

    /** Γράφει τις επιλογές ως data-* στο <html>· το CSS κάνει τα υπόλοιπα. */
    apply(value, root) {
        const el = root || document.documentElement;
        const a = this.normalize(value);
        el.setAttribute('data-accent', a.accent);
        el.setAttribute('data-size', a.size);
        return a;
    },
};

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
    Appearance.apply(Appearance.load());
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = Appearance;
}
