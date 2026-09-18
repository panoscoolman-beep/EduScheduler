/**
 * 📱 «Σήμερα» — ποιος διδάσκει τώρα, σε ποια αίθουσα, τι ακολουθεί.
 * Μόνο ανάγνωση. Άμεσο link: …/#today (για την αρχική οθόνη του κινητού).
 */
const TodayView = {
    _timer: null,
    _offset: 0,          // 0 = σήμερα, ±1 = επόμενη/προηγούμενη μέρα
    _data: null,
    FILTER_KEY: 'eds.today.filter',

    async render(container) {
        this._offset = 0;
        try {
            const solutions = (await API.solver.listSolutions()).filter(s => !s.archived);
            const sid = TimetableHelpers.defaultSolutionId(solutions, App._currentSolutionId);
            if (!sid) {
                container.innerHTML = '<p class="text-muted">Δεν υπάρχει πρόγραμμα ακόμα.</p>';
                return;
            }
            const [solution, periods] = await Promise.all([API.solver.getSolution(sid), API.periods.list()]);
            this._data = { solution, periods };
        } catch (err) {
            container.innerHTML = `<p class="text-muted">⚠️ ${TodayHelpers._esc(err.message)}</p>`;
            return;
        }
        const opts = TodayHelpers.filterOptions(this._data.solution.slots);
        const esc = TodayHelpers._esc;
        const saved = this._loadFilter();
        const option = (value, label) =>
            `<option value="${esc(value)}" ${value === saved ? 'selected' : ''}>${esc(label)}</option>`;
        container.innerHTML = `
            <div id="today-root" class="today-root">
                <div class="today-bar">
                    <button class="btn btn-secondary" id="today-prev" aria-label="Προηγούμενη μέρα">◀</button>
                    <div class="today-title" id="today-title"></div>
                    <button class="btn btn-secondary" id="today-next" aria-label="Επόμενη μέρα">▶</button>
                </div>
                <select class="form-select" id="today-filter">
                    ${option('', 'Όλοι οι καθηγητές & αίθουσες')}
                    <optgroup label="Καθηγητής">${opts.teachers.map(t => option(`t:${t}`, t)).join('')}</optgroup>
                    <optgroup label="Αίθουσα">${opts.rooms.map(r => option(`r:${r}`, r)).join('')}</optgroup>
                </select>
                <p class="text-muted today-source">Πρόγραμμα: ${esc(this._data.solution.name)}</p>
                <div id="today-list"></div>
            </div>`;
        document.getElementById('today-prev').addEventListener('click', () => { this._offset -= 1; this._draw(); });
        document.getElementById('today-next').addEventListener('click', () => { this._offset += 1; this._draw(); });
        document.getElementById('today-filter').addEventListener('change', (e) => {
            this._saveFilter(e.target.value);
            this._draw();
        });
        this._draw();
        this._startTimer();
    },

    _draw() {
        if (!document.getElementById('today-root') || !this._data) return;
        const date = new Date();
        date.setDate(date.getDate() + this._offset);
        const day = TodayHelpers.edsDay(date);
        const now = this._offset === 0 ? TodayHelpers.nowHHMM(new Date()) : null;
        const label = this._offset === 0 ? 'Σήμερα' : this._offset === 1 ? 'Αύριο'
            : this._offset === -1 ? 'Χθες' : date.toLocaleDateString('el-GR');
        document.getElementById('today-title').innerHTML =
            `<b>${label}</b><br><small>${TodayHelpers.DAYS[day]}${now ? ` · ${now}` : ''}</small>`;
        const filter = document.getElementById('today-filter').value;
        const built = TodayHelpers.buildDay(this._data.solution.slots, this._data.periods, day, now, filter);
        document.getElementById('today-list').innerHTML = TodayHelpers.buildHtml(built);
    },

    /** Ανανέωση ώρας κάθε λεπτό· σταματά μόνο του όταν φύγεις από τη σελίδα. */
    _startTimer() {
        clearInterval(this._timer);
        this._timer = setInterval(() => {
            if (!document.getElementById('today-root')) {
                clearInterval(this._timer);
                return;
            }
            this._draw();
        }, 60000);
    },

    _loadFilter() {
        try { return localStorage.getItem(this.FILTER_KEY) || ''; } catch (_) { return ''; }
    },

    _saveFilter(value) {
        try { localStorage.setItem(this.FILTER_KEY, value); } catch (_) { /* ιδιωτική περιήγηση */ }
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = TodayView;
}
