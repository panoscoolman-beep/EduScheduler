/**
 * Πίνακας Ελέγχου — «τι θέλει προσοχή» αντί για μετρητές (Π9).
 *
 * Όλα από αναγνώσεις που ήδη υπάρχουν: preview δημοσίευσης, Παλέτα του
 * προγράμματος, 🕳 κενά, νέοι μαθητές του CRM. Η μέρα με μια ματιά (από το
 * 📢 δημοσιευμένο πρόγραμμα, όπως το «Σήμερα»). Οι μετρητές μένουν σε μία
 * γραμμή· η «Γρήγορη Εκκίνηση» φαίνεται μόνο όσο λείπουν τα βασικά.
 */
const DashboardView = {
    CRM_CACHE_MS: 5 * 60 * 1000,
    _crmCache: null,     // { at, newCount } — το CRM δεν ρωτιέται σε κάθε επίσκεψη

    async render(container) {
        container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Φόρτωση...</p></div>`;

        let teachers, subjects, classes, classrooms, lessons, solutions, students, periods, publications, term;
        try {
            [teachers, subjects, classes, classrooms, lessons, solutions, students, periods, publications, term] = await Promise.all([
                API.teachers.list(),
                API.subjects.list(),
                API.classes.list(),
                API.classrooms.list(),
                API.lessons.list(),
                API.solver.listSolutions(),
                API.request('/students/'),
                API.periods.list().catch(() => []),
                (API.publications ? API.publications.list() : Promise.resolve([])).catch(() => []),
                API.terms.active().catch(() => null),
            ]);
        } catch (err) {
            App.renderError(container, err, () => this.render(container));
            return;
        }
        const esc = DataTable.esc;
        const active = (solutions || []).filter(s => !s.archived);
        // Το πρόγραμμα που δουλεύεις (όπως ανοίγει το Ωρολόγιο) και αυτό που έχουν οι καθηγητές.
        const workingId = TimetableHelpers.defaultSolutionId(active, App._currentSolutionId);
        const working = active.find(s => s.id === workingId) || null;
        const pick = TodayHelpers.pickSolution(active, publications, App._currentSolutionId, workingId);
        const teaching = (periods || []).filter(p => !p.is_break);
        const now = new Date();
        const day = TodayHelpers.edsDay(now);
        const status = working ? TimetableHelpers.statusInfo(working.status) : null;

        const missing = [];
        if (!teaching.length) missing.push(['periods', '🕐', 'Ώρες', 'Οι διδακτικές ώρες της μέρας.']);
        if (!teachers.length) missing.push(['teachers', '👨‍🏫', 'Καθηγητές', 'Καθηγητές και πότε μπορούν.']);
        if (!classes.length) missing.push(['classes', '🏫', 'Τμήματα', 'Τμήματα με τους μαθητές τους.']);
        if (!lessons.length) missing.push(['lessons', '🃏', 'Μαθήματα-Κάρτες', '«Ποιος διδάσκει τι, σε ποιο τμήμα».']);
        if (!active.length) missing.push(['generate', '🧠', 'Δημιουργία', 'Το πρώτο πρόγραμμα.']);

        const count = (n, one, many, view) =>
            `<a href="#${view}" class="dash-count" data-navigate="${view}"><b>${n}</b> ${n === 1 ? one : many}</a>`;

        container.innerHTML = `
            <div class="dash">
                <header class="dash-head">
                    <div>
                        <h2 class="dash-date">${TodayHelpers.DAYS[day]} ${now.getDate()}/${now.getMonth() + 1}</h2>
                        <p class="dash-sub">${term ? `🗂️ ${esc(term.name)}` : ''}${working ? `${term ? ' · ' : ''}📋 ${esc(working.name)}` : ''}
                            ${status ? `<span class="status-chip ${status.cls}" title="${esc(status.title)}">${esc(status.label)}</span>` : ''}</p>
                    </div>
                </header>

                ${missing.length ? `
                <section class="card dash-start">
                    <h3 class="dash-h">🚀 Για να ξεκινήσεις</h3>
                    <p class="text-muted dash-start-note">Λείπουν ακόμα βασικά στοιχεία — με αυτή τη σειρά:</p>
                    <div class="dash-start-steps">${missing.map(([view, icon, label, hint], i) => `
                        <a href="#${view}" class="dash-step" data-navigate="${view}">
                            <span class="dash-step-n">${i + 1}</span>
                            <span><b>${icon} ${esc(label)}</b><small>${esc(hint)}</small></span>
                        </a>`).join('')}</div>
                </section>` : ''}

                <section class="card dash-attention" aria-labelledby="dash-attn-title">
                    <h3 class="dash-h" id="dash-attn-title">Χρειάζεται προσοχή</h3>
                    <div id="dash-attn" class="dash-attn-list" aria-live="polite">
                        <div class="dash-attn-loading text-muted">Έλεγχος…</div>
                    </div>
                </section>

                <div class="dash-grid">
                    <section class="card dash-day" aria-labelledby="dash-day-title">
                        <h3 class="dash-h" id="dash-day-title">Η μέρα</h3>
                        <div id="dash-day" class="dash-day-stats"><span class="text-muted">…</span></div>
                        <a href="#today" class="btn btn-secondary dash-today-link" data-navigate="today">Άνοιγμα «Σήμερα» ›</a>
                    </section>
                    <section class="card dash-now" aria-labelledby="dash-now-title">
                        <h3 class="dash-h" id="dash-now-title">Τώρα</h3>
                        <div id="dash-now"><span class="text-muted">…</span></div>
                    </section>
                </div>

                <p class="dash-counts">
                    ${count(teachers.length, 'καθηγητής', 'καθηγητές', 'teachers')}
                    ${count(students.length, 'μαθητής', 'μαθητές', 'students')}
                    ${count(classes.length, 'τμήμα', 'τμήματα', 'classes')}
                    ${count(lessons.length, 'κάρτα', 'κάρτες', 'lessons')}
                    ${count(classrooms.length, 'αίθουσα', 'αίθουσες', 'classrooms')}
                    ${count(subjects.length, 'μάθημα', 'μαθήματα', 'subjects')}
                    ${count(active.length, 'πρόγραμμα', 'προγράμματα', 'generate')}
                </p>
            </div>
        `;

        container.querySelectorAll('[data-navigate]').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                App.navigateTo(el.dataset.navigate);
            });
        });

        if (!working) {
            this._fillAttention([], { ok: 'Δεν υπάρχει πρόγραμμα ακόμα — ξεκίνα από τη «Δημιουργία».' });
            document.getElementById('dash-day').innerHTML = '<span class="text-muted">Χωρίς πρόγραμμα.</span>';
            document.getElementById('dash-now').innerHTML = '<span class="text-muted">—</span>';
            return;
        }
        await this._fillLive(working, pick, periods, classrooms, day);
    },

    /** Τα «ζωντανά» κομμάτια: φορτώνουν μετά τον σκελετό, το καθένα μόνο του. */
    async _fillLive(working, pick, periods, classrooms, day) {
        const [workSol, todaySol, preview, gaps, crmNew] = await Promise.all([
            API.solver.getSolution(working.id).catch(() => null),
            pick.id && pick.id !== working.id ? API.solver.getSolution(pick.id).catch(() => null) : Promise.resolve(null),
            API.solver.publishPreview(working.id).catch(() => null),
            API.solver.gaps(working.id).catch(() => null),
            this._crmNewCount(),
        ]);
        if (!document.getElementById('dash-attn')) return;   // ο χρήστης έφυγε
        const daySol = todaySol || workSol;
        const rows = this.attentionRows({
            solutionId: working.id, preview, slots: workSol ? workSol.slots : [], gaps, crmNew,
        });
        this._fillAttention(rows, { ok: '✓ Όλα εντάξει — τίποτα δεν περιμένει.' });
        this._fillDay(daySol, periods, classrooms, day, pick);
    },

    /**
     * Οι γραμμές του «Χρειάζεται προσοχή» (pure): { icon, big, text, action, key }.
     */
    attentionRows({ solutionId, preview, slots, gaps, crmNew }) {
        const rows = [];
        const st = TimetableHelpers.publicationState(preview, solutionId);
        if (st && st.changes > 0) {
            const prev = preview.previous;
            const when = prev ? TimetableHelpers.shortDate(prev.published_at) : '';
            rows.push({
                key: 'publish', icon: '✏️', cls: 'warn',
                big: st.changes === 1 ? '1 καθηγητής' : `${st.changes} καθηγητές`,
                text: preview.first || !prev
                    ? 'δεν έχουν λάβει ακόμα το πρόγραμμα — δεν έχει δημοσιευτεί.'
                    : `με αλλαγές μετά τη δημοσίευση${when ? ` της ${when}` : ''} — δεν τις ξέρουν ακόμα.`,
                action: '📢 Δημοσίευση',
            });
        }
        const palette = (slots || []).filter(s => s.is_unplaced);
        if (palette.length) {
            const names = [...new Set(palette.map(s =>
                [s.subject_short || s.subject_name, s.class_short || s.class_name].filter(Boolean).join(' ')))];
            const list = names.slice(0, 2).join(', ') + (names.length > 2 ? ` +${names.length - 2}` : '');
            rows.push({
                key: 'palette', icon: '🅿️', cls: 'info',
                big: palette.length === 1 ? '1 ώρα' : `${palette.length} ώρες`,
                text: `περιμένουν στην Παλέτα${list ? ` (${list})` : ''}.`,
                action: 'Τοποθέτηση',
            });
        }
        const long = ((gaps && gaps.students) || []).filter(r => (r.gaps || []).some(g => g.hours >= 2));
        if (long.length) {
            const days = [...new Set(long.flatMap(r => r.gaps.filter(g => g.hours >= 2).map(g => g.day_name)))];
            rows.push({
                key: 'gaps', icon: '🕳', cls: 'muted',
                big: long.length === 1 ? '1 μαθητής' : `${long.length} μαθητές`,
                text: `με κενό 2 ή περισσότερων ωρών${days.length === 1 ? ` την ${days[0]}` : ''}.`,
                action: 'Κενά',
            });
        }
        if (crmNew > 0) {
            rows.push({
                key: 'crm', icon: '🔄', cls: 'info',
                big: crmNew === 1 ? '1 νέος μαθητής' : `${crmNew} νέοι μαθητές`,
                text: 'στο CRM δεν έχουν περάσει εδώ.',
                action: 'Εισαγωγή',
            });
        }
        return rows;
    },

    _fillAttention(rows, { ok }) {
        const box = document.getElementById('dash-attn');
        if (!box) return;
        const esc = DataTable.esc;
        if (!rows.length) {
            box.innerHTML = `<p class="dash-attn-ok">${esc(ok)}</p>`;
            return;
        }
        box.innerHTML = rows.map(r => `
            <div class="dash-attn-row ${r.cls}">
                <span class="dash-attn-icon" aria-hidden="true">${r.icon}</span>
                <p class="dash-attn-text"><b>${esc(r.big)}</b> ${esc(r.text)}</p>
                <button type="button" class="btn ${r.key === 'publish' ? 'btn-primary' : 'btn-secondary'} btn-sm" data-attn="${r.key}">${esc(r.action)}</button>
            </div>`).join('');
        box.querySelectorAll('[data-attn]').forEach(btn => btn.addEventListener('click', () => {
            const key = btn.dataset.attn;
            if (key === 'publish') App.openPending('timetable', 'publish');
            else if (key === 'gaps') App.openPending('timetable', 'gaps');
            else if (key === 'palette') App.openPending('timetable', 'palette');
            else if (key === 'crm') App.openPending('students', 'crm-import');
        }));
    },

    /** «Η μέρα» + «Τώρα» από το πρόγραμμα που έχουν οι καθηγητές. */
    _fillDay(solution, periods, classrooms, day, pick) {
        const dayBox = document.getElementById('dash-day');
        const nowBox = document.getElementById('dash-now');
        if (!dayBox || !nowBox) return;
        const esc = DataTable.esc;
        if (!solution) {
            dayBox.innerHTML = '<span class="text-muted">Δεν φορτώθηκε το πρόγραμμα.</span>';
            nowBox.innerHTML = '<span class="text-muted">—</span>';
            return;
        }
        const now = TodayHelpers.nowHHMM(new Date());
        const slots = solution.slots || [];
        const built = TodayHelpers.buildDay(slots, periods, day, now);
        const todayCount = slots.filter(s => !s.is_unplaced && s.day_of_week === day).length;
        const free = TodayHelpers.freeNow(slots, periods, classrooms, day, now);
        const conflicts = TodayHelpers.countConflicts(slots, day);
        const stat = (n, label, cls = '') => `<div class="dash-stat ${cls}"><b>${n}</b><span>${label}</span></div>`;
        dayBox.innerHTML = `
            ${stat(todayCount, todayCount === 1 ? 'μάθημα σήμερα' : 'μαθήματα σήμερα')}
            ${stat(built.current ? built.current.items.length : 0,
                built.current ? `τώρα · ως ${esc(built.current.period.end_time)}` : 'τώρα')}
            ${stat(free ? free.rooms.length : '—', free && free.rooms.length === 1 ? 'αίθουσα ελεύθερη' : 'αίθουσες ελεύθερες')}
            ${stat(conflicts, conflicts === 1 ? 'σύγκρουση' : 'συγκρούσεις', conflicts ? 'bad' : 'ok')}
            <p class="dash-day-source">${pick.published ? '📢 Από το δημοσιευμένο' : 'Από το'} «${esc(solution.name)}»</p>`;

        const title = document.getElementById('dash-now-title');
        if (built.current) {
            const left = TodayHelpers.minutes(built.current.period.end_time) - TodayHelpers.minutes(now);
            if (title) title.innerHTML = `Τώρα · ${esc(built.current.period.start_time)}–${esc(built.current.period.end_time)}
                <span class="dash-now-left">λήγει σε ${TodayHelpers.durationText(left)}</span>`;
            const items = built.current.items;
            nowBox.innerHTML = `<ul class="dash-now-list">${items.slice(0, 6).map(s => `
                <li><span><b>${esc(s.subject_name || '')}</b> <small>${esc(s.class_name || '')}</small><br>
                    <small class="text-muted">${esc(s.teacher_name || '')}</small></span>
                    <span class="dash-now-room">${esc(s.classroom_name || '')}</span></li>`).join('')}</ul>
                ${items.length > 6 ? `<p class="text-muted dash-more">+${items.length - 6} ακόμα στο «Σήμερα»</p>` : ''}`;
        } else if (built.next) {
            nowBox.innerHTML = `<p class="text-muted">Κανένα μάθημα αυτή τη στιγμή. Επόμενο:
                <b>${esc(built.next.period.start_time)}</b> (${built.next.items.length === 1 ? '1 μάθημα' : `${built.next.items.length} μαθήματα`}).</p>`;
        } else {
            nowBox.innerHTML = `<p class="text-muted">${todayCount ? '✅ Τα μαθήματα της μέρας τελείωσαν.' : 'Κανένα μάθημα σήμερα.'}</p>`;
        }
    },

    /** Νέοι μαθητές του CRM (με cache 5′ — κάθε επίσκεψη δεν ρωτά το CRM). */
    async _crmNewCount() {
        const c = this._crmCache;
        if (c && Date.now() - c.at < this.CRM_CACHE_MS) return c.newCount;
        try {
            const preview = await API.students.crmPreview();
            const n = preview && preview.available
                ? (preview.rows || []).filter(r => r.status === 'new').length : 0;
            this._crmCache = { at: Date.now(), newCount: n };
            return n;
        } catch (err) {
            return 0;   // CRM εκτός: απλώς χωρίς αυτή τη γραμμή
        }
    },
};
