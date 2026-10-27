/**
 * 📱 «Σήμερα» — ποιος διδάσκει τώρα, σε ποια αίθουσα, τι ακολουθεί, τι είναι
 * ελεύθερο. Πάτημα σε μάθημα: «Λείπει σήμερα» (προτάσεις αντικαταστάτη με
 * έτοιμο μήνυμα), «✓ Παρουσίες» στο CRM, κλήση. Το πρόγραμμα ΔΕΝ αλλάζει
 * από εδώ — μόνο ανάγνωση και μηνύματα. Άμεσο link: …/#today.
 */
const TodayView = {
    _timer: null,
    _offset: 0,          // 0 = σήμερα, ±1 = επόμενη/προηγούμενη μέρα
    _data: null,
    FILTER_KEY: 'eds.today.filter',

    async render(container) {
        this._offset = 0;
        try {
            const [all, publications] = await Promise.all([
                API.solver.listSolutions(),
                (API.publications && API.publications.list ? API.publications.list() : Promise.resolve([]))
                    .catch(() => []),
            ]);
            const solutions = (all || []).filter(s => !s.archived);
            const fallback = TimetableHelpers.defaultSolutionId(solutions, App._currentSolutionId);
            const pick = TodayHelpers.pickSolution(solutions, publications, App._currentSolutionId, fallback);
            if (!pick.id) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📱</div>
                        <p class="empty-state-text">Δεν υπάρχει πρόγραμμα ακόμα</p>
                    </div>`;
                return;
            }
            const optional = (fn) => (typeof fn === 'function' ? fn().catch(() => []) : Promise.resolve([]));
            const [solution, periods, rooms, teachers] = await Promise.all([
                API.solver.getSolution(pick.id),
                API.periods.list(),
                optional(API.classrooms && API.classrooms.list),
                optional(API.teachers && API.teachers.list),
            ]);
            this._data = { solution, periods, rooms: rooms || [], teachers: teachers || [], pick };
        } catch (err) {
            App.renderError(container, err, () => this.render(container));
            return;
        }
        const opts = TodayHelpers.filterOptions(this._data.solution.slots);
        const esc = TodayHelpers._esc;
        const saved = this._loadFilter();
        const option = (value, label) =>
            `<option value="${esc(value)}" ${value === saved ? 'selected' : ''}>${esc(label)}</option>`;
        const pick = this._data.pick;
        const source = pick.published
            ? `<span class="status-chip ok">📢 δημοσιευμένο</span>`
            : `<span class="status-chip muted" title="Δεν έχει δημοσιευτεί πρόγραμμα — δείχνει το τελευταίο">αδημοσίευτο</span>`;
        container.innerHTML = `
            <div id="today-root" class="today-root">
                <div class="today-bar">
                    <button class="btn btn-secondary" id="today-prev" aria-label="Προηγούμενη μέρα">◀</button>
                    <div class="today-title" id="today-title" aria-live="polite"></div>
                    <button class="btn btn-secondary" id="today-next" aria-label="Επόμενη μέρα">▶</button>
                </div>
                <p class="today-source"><span>Πρόγραμμα: ${esc(this._data.solution.name)}</span> ${source}</p>
                <select class="form-select" id="today-filter" aria-label="Φίλτρο καθηγητή ή αίθουσας">
                    ${option('', 'Όλοι οι καθηγητές & αίθουσες')}
                    <optgroup label="Καθηγητής">${opts.teachers.map(t => option(`t:${t}`, t)).join('')}</optgroup>
                    <optgroup label="Αίθουσα">${opts.rooms.map(r => option(`r:${r}`, r)).join('')}</optgroup>
                </select>
                <div id="today-list"></div>
                <div id="today-free"></div>
            </div>`;
        document.getElementById('today-prev').addEventListener('click', () => { this._offset -= 1; this._draw(); });
        document.getElementById('today-next').addEventListener('click', () => { this._offset += 1; this._draw(); });
        document.getElementById('today-filter').addEventListener('change', (e) => {
            this._saveFilter(e.target.value);
            this._draw();
        });
        document.getElementById('today-list').addEventListener('click', (e) => this._onListClick(e));
        this._draw();
        this._startTimer();
    },

    _date() {
        const date = new Date();
        date.setDate(date.getDate() + this._offset);
        return date;
    },

    _draw() {
        if (!document.getElementById('today-root') || !this._data) return;
        const date = this._date();
        const day = TodayHelpers.edsDay(date);
        const now = this._offset === 0 ? TodayHelpers.nowHHMM(new Date()) : null;
        const near = { 0: 'Σήμερα', 1: 'Αύριο', '-1': 'Χθες' }[this._offset];
        const dm = `${date.getDate()}/${date.getMonth() + 1}`;
        document.getElementById('today-title').innerHTML = near
            ? `<b>${near}</b><br><small>${TodayHelpers.DAYS[day]} ${dm}${now ? ` · ${now}` : ''}</small>`
            : `<b>${TodayHelpers.DAYS[day]}</b><br><small>${dm}</small>`;
        const filter = document.getElementById('today-filter').value;
        const built = TodayHelpers.buildDay(this._data.solution.slots, this._data.periods, day, now, filter);
        // Ανοιχτό μάθημα (ενέργειες) μένει ανοιχτό στο ανανέωμα του λεπτού.
        const openId = document.querySelector('#today-list .today-item.is-open')?.dataset.slotId;
        document.getElementById('today-list').innerHTML = TodayHelpers.buildHtml(built, { now });
        if (openId) {
            const item = document.querySelector(`#today-list .today-item[data-slot-id="${openId}"]`);
            if (item) this._toggleItem(item, true);
        }
        const free = (now && !filter)
            ? TodayHelpers.freeNow(this._data.solution.slots, this._data.periods, this._data.rooms, day, now)
            : null;
        document.getElementById('today-free').innerHTML = TodayHelpers.freeHtml(free);
    },

    _onListClick(e) {
        const main = e.target.closest('.today-item-main');
        if (main) {
            const item = main.closest('.today-item');
            this._toggleItem(item, !item.classList.contains('is-open'));
            return;
        }
        const absent = e.target.closest('[data-today-absent]');
        if (absent) {
            const slot = this._slotById(absent.dataset.todayAbsent);
            if (slot) this.openAbsent(slot);
        }
    },

    _slotById(id) {
        return (this._data.solution.slots || []).find(s => String(s.id) === String(id)) || null;
    },

    _teacher(id) {
        return (this._data.teachers || []).find(t => t.id === id) || null;
    },

    /** «Σήμερα» / «Αύριο» / «την Πέμπτη» για κουμπιά και μηνύματα. */
    _dayWord(cap = false) {
        const w = this._offset === 0 ? 'σήμερα' : this._offset === 1 ? 'αύριο'
            : `την ${TodayHelpers.DAYS[TodayHelpers.edsDay(this._date())]}`;
        return cap ? w.charAt(0).toUpperCase() + w.slice(1) : w;
    },

    /** Ενέργειες κάτω από ένα μάθημα (ανοίγουν με πάτημα). */
    _toggleItem(item, open) {
        const box = item.querySelector('.today-actions');
        const btn = item.querySelector('.today-item-main');
        document.querySelectorAll('#today-list .today-item.is-open').forEach(other => {
            if (other === item) return;
            other.classList.remove('is-open');
            other.querySelector('.today-actions').hidden = true;
            other.querySelector('.today-item-main').setAttribute('aria-expanded', 'false');
        });
        item.classList.toggle('is-open', open);
        btn.setAttribute('aria-expanded', String(open));
        box.hidden = !open;
        if (!open) return;
        const slot = this._slotById(item.dataset.slotId);
        if (!slot) { box.hidden = true; return; }
        const esc = TodayHelpers._esc;
        const teacher = this._teacher(slot.teacher_id);
        const phone = teacher ? Contact.phoneNumbers(teacher.phone)[0] : null;
        const crm = this._crmAttendanceUrl(slot);
        box.innerHTML = `
            <button type="button" class="btn btn-secondary" data-today-absent="${slot.id}">🙋 Λείπει ${esc(this._dayWord())}</button>
            ${crm ? `<a class="btn btn-secondary" href="${esc(crm)}" target="_blank" rel="noopener">✓ Παρουσίες</a>` : ''}
            ${phone ? `<a class="btn btn-secondary" href="${esc(Contact.links(phone).call)}">📞 ${esc(phone.display)}</a>` : ''}`;
    },

    /**
     * «✓ Παρουσίες» στο CRM για αυτό το τμήμα και αυτή τη μέρα. Το CRM είναι
     * στον ίδιο server στην πόρτα 8443 όταν ο EduScheduler ανοίγει από την
     * HTTPS 8444 (tailscale serve)· αλλού (π.χ. τοπικά) δεν δείχνουμε κουμπί
     * παρά να στείλουμε σε λάθος διεύθυνση.
     */
    _crmAttendanceUrl(slot) {
        const loc = window.location;
        if (loc.protocol !== 'https:' || loc.port !== '8444' || !slot.class_id) return null;
        const params = new URLSearchParams({ class: String(slot.class_id) });
        if (this._offset !== 0) {
            const d = this._date();
            const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
            params.set('date', iso);
        }
        return `https://${loc.hostname}:8443/students/attendance?${params.toString()}`;
    },

    /**
     * 🙋 «Λείπει σήμερα»: όλα τα μαθήματα του καθηγητή εκείνη τη μέρα, με
     * αντικαταστάτες σε σειρά καταλληλότητας (υπάρχων υπολογισμός, μόνο
     * ανάγνωση) και έτοιμο μήνυμα για Viber/SMS. Τίποτα δεν αλλάζει στο πρόγραμμα.
     */
    async openAbsent(slot) {
        const esc = TodayHelpers._esc;
        const day = TodayHelpers.edsDay(this._date());
        const d = this._date();
        const title = `🙋 Λείπει ${this._dayWord()}`;
        Modal.open(title, '<div class="loading-spinner"><div class="spinner"></div><p>Ψάχνω αντικαταστάτες…</p></div>',
            null, { hideFooter: true });
        let data;
        try {
            data = await API.solver.substituteSuggestions(this._data.solution.id, slot.teacher_id, day);
        } catch (err) {
            const body = document.getElementById('modal-body');
            if (body) body.innerHTML = `<p class="text-muted">Δεν βρέθηκαν προτάσεις: ${esc(err.message)}</p>`;
            return;
        }
        const body = document.getElementById('modal-body');
        if (!body || !Modal.isOpen()) return;
        const periods = new Map((this._data.periods || []).map(p => [p.id, p]));
        const affected = (data.affected_slots || []).slice().sort((a, b) =>
            TodayHelpers.minutes((periods.get(a.period_id) || {}).start_time)
            - TodayHelpers.minutes((periods.get(b.period_id) || {}).start_time));
        const dayName = TodayHelpers.DAYS[day];
        const head = `<p class="absent-who"><b>${esc(slot.teacher_name || '')}</b> · ${dayName} ${d.getDate()}/${d.getMonth() + 1}</p>`;
        if (!affected.length) {
            body.innerHTML = `${head}<p class="text-muted">Δεν έχει μαθήματα αυτή τη μέρα — δεν χρειάζεται αντικατάσταση.</p>`;
            return;
        }
        const shortDay = ['Δευ', 'Τρί', 'Τετ', 'Πέμ', 'Παρ', 'Σάβ', 'Κυρ'];
        const sections = affected.map((a, i) => {
            const p = periods.get(a.period_id) || {};
            const cands = (a.candidates || []).slice(0, 3).map((c, j) => `
                <button type="button" class="absent-cand" data-a="${i}" data-c="${j}" aria-pressed="false">
                    <span class="absent-cand-name">${esc(c.name)}${j === 0 ? ' <span class="status-chip ok">Καλύτερη</span>' : ''}</span>
                    <small>${esc((c.reasons || []).join(' · '))}</small>
                </button>`).join('');
            const resched = (a.reschedule_options || []).slice(0, 3).map(o => {
                const op = periods.get(o.period_id);
                return `${shortDay[o.day_of_week] || ''} ${esc(op ? op.start_time : (o.period_name || ''))}`;
            }).join(' · ');
            return `
                <section class="absent-slot">
                    <h4>${esc(p.start_time || '')}–${esc(p.end_time || '')} · ${esc(a.subject_name || '')}
                        <small>${esc(a.class_name || '')}${a.classroom_name ? ` · ${esc(a.classroom_name)}` : ''}</small></h4>
                    ${cands || '<p class="text-muted absent-none">Κανείς ελεύθερος αυτή την ώρα.</p>'}
                    ${resched ? `<p class="absent-resched">ή άλλη ώρα την ίδια εβδομάδα: ${resched}</p>` : ''}
                </section>`;
        }).join('');
        body.innerHTML = `<div class="absent-root">${head}
            <p class="text-muted absent-intro">${affected.length === 1 ? '1 μάθημα' : `${affected.length} μαθήματα`} — προτάσεις με σειρά καταλληλότητας. Διάλεξε ποιος θα το κάνει.</p>
            ${sections}
            <div id="absent-msg" class="absent-msg" hidden></div></div>`;
        const root = body.querySelector('.absent-root');

        // Επιλογή αντικαταστάτη ανά μάθημα → ένα μήνυμα ανά αντικαταστάτη.
        // (Listener στο δικό μας στοιχείο, όχι στο #modal-body που μένει για τα επόμενα παράθυρα.)
        const chosen = new Map();   // index μαθήματος → candidate
        root.addEventListener('click', (e) => {
            const btn = e.target.closest('.absent-cand');
            if (btn) {
                const ai = Number(btn.dataset.a);
                const cand = affected[ai].candidates[Number(btn.dataset.c)];
                const same = chosen.get(ai) && chosen.get(ai).teacher_id === cand.teacher_id;
                if (same) chosen.delete(ai); else chosen.set(ai, cand);
                root.querySelectorAll(`.absent-cand[data-a="${ai}"]`).forEach(b => {
                    const on = !same && b === btn;
                    b.classList.toggle('is-on', on);
                    b.setAttribute('aria-pressed', String(on));
                });
                this._renderAbsentMessage(root, affected, chosen, periods, slot, same ? null : cand);
                return;
            }
            const copy = e.target.closest('[data-copy]');
            if (copy) this._copy(root.querySelector('#absent-text')?.value || '');
        });
    },

    _renderAbsentMessage(body, affected, chosen, periods, slot, focusCand) {
        const box = body.querySelector('#absent-msg');
        const esc = TodayHelpers._esc;
        const cand = focusCand || [...chosen.values()].pop();
        if (!cand) { box.hidden = true; box.innerHTML = ''; return; }
        const items = [...chosen.entries()]
            .filter(([, c]) => c.teacher_id === cand.teacher_id)
            .map(([i]) => {
                const a = affected[i];
                const p = periods.get(a.period_id) || {};
                return { start: p.start_time || '', end: p.end_time || '', subject: a.subject_name || '',
                         class: a.class_name || '', room: a.classroom_name || '' };
            });
        const text = TodayHelpers.substituteMessage(cand.name, slot.teacher_name, items, this._dayWord());
        const teacher = this._teacher(cand.teacher_id);
        const phone = teacher ? Contact.phoneNumbers(teacher.phone)[0] : null;
        const links = phone ? Contact.links(phone, text) : null;
        box.hidden = false;
        box.innerHTML = `
            <label class="form-label" for="absent-text">Μήνυμα στον/στην ${esc(cand.name)}</label>
            <textarea id="absent-text" class="form-input absent-text" rows="3" data-no-dirty>${esc(text)}</textarea>
            <div class="absent-actions">
                ${links && links.viber ? `<a class="btn btn-primary" href="${esc(links.viber)}">💬 Viber</a>` : ''}
                ${links && links.sms ? `<a class="btn btn-secondary" href="${esc(links.sms)}">✉️ SMS</a>` : ''}
                ${links ? `<a class="btn btn-secondary" href="${esc(links.call)}">📞 Κλήση</a>` : ''}
                <button type="button" class="btn btn-secondary" data-copy>📋 Αντιγραφή</button>
            </div>
            ${phone ? '' : '<p class="text-muted absent-nophone">Δεν υπάρχει κινητό στα στοιχεία του — αντέγραψε το μήνυμα.</p>'}
            ${links && links.viber ? '<p class="text-muted absent-hint">Το Viber ανοίγει τη συνομιλία — επικόλλησε το μήνυμα (αντιγράφεται αυτόματα).</p>' : ''}`;
        // Viber δεν δέχεται έτοιμο κείμενο: αντιγραφή μόλις πατηθεί.
        box.querySelector('a[href^="viber:"]')?.addEventListener('click', () =>
            this._copy(box.querySelector('#absent-text').value, true));
        box.querySelector('#absent-text').addEventListener('input', (e) => {
            if (!links) return;
            const fresh = Contact.links(phone, e.target.value);
            const sms = box.querySelector('a[href^="sms:"]');
            if (sms && fresh.sms) sms.href = fresh.sms;
        });
    },

    async _copy(text, quiet = false) {
        try {
            await navigator.clipboard.writeText(text);
            if (!quiet) Toast.success('Το μήνυμα αντιγράφηκε');
        } catch (_) {
            const ta = document.getElementById('absent-text');
            if (ta) { ta.focus(); ta.select(); }
            if (!quiet) Toast.info('Επίλεξε το κείμενο και αντέγραψέ το');
        }
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
