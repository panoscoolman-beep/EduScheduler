/**
 * 🔄 Ειδοποίηση νέας έκδοσης.
 *
 * Μια καρτέλα που έμεινε ανοιχτή πριν από deploy συνεχίζει να τρέχει το παλιό
 * JS (π.χ. 18/9: η παλιά σελίδα δεν έστελνε το «ναι, σίγουρα» στη διαγραφή
 * τμήματος). Εδώ διαβάζουμε περιοδικά το index.html του server (no-store)·
 * αν το ?v=N του app.js διαφέρει από το φορτωμένο, δείχνουμε μπάρα
 * «Νέα έκδοση — ανανέωση». Δεν ανανεώνει ποτέ μόνο του (μπορεί να γράφεις φόρμα).
 *
 * Browser: global VersionCheck. Node: module.exports για τα tests.
 */
const VersionCheck = {
    INTERVAL_MS: 5 * 60 * 1000,
    RELOAD_PARAM: '_v',
    _timer: null,
    _shown: false,

    /** Το N του `app.js?v=N` μέσα σε HTML — null αν δεν βρεθεί. */
    parseVersion(html) {
        const m = /js\/app\.js\?v=(\d+)/.exec(html || '');
        return m ? Number(m[1]) : null;
    },

    /** Η έκδοση που τρέχει τώρα αυτή η καρτέλα (από το <script> του app.js). */
    loadedVersion(doc) {
        const script = [...doc.querySelectorAll('script[src]')].find(s => /js\/app\.js\?v=/.test(s.getAttribute('src')));
        return script ? VersionCheck.parseVersion(script.getAttribute('src')) : null;
    },

    isStale(loaded, served) {
        return loaded !== null && served !== null && served !== loaded;
    },

    /** URL που παρακάμπτει την cache του index.html, κρατώντας το #hash. */
    reloadUrl(loc, now) {
        const params = new URLSearchParams(loc.search);
        params.set(VersionCheck.RELOAD_PARAM, String(now));
        return `${loc.pathname}?${params.toString()}${loc.hash || ''}`;
    },

    /** Μετά την ανανέωση: σβήσε το ?_v= από τη διεύθυνση (καθαρό URL/σελιδοδείκτης). */
    cleanUrl(win) {
        const params = new URLSearchParams(win.location.search);
        if (!params.has(VersionCheck.RELOAD_PARAM)) return;
        params.delete(VersionCheck.RELOAD_PARAM);
        const qs = params.toString();
        win.history.replaceState(null, '', `${win.location.pathname}${qs ? `?${qs}` : ''}${win.location.hash}`);
    },

    async check(win = window) {
        if (VersionCheck._shown) return;
        try {
            const res = await win.fetch(`${win.location.pathname}`, { cache: 'no-store' });
            if (!res.ok) return;
            const served = VersionCheck.parseVersion(await res.text());
            if (VersionCheck.isStale(VersionCheck.loadedVersion(win.document), served)) {
                VersionCheck.showBanner(win);
            }
        } catch (_) {
            /* εκτός δικτύου — ξαναδοκιμάζει στον επόμενο έλεγχο */
        }
    },

    showBanner(win) {
        if (VersionCheck._shown) return;
        VersionCheck._shown = true;
        const bar = win.document.createElement('div');
        bar.id = 'version-banner';
        bar.className = 'version-banner';
        bar.setAttribute('role', 'status');
        bar.innerHTML = `<span>🔄 Υπάρχει νέα έκδοση του EduScheduler.</span>
            <button class="btn btn-primary btn-sm" id="version-reload">Ανανέωση</button>
            <button class="btn btn-secondary btn-sm" id="version-later" aria-label="Αργότερα">✕</button>`;
        win.document.body.appendChild(bar);
        bar.querySelector('#version-reload').addEventListener('click', () => {
            win.location.assign(VersionCheck.reloadUrl(win.location, Date.now()));
        });
        bar.querySelector('#version-later').addEventListener('click', () => bar.remove());
    },

    start(win = window) {
        VersionCheck.cleanUrl(win);
        clearInterval(VersionCheck._timer);
        VersionCheck._timer = setInterval(() => VersionCheck.check(win), VersionCheck.INTERVAL_MS);
        // Επιστροφή σε καρτέλα που ήταν στο παρασκήνιο → έλεγχος αμέσως.
        win.document.addEventListener('visibilitychange', () => {
            if (win.document.visibilityState === 'visible') VersionCheck.check(win);
        });
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = VersionCheck;
}
