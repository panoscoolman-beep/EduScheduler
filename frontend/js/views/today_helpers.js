/**
 * 📱 «Σήμερα» — pure helpers (χωρίς DOM/API), ώστε να ελέγχονται με node --test.
 *
 * Browser: global TodayHelpers. Node: module.exports για τα tests. No build step.
 */
const TodayHelpers = {
    DAYS: ['Δευτέρα', 'Τρίτη', 'Τετάρτη', 'Πέμπτη', 'Παρασκευή', 'Σάββατο', 'Κυριακή'],

    /** JS Date → μέρα EDS (0=Δευτέρα … 6=Κυριακή). */
    edsDay(date) {
        return (date.getDay() + 6) % 7;
    },

    /** «H:MM»/«HH:MM» → λεπτά από τα μεσάνυχτα (για σωστή σύγκριση). */
    minutes(hhmm) {
        const [h, m] = String(hhmm || '0:0').split(':').map(Number);
        return (h || 0) * 60 + (m || 0);
    },

    nowHHMM(date) {
        return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
    },

    /** Επιλογές φίλτρου: καθηγητές και αίθουσες που εμφανίζονται στο πρόγραμμα. */
    filterOptions(slots) {
        const collator = new Intl.Collator('el');
        const uniq = (key) => [...new Set((slots || []).filter(s => !s.is_unplaced && s[key]).map(s => s[key]))]
            .sort(collator.compare);
        return { teachers: uniq('teacher_name'), rooms: uniq('classroom_name') };
    },

    /** filter: '' (όλα) | 't:<καθηγητής>' | 'r:<αίθουσα>' */
    matches(slot, filter) {
        if (!filter) return true;
        const value = filter.slice(2);
        return filter.startsWith('t:') ? slot.teacher_name === value : slot.classroom_name === value;
    },

    /**
     * Ομαδοποίηση μιας μέρας σε «Τώρα / Ακολουθεί / Αργότερα».
     * now = «HH:MM» για σήμερα, ή null για άλλη μέρα (όλα στο «Αργότερα»).
     */
    buildDay(slots, periods, day, now, filter = '') {
        const byPeriod = new Map((periods || []).map(p => [p.id, p]));
        const groups = new Map();
        (slots || []).forEach(s => {
            const p = byPeriod.get(s.period_id);
            if (s.is_unplaced || s.day_of_week !== day || !p || !TodayHelpers.matches(s, filter)) return;
            if (!groups.has(p.id)) groups.set(p.id, { period: p, items: [] });
            groups.get(p.id).items.push(s);
        });
        const collator = new Intl.Collator('el');
        const ordered = [...groups.values()]
            .sort((a, b) => TodayHelpers.minutes(a.period.start_time) - TodayHelpers.minutes(b.period.start_time));
        ordered.forEach(g => g.items.sort((a, b) =>
            collator.compare(a.classroom_name || '', b.classroom_name || '')));

        const result = { current: null, next: null, later: [], done: 0, empty: ordered.length === 0 };
        if (now === null || now === undefined) {
            result.later = ordered;
            return result;
        }
        const t = TodayHelpers.minutes(now);
        ordered.forEach(g => {
            const start = TodayHelpers.minutes(g.period.start_time);
            const end = TodayHelpers.minutes(g.period.end_time);
            if (end <= t) result.done += 1;
            else if (start <= t) result.current = g;
            else if (!result.next) result.next = g;
            else result.later.push(g);
        });
        return result;
    },

    _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    /** «26′» / «1 ώρα 5′» — πόσο απομένει. */
    durationText(mins) {
        const m = Math.max(0, Math.round(mins));
        if (m < 60) return `${m}′`;
        const h = Math.floor(m / 60);
        const r = m % 60;
        return `${h} ${h === 1 ? 'ώρα' : 'ώρες'}${r ? ` ${r}′` : ''}`;
    },

    /** Η διδακτική ώρα που τρέχει τώρα ([start, end)), ακόμα κι αν δεν έχει μάθημα. */
    currentPeriod(periods, now) {
        if (now === null || now === undefined) return null;
        const t = TodayHelpers.minutes(now);
        return (periods || []).filter(p => !p.is_break).find(p =>
            TodayHelpers.minutes(p.start_time) <= t && t < TodayHelpers.minutes(p.end_time)) || null;
    },

    /**
     * «Ελεύθερα τώρα»: αίθουσες χωρίς μάθημα στην τρέχουσα ώρα και καθηγητές
     * της ημέρας που δεν διδάσκουν τώρα αλλά έχουν κι άλλο μάθημα σήμερα —
     * με «ως HH:MM» (πότε πιάνονται ξανά). Pure.
     */
    freeNow(slots, periods, rooms, day, now) {
        const period = TodayHelpers.currentPeriod(periods, now);
        if (!period) return null;
        const byId = new Map((periods || []).map(p => [p.id, p]));
        const todays = (slots || []).filter(s => !s.is_unplaced && s.day_of_week === day && byId.has(s.period_id));
        const startOf = (s) => TodayHelpers.minutes(byId.get(s.period_id).start_time);
        const nowStart = TodayHelpers.minutes(period.start_time);
        const busyRooms = new Set(todays.filter(s => s.period_id === period.id).map(s => s.classroom_name));
        const busyTeachers = new Set(todays.filter(s => s.period_id === period.id).map(s => s.teacher_name));
        const nextStart = (match) => {
            const later = todays.filter(s => match(s) && startOf(s) > nowStart).map(s => byId.get(s.period_id));
            if (!later.length) return null;
            later.sort((a, b) => TodayHelpers.minutes(a.start_time) - TodayHelpers.minutes(b.start_time));
            return later[0].start_time;
        };
        const collator = new Intl.Collator('el');
        const freeRooms = (rooms || [])
            .filter(r => r && r.name && !r.archived && !busyRooms.has(r.name))
            .map(r => ({ name: r.name, until: nextStart(s => s.classroom_name === r.name) }))
            .sort((a, b) => collator.compare(a.name, b.name));
        const teacherNames = [...new Set(todays.map(s => s.teacher_name).filter(Boolean))];
        const freeTeachers = teacherNames
            .filter(n => !busyTeachers.has(n))
            .map(n => ({ name: n, until: nextStart(s => s.teacher_name === n) }))
            .filter(t => t.until)
            .sort((a, b) => TodayHelpers.minutes(a.until) - TodayHelpers.minutes(b.until) || collator.compare(a.name, b.name));
        return { period, rooms: freeRooms, teachers: freeTeachers };
    },

    /**
     * Ποιο πρόγραμμα δείχνει το «Σήμερα»: το 📢 δημοσιευμένο (αυτό έχουν οι
     * καθηγητές), αν υπάρχει στη λίστα· αλλιώς όπως πριν (επιλογή χρήστη ή το
     * νεότερο κανονικό). → { id, published }
     */
    pickSolution(solutions, publications, preferredId, defaultId) {
        const list = (solutions || []).filter(s => !s.archived);
        const pub = (publications || []).find(p => list.some(s => s.id === p.solution_id));
        if (pub) return { id: pub.solution_id, published: true, publishedAt: pub.published_at || null };
        return { id: defaultId, published: false, publishedAt: null };
    },

    /**
     * Συγκρούσεις μιας μέρας: ίδιος καθηγητής, αίθουσα ή τμήμα σε δύο μαθήματα
     * την ίδια ώρα (δεν θα έπρεπε να συμβαίνει — π.χ. μετά από κλειδώματα). Pure.
     */
    countConflicts(slots, day) {
        const seen = new Map();
        (slots || []).forEach(s => {
            if (s.is_unplaced || s.day_of_week !== day) return;
            [['t', s.teacher_id ?? s.teacher_name], ['r', s.classroom_id ?? s.classroom_name], ['c', s.class_id ?? s.class_name]]
                .forEach(([k, v]) => {
                    if (v === null || v === undefined || v === '') return;
                    const key = `${s.period_id}|${k}|${v}`;
                    seen.set(key, (seen.get(key) || 0) + 1);
                });
        });
        return [...seen.values()].filter(n => n > 1).length;
    },

    /** Μικρό όνομα για το μήνυμα: «ΕΛΕΝΗ ΦΩΤΙΟΥ» → «ΕΛΕΝΗ». */
    firstName(full) {
        return String(full || '').trim().split(/\s+/)[0] || '';
    },

    /**
     * Έτοιμο μήνυμα προς τον αντικαταστάτη. items = [{ start, end, subject, class, room }]
     * (συνεχόμενες ώρες του ίδιου μαθήματος ενώνονται: «17:00–19:00»).
     * dayWord = «σήμερα» / «αύριο» / «την Πέμπτη».
     */
    substituteMessage(candidateName, absentName, items, dayWord = 'σήμερα') {
        const hello = TodayHelpers.firstName(candidateName);
        const sorted = (items || []).slice().sort((a, b) => TodayHelpers.minutes(a.start) - TodayHelpers.minutes(b.start));
        const merged = [];
        for (const i of sorted) {
            const last = merged[merged.length - 1];
            if (last && last.end === i.start && last.subject === i.subject && last.class === i.class && last.room === i.room) {
                last.end = i.end;
            } else {
                merged.push({ ...i });
            }
        }
        const parts = merged.map(i =>
            `${i.start}–${i.end} ${i.subject}${i.class ? ` (${i.class})` : ''}${i.room ? ` στην ${i.room}` : ''}`);
        const what = parts.length > 1 ? parts.slice(0, -1).join(', ') + ' και ' + parts[parts.length - 1] : (parts[0] || '');
        return `Καλησπέρα${hello ? ` ${hello}` : ''}! Μπορείς ${dayWord} ${what}, αντί για ${absentName || 'τον συνάδελφο'}; Ευχαριστώ!`;
    },

    _itemHtml(s, opts) {
        const esc = TodayHelpers._esc;
        return `
            <div class="today-item" data-slot-id="${s.id != null ? s.id : ''}">
                <button type="button" class="today-item-main" aria-expanded="false">
                    <span class="today-room">${esc(s.classroom_name || '—')}</span>
                    <span class="today-what"><b>${esc(s.subject_name || 'Μάθημα')}</b>
                        <small>${esc(s.class_name || '')}</small></span>
                    <span class="today-who">👤 ${esc(s.teacher_name || '—')}</span>
                    <span class="today-chev" aria-hidden="true">›</span>
                </button>
                <div class="today-actions" hidden></div>
            </div>`;
    },

    groupHtml(group, title, cls, opts = {}) {
        const esc = TodayHelpers._esc;
        const p = group.period;
        const items = group.items.map(s => TodayHelpers._itemHtml(s, opts)).join('');
        const note = opts.note ? ` <span class="today-note">${esc(opts.note)}</span>` : '';
        const head = `${title ? `${title} · ` : ''}${esc(p.start_time)}–${esc(p.end_time)}`;
        if (opts.collapsed) {
            const n = group.items.length;
            return `<details class="today-group ${cls}">
                        <summary><span class="today-group-title">${head}</span>
                            <span class="today-count">${n === 1 ? '1 μάθημα' : `${n} μαθήματα`}</span></summary>
                        ${items}
                    </details>`;
        }
        return `<section class="today-group ${cls}">
                    <h3><span class="today-group-title">${head}</span>${note}</h3>${items}
                </section>`;
    },

    /**
     * opts.now = «HH:MM» όταν είναι σήμερα: «λήγει σε …» στο Τώρα, «σε …» στο
     * Ακολουθεί, και οι επόμενες ώρες μαζεμένες (πάτημα = ανοίγουν).
     */
    buildHtml(day, opts = {}) {
        if (day.empty) return '<p class="text-muted today-empty">Κανένα μάθημα αυτή τη μέρα.</p>';
        const t = opts.now ? TodayHelpers.minutes(opts.now) : null;
        const parts = [];
        if (day.current) {
            const left = t !== null ? TodayHelpers.minutes(day.current.period.end_time) - t : null;
            parts.push(TodayHelpers.groupHtml(day.current, '🟢 Τώρα', 'is-now',
                { note: left !== null ? `λήγει σε ${TodayHelpers.durationText(left)}` : '' }));
        }
        if (day.next) {
            const until = t !== null ? TodayHelpers.minutes(day.next.period.start_time) - t : null;
            parts.push(TodayHelpers.groupHtml(day.next, '⏭ Ακολουθεί', 'is-next',
                { note: until !== null ? `σε ${TodayHelpers.durationText(until)}` : '' }));
        }
        if (!day.current && !day.next && day.done && !day.later.length) {
            parts.push('<p class="text-muted today-empty">✅ Τα μαθήματα της μέρας τελείωσαν.</p>');
        }
        const collapse = t !== null && (day.current || day.next);
        day.later.forEach(g => parts.push(TodayHelpers.groupHtml(g, '', '', { collapsed: collapse })));
        if (day.done) {
            parts.push(`<p class="text-muted today-done">${day.done === 1
                ? '1 ώρα έχει ήδη ολοκληρωθεί.' : `${day.done} ώρες έχουν ήδη ολοκληρωθεί.`}</p>`);
        }
        return parts.join('');
    },

    /** «Ελεύθερα τώρα» (μόνο για σήμερα, χωρίς φίλτρο). */
    freeHtml(free) {
        if (!free) return '';
        const esc = TodayHelpers._esc;
        const chip = (x, icon) => `<li class="today-free-item"><span>${icon} ${esc(x.name)}</span>
            <small>${x.until ? `ως ${esc(x.until)}` : 'όλη τη μέρα'}</small></li>`;
        const rooms = free.rooms.length
            ? free.rooms.map(r => chip(r, '🚪')).join('')
            : '<li class="text-muted today-free-none">Καμία ελεύθερη αίθουσα</li>';
        const teachers = free.teachers.map(x => chip(x, '👤')).join('');
        return `<section class="today-free" aria-label="Ελεύθερα τώρα">
                    <h3>Ελεύθερα τώρα <small class="text-muted">${esc(free.period.start_time)}–${esc(free.period.end_time)}</small></h3>
                    <ul class="today-free-list">${rooms}${teachers}</ul>
                </section>`;
    },
};

if (typeof module !== 'undefined' && module.exports) {
    module.exports = TodayHelpers;
}
