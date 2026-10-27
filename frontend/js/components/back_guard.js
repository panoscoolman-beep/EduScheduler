/**
 * «Πίσω» του κινητού (και του browser) για παράθυρα και μενού.
 *
 * Όσο είναι ανοιχτό ένα παράθυρο (Modal) ή το μενού «Περισσότερα», υπάρχει
 * ΜΙΑ επιπλέον εγγραφή στο ιστορικό (ίδια διεύθυνση). Το «Πίσω» την
 * καταναλώνει και κλείνει το πάνω-πάνω παράθυρο αντί να βγει από την
 * εφαρμογή. Όταν το παράθυρο κλείνει από κουμπί, η εγγραφή αφαιρείται με
 * history.back() — αλλά μόνο αν στο μεταξύ (ίδιο tick) δεν άνοιξε άλλο, ώστε
 * το «κλείσε το ένα, άνοιξε το επόμενο» να μη μπερδεύει το ιστορικό.
 *
 * Browser: global BackGuard. Node: module.exports για τα tests.
 */
const BackGuard = {
    _stack: [],          // [{ id, close }] — close() → true αν έκλεισε
    _pushed: false,      // υπάρχει δική μας εγγραφή στο ιστορικό
    _ignore: 0,          // popstate που προκαλέσαμε εμείς (history.back)
    _settleTimer: null,

    /** Άνοιξε overlay με id· close(source) καλείται από το «Πίσω». */
    open(id, close) {
        this._stack = this._stack.filter(e => e.id !== id);
        this._stack.push({ id, close });
        this._cancelSettle();
        if (!this._pushed) {
            try {
                window.history.pushState({ edsOverlay: true }, '', window.location.href);
                this._pushed = true;
            } catch (_) { /* χωρίς history (π.χ. sandbox) — απλώς χωρίς «Πίσω» */ }
        }
    },

    /** Το overlay έκλεισε από το UI (κουμπί, πάτημα έξω, Esc). */
    closed(id) {
        this._stack = this._stack.filter(e => e.id !== id);
        this._scheduleSettle();
    },

    isOpen(id) {
        return this._stack.some(e => e.id === id);
    },

    /**
     * Πλοήγηση σε άλλη σελίδα ενώ υπάρχει η εγγραφή μας: ο καλών τη
     * ΑΝΤΙΚΑΘΙΣΤΑ (replaceState) αντί να προσθέσει νέα — αλλιώς το «Πίσω»
     * θα έπεφτε σε μια «νεκρή» εγγραφή. true = υπήρχε εγγραφή.
     */
    takeMarker() {
        this._cancelSettle();
        if (!this._pushed || this._stack.length) return false;
        this._pushed = false;
        return true;
    },

    /** popstate: true = το χειρίστηκε (δεν είναι αλλαγή σελίδας). */
    handlePop() {
        if (this._ignore > 0) {
            this._ignore -= 1;
            return true;
        }
        if (!this._pushed) return false;
        this._pushed = false;
        const top = this._stack[this._stack.length - 1];
        if (!top) return true;
        let closed = true;
        try { closed = top.close('back') !== false; } catch (_) { closed = true; }
        if (closed) {
            this._stack = this._stack.filter(e => e !== top);
        }
        // Έμεινε κάτι ανοιχτό (ή δεν έκλεισε, π.χ. «Να κλείσει χωρίς
        // αποθήκευση;») → ξανά εγγραφή, ώστε το επόμενο «Πίσω» να το κλείσει.
        if (this._stack.length) {
            try {
                window.history.pushState({ edsOverlay: true }, '', window.location.href);
                this._pushed = true;
            } catch (_) { /* ignore */ }
        }
        return true;
    },

    _scheduleSettle() {
        this._cancelSettle();
        this._settleTimer = setTimeout(() => {
            this._settleTimer = null;
            if (this._stack.length || !this._pushed) return;
            this._pushed = false;
            this._ignore += 1;
            try { window.history.back(); } catch (_) { this._ignore = 0; }
            // Ασφάλεια: αν για κάποιο λόγο δεν έρθει popstate, μην «φάμε»
            // το επόμενο πραγματικό «Πίσω».
            setTimeout(() => { this._ignore = 0; }, 800);
        }, 0);
    },

    _cancelSettle() {
        if (this._settleTimer) {
            clearTimeout(this._settleTimer);
            this._settleTimer = null;
        }
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = BackGuard;
}
