/**
 * Full-app jsdom harness για regression tests που χρειάζονται ΟΛΗ την
 * εφαρμογή: φορτώνει το πραγματικό frontend/index.html και κάθε <script> του
 * με τη σειρά (πραγματικός κώδικας, χωρίς stubs), με window.fetch δρομολογημένο
 * σε ψεύτικο backend (routes: { 'GET /api/x/': handler, 'PUT /api/x/*': … }).
 *
 * Δεν είναι test (δεν ταιριάζει στο *.test.js) — το κάνουν require τα tests.
 * Πάντα `app.close()` στο τέλος: σταματά timers (Toast, «Σήμερα») ώστε να
 * τελειώνει γρήγορα το process του runner.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const FRONT = path.join(__dirname, '..', '..');
const GLOBALS = ['API', 'Toast', 'Modal', 'App', 'DataTable', 'TimetableView', 'TimetableGrid',
    'TimetableHelpers', 'StudentPicker', 'ClassesView', 'StudentsView', 'GenerateView',
    'TodayView', 'TermsView', 'TeachersView', 'VersionCheck', 'TimetableInteractions', 'SettingsView'];

/** Βασικό ψεύτικο backend: άδειο σενάριο με 3 ώρες. */
function baseRoutes(over = {}) {
    const periods = [
        { id: 1, name: '1η', short_name: '1η', start_time: '16:00', end_time: '17:00', is_break: false, sort_order: 1 },
        { id: 2, name: '2η', short_name: '2η', start_time: '17:00', end_time: '18:00', is_break: false, sort_order: 2 },
        { id: 3, name: '3η', short_name: '3η', start_time: '18:00', end_time: '19:00', is_break: false, sort_order: 3 },
    ];
    return Object.assign({
        'GET /api/terms/': () => [{ id: 1, name: 'Χειμ', is_active: true }],
        'GET /api/settings/': () => ({ days_per_week: 5 }),
        'GET /api/periods/': () => periods,
        'GET /api/solver/readiness': () => ({ ok: true, checks: [] }),
        'GET /api/solver/solutions': () => [],
        'GET /api/students/': () => [],
        'GET /api/students/grade-options': () => ({ grades: [], tracks: {}, track_labels: {} }),
        'GET /api/lessons/': () => [],
        'GET /api/lessons/rosters': () => ({ rosters: {} }),
        'GET /api/classes/': () => [],
        'GET /api/classrooms/': () => [{ id: 1, name: 'Αίθ 1', short_name: 'Α1' }],
        'GET /api/teachers/': () => [],
        'GET /api/subjects/': () => [],
        'GET /api/constraints/': () => [],
    }, over);
}

/** Ένα slot προγράμματος (τοποθετημένο) με λογικές τιμές. */
function slot(id, extra = {}) {
    return Object.assign({
        id, solution_id: 7, lesson_id: 100 + id, day_of_week: 0, period_id: 1, classroom_id: 1,
        classroom_name: 'Αίθ 1', subject_name: 'Φυσική', subject_short: 'ΦΥΣ', subject_color: '#3B82F6',
        class_name: 'Β2', class_short: 'Β2', class_id: 11, teacher_name: 'Νικολάου', teacher_short: 'ΝΙΚ',
        teacher_id: 21, is_locked: false, is_unplaced: false, students: ['Νίκος Π.'],
    }, extra);
}

/**
 * Backend με προγράμματα: state.solutions (λίστα) και, ανά πρόγραμμα, τα
 * slots στο s.slots (ή στο state.slots για το πρόγραμμα 7).
 */
function timetableRoutes(over = {}) {
    const state = {
        solutions: [{ id: 7, name: 'Χειμερινό', status: 'optimal', score: 1, created_at: '2026-09-20T10:00:00Z', archived: false }],
        slots: [slot(1), slot(2, { day_of_week: 1, period_id: 2 })],
        can_undo: 3, can_redo: 1, undoCalls: 0, redoCalls: 0,
    };
    const routes = baseRoutes(Object.assign({
        'GET /api/solver/solutions': ({ search }) => (/include_archived=true/.test(search || '')
            ? state.solutions : state.solutions.filter(s => !s.archived)),
        'GET /api/solver/solutions/*': ({ path: p }) => {
            const id = +p.split('/').pop();
            const s = state.solutions.find(x => x.id === id);
            return s ? { ...s, slots: s.slots || (id === 7 ? state.slots : []) } : { __status: 404, data: { detail: 'Not found' } };
        },
        'GET /api/solver/solutions/*/history-summary': () => ({ can_undo: state.can_undo, can_redo: state.can_redo }),
        'POST /api/solver/solutions/*/undo': () => { state.undoCalls += 1; return { message: 'Αναιρέθηκε' }; },
        'POST /api/solver/solutions/*/redo': () => { state.redoCalls += 1; return { message: 'Επαναλήφθηκε' }; },
        'GET /api/students/': () => [{ id: 1, first_name: 'Νίκος', last_name: 'Παπαδόπουλος', class_ids: [11] }],
        'GET /api/classes/': () => [{ id: 11, name: 'Β2', short_name: 'Β2', student_ids: [1] }],
    }, over));
    return { routes, state };
}

function boot(routes, { hash = '' } = {}) {
    const raw = fs.readFileSync(path.join(FRONT, 'index.html'), 'utf8');
    const html = raw.replace(/<script src="[^"]+"><\/script>/g, '');
    const dom = new JSDOM(html, { url: 'http://eds.local/' + hash, runScripts: 'dangerously', pretendToBeVisual: true });
    const w = dom.window;
    const calls = [];
    w.fetch = async (url, cfg = {}) => {
        const method = (cfg.method || 'GET').toUpperCase();
        const u = new URL(url, 'http://eds.local');
        const key = `${method} ${u.pathname}`;
        const body = cfg.body ? JSON.parse(cfg.body) : undefined;
        calls.push({ method, path: u.pathname, search: u.search, body });
        let handler = routes[key];
        if (!handler) {
            for (const [k, h] of Object.entries(routes)) {
                if (!k.includes('*')) continue;
                const re = new RegExp('^' + k.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '[^/]+') + '$');
                if (re.test(key)) { handler = h; break; }
            }
        }
        let status = 200;
        let data = null;
        if (!handler) { status = 404; data = { detail: `no route ${key}` }; } else {
            const r = await handler({ body, search: u.search, path: u.pathname });
            if (r && r.__status) { status = r.__status; data = r.data; } else data = r;
        }
        return { ok: status >= 200 && status < 300, status, json: async () => data, text: async () => JSON.stringify(data) };
    };
    w.open = () => null;
    w.print = () => null;
    w.scrollTo = () => null;
    w.HTMLElement.prototype.scrollIntoView = function () {};
    const srcs = [...raw.matchAll(/<script src="([^"?]+)\?v=\d+"><\/script>/g)].map(m => m[1]);
    for (const src of srcs) {
        const el = w.document.createElement('script');
        el.textContent = fs.readFileSync(path.join(FRONT, src), 'utf8');
        w.document.body.appendChild(el);
    }
    // Τα classic scripts δηλώνουν top-level const — φέρ' τα στο test.
    const G = {};
    for (const n of GLOBALS) {
        const el = w.document.createElement('script');
        el.textContent = `window.__x = (typeof ${n} !== 'undefined') ? ${n} : undefined;`;
        w.document.body.appendChild(el);
        G[n] = w.__x;
    }
    G.VersionCheck.start = () => {};     // καμία περιοδική κλήση στα tests
    const toasts = [];
    const origShow = G.Toast.show.bind(G.Toast);
    G.Toast.show = (m, t, d) => { toasts.push({ type: t, message: m }); origShow(m, t, d); };
    return { dom, w, doc: w.document, calls, G, toasts, close: () => w.close() };
}

const sleep = (w, ms) => new Promise(r => w.setTimeout(r, ms));

/** Περίμενε μέχρι να ισχύσει το cond() (polling) — όχι σταθερές καθυστερήσεις. */
async function waitFor(w, cond, { timeout = 3000, step = 10 } = {}) {
    const start = Date.now();
    for (;;) {
        let ok = false;
        try { ok = cond(); } catch (_) { ok = false; }
        if (ok) return ok;
        if (Date.now() - start > timeout) throw new Error('waitFor: timeout');
        await sleep(w, step);
    }
}

/** Boot + περίμενε το App.init (αρχική σελίδα σχεδιασμένη). */
async function start(routes, opts) {
    const app = boot(routes, opts);
    await waitFor(app.w, () => app.G.App && app.doc.getElementById('content-area')
        && !app.doc.querySelector('#content-area .loading-spinner'));
    return app;
}

/** Πλοήγηση σε σελίδα + περίμενε να φύγει το spinner. */
async function go(app, view, readySelector) {
    app.G.App.navigateTo(view);
    await waitFor(app.w, () => app.doc.querySelector(readySelector));
}

module.exports = { boot, start, go, sleep, waitFor, baseRoutes, timetableRoutes, slot };
